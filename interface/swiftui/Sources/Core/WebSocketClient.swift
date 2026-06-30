import Foundation

// MARK: - Mensajes salientes

enum ClientMessage: Encodable {
    case message(content: String, sessionId: String)
    case confirm(actionId: String, confirmed: Bool, sessionId: String)
    case cancel(sessionId: String)
    case ping

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case .message(let content, let sid):
            try c.encode("message", forKey: .type)
            try c.encode(content, forKey: .content)
            try c.encode(sid, forKey: .sessionId)
        case .confirm(let actionId, let confirmed, let sid):
            try c.encode("confirm", forKey: .type)
            try c.encode(actionId, forKey: .actionId)
            try c.encode(confirmed, forKey: .confirmed)
            try c.encode(sid, forKey: .sessionId)
        case .cancel(let sid):
            try c.encode("cancel", forKey: .type)
            try c.encode(sid, forKey: .sessionId)
        case .ping:
            try c.encode("ping", forKey: .type)
        }
    }

    enum CodingKeys: String, CodingKey {
        case type, content, sessionId = "session_id", actionId = "action_id", confirmed
    }
}

// MARK: - Mensaje de sincronización de estado (enviado al conectar/reconectar)

/// Sonda mínima para distinguir el tipo de mensaje antes del decode completo.
private struct MessageTypeProbe: Decodable {
    let type: String
}

/// Estado de sesión que el backend envía al (re)conectar — ADR-80.
/// No es un `AgentUpdate` (no trae `message`/`progress`/`state`), así que
/// requiere su propia ruta de decodificación.
struct SessionStateMessage: Decodable {
    let sessionState: String
    let currentStep: String?
    let pendingConfirmation: PendingConfirmation?

    struct PendingConfirmation: Decodable {
        let requestId: String
        let actionDescription: String
        let command: String?
        let riskLevel: String?
        let requiresAuth: Bool?

        enum CodingKeys: String, CodingKey {
            case requestId = "request_id"
            case actionDescription = "action_description"
            case command
            case riskLevel = "risk_level"
            case requiresAuth = "requires_auth"
        }
    }

    enum CodingKeys: String, CodingKey {
        case sessionState = "session_state"
        case currentStep = "current_step"
        case pendingConfirmation = "pending_confirmation"
    }
}

// MARK: - Confirmación de acción (ConfirmationManager → ws_sender.broadcast)

/// Broadcast de confirmación de una acción sensible (p.ej. borrar archivos).
/// Llega como `{"type":"waiting","data":{...}}`; a diferencia del `waiting`
/// del agente, trae el `confirmation_id` real (UUID) y la lista `affected_items`.
struct ConfirmationBroadcast: Decodable {
    let data: ConfirmationData

    struct ConfirmationData: Decodable {
        let confirmationId: String
        let action: String
        let command: String?
        let actionType: String?
        let riskLevel: String?
        let requiresAuth: Bool?
        let affectedItems: [String]?
        let affectedCount: Int?
        let expiresIn: Int?

        enum CodingKeys: String, CodingKey {
            case confirmationId = "confirmation_id"
            case action, command
            case actionType = "action_type"
            case riskLevel = "risk_level"
            case requiresAuth = "requires_auth"
            case affectedItems = "affected_items"
            case affectedCount = "affected_count"
            case expiresIn = "expires_in"
        }
    }
}

// MARK: - Cliente WebSocket

@MainActor
final class WebSocketClient: NSObject, URLSessionWebSocketDelegate {
    private let baseURL = URL(string: "ws://127.0.0.1:8765/ws")!
    private var task: URLSessionWebSocketTask?
    private var session: URLSession!
    private var reconnectDelay: TimeInterval = 1.0
    private let maxDelay: TimeInterval = 30.0
    private var isRunning = false
    private var sessionId: String = ""   // sesión real, reusada al reconectar

    var onUpdate: ((AgentUpdate) -> Void)?
    var onConnectionChange: ((Bool) -> Void)?
    var onLongDisconnect: (() -> Void)?  // llamado cuando reconexión tarda >5s (P7c)
    var onSessionState: ((SessionStateMessage) -> Void)?  // sync de estado al (re)conectar
    var onConfirmation: ((ConfirmationBroadcast.ConfirmationData) -> Void)?  // acción sensible

    override init() {
        super.init()
        session = URLSession(configuration: .default, delegate: self, delegateQueue: nil)
    }

    func connect(sessionId: String) {
        guard !isRunning else { return }
        isRunning = true
        reconnectDelay = 1.0
        self.sessionId = sessionId
        _connect(sessionId: sessionId)
    }

    func disconnect() {
        isRunning = false
        task?.cancel(with: .normalClosure, reason: nil)
        task = nil
    }

    func send(_ message: ClientMessage) {
        guard let task else { return }
        guard let data = try? JSONEncoder().encode(message),
              let text = String(data: data, encoding: .utf8) else { return }
        task.send(.string(text)) { _ in }
    }

    // MARK: Private

    private func _connect(sessionId: String) {
        var items = [URLQueryItem(name: "session_id", value: sessionId)]
        // El backend exige el token de API en /ws?token=...; sin él cierra
        // la conexión con código 1008 antes de aceptarla. main.py lo escribe
        // en ~/.jarvis/.api_token (0600).
        if let token = Self._readApiToken() {
            items.append(URLQueryItem(name: "token", value: token))
        }
        var url = baseURL
        url.append(queryItems: items)
        task = session.webSocketTask(with: url)
        task?.resume()
        _receiveLoop()
    }

    /// Lee el token de API escrito por el backend en ~/.jarvis/.api_token.
    private static func _readApiToken() -> String? {
        let path = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".jarvis/.api_token")
        guard let raw = try? String(contentsOf: path, encoding: .utf8) else { return nil }
        let token = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        return token.isEmpty ? nil : token
    }

    private func _receiveLoop() {
        task?.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(let msg):
                if case .string(let text) = msg, let data = text.data(using: .utf8) {
                    let probe = try? JSONDecoder().decode(MessageTypeProbe.self, from: data)
                    if probe?.type == "session_state",
                       let state = try? JSONDecoder().decode(SessionStateMessage.self, from: data) {
                        Task { @MainActor in self.onSessionState?(state) }
                    } else if probe?.type == "waiting",
                              let conf = try? JSONDecoder().decode(ConfirmationBroadcast.self, from: data) {
                        // Confirmación de acción: trae `data` con confirmation_id real
                        // y affected_items. El `waiting` del agente no tiene `data`,
                        // así que cae a la rama AgentUpdate de abajo.
                        Task { @MainActor in self.onConfirmation?(conf.data) }
                    } else if let update = try? JSONDecoder().decode(AgentUpdate.self, from: data) {
                        Task { @MainActor in self.onUpdate?(update) }
                    }
                }
                self._receiveLoop()
            case .failure:
                Task { @MainActor in self._scheduleReconnect() }
            }
        }
    }

    @MainActor
    private func _scheduleReconnect() {
        guard isRunning else { return }
        onConnectionChange?(false)
        let delay = reconnectDelay
        reconnectDelay = min(reconnectDelay * 2, maxDelay)

        // Notificar desconexión prolongada cuando el delay supera 5s (P7c)
        if delay > 5.0 {
            onLongDisconnect?()
        }

        Task {
            try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
            if self.isRunning {
                // Reusar la sesión real: usar un id distinto perdería el buffer
                // de mensajes (deque maxlen=50) y el scoping de confirmaciones.
                self._connect(sessionId: self.sessionId)
            }
        }
    }

    // MARK: URLSessionWebSocketDelegate

    nonisolated func urlSession(
        _ session: URLSession,
        webSocketTask: URLSessionWebSocketTask,
        didOpenWithProtocol protocol: String?
    ) {
        Task { @MainActor [weak self] in
            self?.reconnectDelay = 1.0
            self?.onConnectionChange?(true)
        }
    }

    nonisolated func urlSession(
        _ session: URLSession,
        webSocketTask: URLSessionWebSocketTask,
        didCloseWith closeCode: URLSessionWebSocketTask.CloseCode,
        reason: Data?
    ) {
        Task { @MainActor [weak self] in
            self?._scheduleReconnect()
        }
    }
}
