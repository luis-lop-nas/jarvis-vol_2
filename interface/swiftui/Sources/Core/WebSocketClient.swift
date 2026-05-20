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

// MARK: - Cliente WebSocket

@MainActor
final class WebSocketClient: NSObject, URLSessionWebSocketDelegate {
    private let baseURL = URL(string: "ws://127.0.0.1:8765/ws")!
    private var task: URLSessionWebSocketTask?
    private var session: URLSession!
    private var reconnectDelay: TimeInterval = 1.0
    private let maxDelay: TimeInterval = 30.0
    private var isRunning = false

    var onUpdate: ((AgentUpdate) -> Void)?
    var onConnectionChange: ((Bool) -> Void)?
    var onLongDisconnect: (() -> Void)?  // llamado cuando reconexión tarda >5s (P7c)

    override init() {
        super.init()
        session = URLSession(configuration: .default, delegate: self, delegateQueue: nil)
    }

    func connect(sessionId: String) {
        guard !isRunning else { return }
        isRunning = true
        reconnectDelay = 1.0
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
        var url = baseURL
        url.append(queryItems: [URLQueryItem(name: "session_id", value: sessionId)])
        task = session.webSocketTask(with: url)
        task?.resume()
        _receiveLoop()
    }

    private func _receiveLoop() {
        task?.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(let msg):
                if case .string(let text) = msg,
                   let data = text.data(using: .utf8),
                   let update = try? JSONDecoder().decode(AgentUpdate.self, from: data) {
                    Task { @MainActor in self.onUpdate?(update) }
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
                self._connect(sessionId: "reconnect")
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
