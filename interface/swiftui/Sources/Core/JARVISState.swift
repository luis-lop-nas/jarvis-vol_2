import Foundation
import SwiftUI

// MARK: - Fase del agente (colores semánticos P2, P7)

enum AgentPhase: String, Equatable {
    case thinking   // llamando al modelo
    case acting     // ejecutando herramienta
    case completed  // tarea completada
    case error      // error o timeout
}

// MARK: - Tipos de datos

struct LogStep: Identifiable, Codable {
    let id: String
    let description: String
    var status: StepStatus
    var timestamp: Date = Date()

    enum StepStatus: String, Codable {
        case pending, active, completed, failed
    }

    // elapsed relativo: "hace 2s" / "hace 1m"
    var elapsed: String {
        let seconds = Int(-timestamp.timeIntervalSinceNow)
        if seconds < 60 { return "hace \(seconds)s" }
        return "hace \(seconds / 60)m"
    }
}

struct ChatMessage: Identifiable {
    let id: UUID = UUID()
    let role: ChatRole
    let content: String
    let timestamp: Date = Date()

    enum ChatRole { case user, assistant }
}

struct AgentMessage: Identifiable, Codable {
    let id: UUID
    let type: String
    let message: String
    let progress: Double
    let step: [String: AnyCodableValue]?
    let result: [String: AnyCodableValue]?
    let state: String
    let timestamp: Date

    init(from update: AgentUpdate) {
        self.id = UUID()
        self.type = update.type
        self.message = update.message
        self.progress = update.progress
        self.step = update.step
        self.result = update.result
        self.state = update.state
        self.timestamp = Date()
    }
}

struct AgentUpdate: Decodable {
    let type: String
    let message: String
    let progress: Double
    let step: [String: AnyCodableValue]?
    let result: [String: AnyCodableValue]?
    let state: String
}

// Envoltorio para valores JSON heterogéneos en Codable
enum AnyCodableValue: Codable {
    case string(String)
    case int(Int)
    case double(Double)
    case bool(Bool)
    case null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let v = try? c.decode(String.self) { self = .string(v); return }
        if let v = try? c.decode(Int.self) { self = .int(v); return }
        if let v = try? c.decode(Double.self) { self = .double(v); return }
        if let v = try? c.decode(Bool.self) { self = .bool(v); return }
        self = .null
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let v): try c.encode(v)
        case .int(let v): try c.encode(v)
        case .double(let v): try c.encode(v)
        case .bool(let v): try c.encode(v)
        case .null: try c.encodeNil()
        }
    }
}

struct ConfirmationRequest: Identifiable {
    let id: String
    let actionDescription: String
    let command: String?
    let isDestructive: Bool
    let actionType: String         // e.g. "filesystem.eliminar"
    let affectedItems: [String]?   // lista de archivos/elementos afectados
    let affectedCount: Int         // total de elementos afectados
    let createdAt: Date = Date()
}

// MARK: - Estado de la UI

enum UIState: Equatable {
    case silent
    case notchPulse(status: String, model: String)
    case edgeLog(steps: [LogStep])
    case focusModal(query: String, response: String, steps: [LogStep])
    case inline(app: String, suggestion: String)

    static func == (lhs: UIState, rhs: UIState) -> Bool {
        switch (lhs, rhs) {
        case (.silent, .silent): return true
        case (.notchPulse, .notchPulse): return true
        case (.edgeLog, .edgeLog): return true
        case (.focusModal, .focusModal): return true
        case (.inline, .inline): return true
        default: return false
        }
    }
}

// MARK: - Estado observable principal

@Observable
final class JARVISState {
    var uiState: UIState = .silent
    var sessionId: String = UUID().uuidString
    var isConnected: Bool = false
    var isDisconnected: Bool = false      // sin conexión >5s (P7)
    var pendingConfirmation: ConfirmationRequest? = nil
    var messages: [AgentMessage] = []
    var currentProgress: Double = 0.0
    var focusModalShown: Bool = false
    var inputText: String = ""

    // P2 — Fase y herramienta activa para colores semánticos en notch
    var agentPhase: AgentPhase = .thinking
    var currentToolName: String? = nil

    // P4 — Historial de conversación e info del modelo
    var conversationHistory: [ChatMessage] = []
    var lastModelUsed: String? = nil
    var lastTokenCount: Int? = nil
    var lastCostUsd: Double? = nil

    // P7 — Mensaje de error visible en notch
    var errorMessage: String? = nil

    private var logSteps: [LogStep] = []

    // P2 — Texto/modelo que el notch muestra en cada fase. El notch es el
    // elemento persistente y debe reflejar SIEMPRE la fase (los 4 colores),
    // aunque además se muestre el edge log durante `acting`.
    var notchStatusText: String {
        switch agentPhase {
        case .thinking:  return "Pensando…"
        case .acting:    return currentToolName ?? "Ejecutando"
        case .completed: return "Listo"
        case .error:     return errorMessage ?? "Error"
        }
    }

    var notchModel: String { lastModelUsed ?? "" }

    func applyUpdate(_ update: AgentUpdate) {
        withAnimation(.spring(response: 0.3, dampingFraction: 0.8)) {
            currentProgress = update.progress

            // Extraer metadatos de modelo/tokens del campo step
            if let stepDict = update.step {
                if case .string(let model) = stepDict["modelo"] ?? stepDict["model"] {
                    lastModelUsed = model
                }
                if case .int(let tokens) = stepDict["tokens"] ?? stepDict["total_tokens"] {
                    lastTokenCount = tokens
                }
                if case .double(let cost) = stepDict["cost_usd"] ?? stepDict["total_cost_usd"] {
                    lastCostUsd = cost
                }
            }

            switch update.type {
            case "thinking", "pensando":
                agentPhase = .thinking
                currentToolName = nil
                if case .focusModal(let q, let r, _) = uiState {
                    uiState = .focusModal(query: q, response: r, steps: logSteps)
                } else {
                    uiState = .notchPulse(status: update.message, model: lastModelUsed ?? "")
                }
                _addStep(id: UUID().uuidString, description: update.message, status: .active)

            case "acting", "actuando":
                agentPhase = .acting
                let toolName = update.step.flatMap { dict -> String? in
                    guard case .string(let t) = dict["herramienta"] ?? dict["tool"] else { return nil }
                    return t
                }
                currentToolName = toolName

                let step = update.step.flatMap { dict -> LogStep? in
                    guard case .string(let id) = dict["id"],
                          case .string(let desc) = dict["descripcion"] else { return nil }
                    return LogStep(id: id, description: desc, status: .active)
                }
                if let step { _updateStep(step) }

                if case .focusModal(let q, let r, _) = uiState {
                    uiState = .focusModal(query: q, response: r, steps: logSteps)
                } else {
                    uiState = .edgeLog(steps: logSteps)
                }

            case "waiting", "esperando":
                agentPhase = .thinking
                let actionId = (update.step.flatMap { dict -> String? in
                    guard case .string(let id) = dict["id"] else { return nil }
                    return id
                }) ?? UUID().uuidString
                let isDestructive = (update.step.flatMap { dict -> Bool? in
                    guard case .bool(let v) = dict["requiere_confirmacion"] else { return nil }
                    return v
                }) ?? false
                let actionType = (update.step.flatMap { dict -> String? in
                    guard case .string(let t) = dict["herramienta"] ?? dict["action_type"] else { return nil }
                    return t
                }) ?? ""
                // affected_items: array de strings
                let affectedItems: [String]? = nil
                let affectedCount: Int
                if let stepDict = update.step,
                   case .int(let count) = stepDict["affected_count"] {
                    affectedCount = count
                } else {
                    affectedCount = 0
                }

                pendingConfirmation = ConfirmationRequest(
                    id: actionId,
                    actionDescription: update.message,
                    command: update.step.flatMap { dict -> String? in
                        guard case .string(let cmd) = dict["herramienta"] else { return nil }
                        return cmd
                    },
                    isDestructive: isDestructive,
                    actionType: actionType,
                    affectedItems: affectedItems,
                    affectedCount: affectedCount
                )
                focusModalShown = true

            case "inline", "sugerencia":
                // Sugerencia contextual anclada a la app activa (P5). El bundle id
                // opcional en step["app"] elige la variante de InlineView; si falta,
                // se usa genérico. Sin este caso, uiState nunca llegaba a .inline.
                let app = (update.step.flatMap { dict -> String? in
                    guard case .string(let a) = dict["app"] ?? dict["bundle_id"] else { return nil }
                    return a
                }) ?? ""
                agentPhase = .completed
                uiState = .inline(app: app, suggestion: update.message)

            case "done", "listo":
                agentPhase = .completed
                currentToolName = nil
                _markAllStepsCompleted()
                if case .focusModal(let q, _, _) = uiState {
                    uiState = .focusModal(query: q, response: update.message, steps: logSteps)
                    // Añadir al historial de conversación
                    conversationHistory.append(ChatMessage(role: .assistant, content: update.message))
                }
                pendingConfirmation = nil
                currentProgress = 1.0
                DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) { [weak self] in
                    withAnimation { self?.uiState = .silent }
                }

            case "error":
                agentPhase = .error
                currentToolName = nil
                errorMessage = update.message
                _markAllStepsFailed()
                if case .focusModal(let q, _, _) = uiState {
                    uiState = .focusModal(query: q, response: "Error: \(update.message)", steps: logSteps)
                } else {
                    uiState = .notchPulse(status: update.message, model: lastModelUsed ?? "")
                }
                pendingConfirmation = nil
                // Auto-reset a silent tras 5s
                DispatchQueue.main.asyncAfter(deadline: .now() + 5.0) { [weak self] in
                    withAnimation(.easeOut(duration: 0.5)) {
                        self?.uiState = .silent
                        self?.agentPhase = .thinking
                        self?.errorMessage = nil
                    }
                }

            default:
                break
            }

            let msg = AgentMessage(from: update)
            messages.append(msg)
            if messages.count > 100 { messages.removeFirst() }
        }
    }

    func addUserMessage(_ text: String) {
        conversationHistory.append(ChatMessage(role: .user, content: text))
    }

    /// Confirmación de acción sensible (ConfirmationManager). Trae el
    /// confirmation_id real y la lista de elementos afectados, que la tarjeta
    /// muestra en "Ver N elementos". G6.
    func applyConfirmation(_ data: ConfirmationBroadcast.ConfirmationData) {
        withAnimation(.spring(response: 0.3, dampingFraction: 0.8)) {
            agentPhase = .thinking
            pendingConfirmation = ConfirmationRequest(
                id: data.confirmationId,
                actionDescription: data.action,
                command: data.command,
                isDestructive: (data.riskLevel == "dangerous"),
                actionType: data.actionType ?? "",
                affectedItems: data.affectedItems,
                affectedCount: data.affectedCount ?? (data.affectedItems?.count ?? 0)
            )
            // Surface el modal aunque el overlay esté en reposo: sin poner uiState
            // en .focusModal, _syncWindowsToState no abre la ventana y la tarjeta
            // de confirmación no llegaría a verse.
            if case .focusModal = uiState {} else {
                uiState = .focusModal(query: "", response: "", steps: [])
            }
            focusModalShown = true
        }
    }

    /// Estado de sesión enviado al (re)conectar (ADR-80). Si había una
    /// confirmación pendiente, la reconstruye para que la tarjeta reaparezca. G4.
    func applySessionState(_ msg: SessionStateMessage) {
        guard let pc = msg.pendingConfirmation else { return }
        withAnimation(.spring(response: 0.3, dampingFraction: 0.8)) {
            pendingConfirmation = ConfirmationRequest(
                id: pc.requestId,
                actionDescription: pc.actionDescription,
                command: pc.command,
                isDestructive: (pc.riskLevel == "dangerous"),
                actionType: "",
                affectedItems: nil,
                affectedCount: 0
            )
            focusModalShown = true
        }
    }

    func reset() {
        logSteps = []
        pendingConfirmation = nil
        currentProgress = 0.0
        inputText = ""
        agentPhase = .thinking
        currentToolName = nil
        errorMessage = nil
    }

    // MARK: Private

    private func _addStep(id: String, description: String, status: LogStep.StepStatus) {
        if let idx = logSteps.firstIndex(where: { $0.id == id }) {
            logSteps[idx].status = status
        } else {
            logSteps.append(LogStep(id: id, description: description, status: status))
        }
        if logSteps.count > 20 { logSteps.removeFirst() }
    }

    private func _updateStep(_ step: LogStep) {
        if let idx = logSteps.firstIndex(where: { $0.id == step.id }) {
            logSteps[idx] = step
        } else {
            logSteps.append(step)
        }
    }

    private func _markAllStepsCompleted() {
        for i in logSteps.indices where logSteps[i].status == .active {
            logSteps[i].status = .completed
        }
    }

    private func _markAllStepsFailed() {
        for i in logSteps.indices where logSteps[i].status == .active {
            logSteps[i].status = .failed
        }
    }
}
