import Foundation
import SwiftUI

// MARK: - Tipos de datos

struct LogStep: Identifiable, Codable {
    let id: String
    let description: String
    var status: StepStatus

    enum StepStatus: String, Codable {
        case pending, active, completed, failed
    }
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
    var pendingConfirmation: ConfirmationRequest? = nil
    var messages: [AgentMessage] = []
    var currentProgress: Double = 0.0
    var focusModalShown: Bool = false
    var inputText: String = ""

    private var logSteps: [LogStep] = []

    func applyUpdate(_ update: AgentUpdate) {
        withAnimation(.spring(response: 0.3, dampingFraction: 0.8)) {
            currentProgress = update.progress

            switch update.type {
            case "thinking":
                if case .focusModal(let q, let r, _) = uiState {
                    uiState = .focusModal(query: q, response: r, steps: logSteps)
                } else {
                    uiState = .notchPulse(status: update.message, model: "")
                }
                _addStep(id: UUID().uuidString, description: update.message, status: .active)

            case "acting":
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

            case "waiting":
                let actionId = (update.step.flatMap { dict -> String? in
                    guard case .string(let id) = dict["id"] else { return nil }
                    return id
                }) ?? UUID().uuidString
                let isDestructive = (update.step.flatMap { dict -> Bool? in
                    guard case .bool(let v) = dict["requiere_confirmacion"] else { return nil }
                    return v
                }) ?? false
                pendingConfirmation = ConfirmationRequest(
                    id: actionId,
                    actionDescription: update.message,
                    command: update.step.flatMap { dict -> String? in
                        guard case .string(let cmd) = dict["herramienta"] else { return nil }
                        return cmd
                    },
                    isDestructive: isDestructive
                )
                focusModalShown = true

            case "done":
                _markAllStepsCompleted()
                if case .focusModal(let q, _, _) = uiState {
                    uiState = .focusModal(query: q, response: update.message, steps: logSteps)
                }
                pendingConfirmation = nil
                currentProgress = 1.0
                DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) { [weak self] in
                    withAnimation { self?.uiState = .silent }
                }

            case "error":
                _markAllStepsFailed()
                if case .focusModal(let q, _, _) = uiState {
                    uiState = .focusModal(query: q, response: "Error: \(update.message)", steps: logSteps)
                }
                pendingConfirmation = nil

            default:
                break
            }

            let msg = AgentMessage(from: update)
            messages.append(msg)
            if messages.count > 100 { messages.removeFirst() }
        }
    }

    func reset() {
        logSteps = []
        pendingConfirmation = nil
        currentProgress = 0.0
        inputText = ""
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
