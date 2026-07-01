import SwiftUI

// MARK: - FocusModalView
// Panel central — invocado con ⌘⌥Space.
// Incluye: historial scrollable, respuesta streaming, input inline, footer de metadata.

struct FocusModalView: View {
    @Bindable var state: JARVISState
    let onClose: () -> Void
    let onSend: (String) -> Void
    let onConfirm: (String, Bool) -> Void

    @State private var replyText: String = ""
    @FocusState private var replyFocused: Bool

    private let bg = Color(red: 0.05, green: 0.05, blue: 0.06)
    private let blue = Color(red: 0.22, green: 0.54, blue: 0.87)
    private let textMuted = Color.white.opacity(0.35)

    var responseText: String {
        if case .focusModal(_, let r, _) = state.uiState { return r }
        return ""
    }

    var logSteps: [LogStep] {
        if case .focusModal(_, _, let steps) = state.uiState { return steps }
        return []
    }

    var body: some View {
        ZStack {
            // Scrim
            Color.black.opacity(0.30)
                .ignoresSafeArea()
                .onTapGesture { onClose() }

            // Modal
            VStack(spacing: 0) {
                modalContent
            }
            .frame(width: 480)
            .frame(maxHeight: 620)
            .background {
                ZStack {
                    VisualEffectBlur(material: .hudWindow, blendingMode: .behindWindow)
                    bg.opacity(0.88)
                }
                .clipShape(RoundedRectangle(cornerRadius: 20))
            }
            .overlay(
                RoundedRectangle(cornerRadius: 20)
                    .strokeBorder(blue.opacity(0.2), lineWidth: 0.5)
            )
            .shadow(color: .black.opacity(0.5), radius: 40, y: 20)
            .padding(.top, 130)
            .frame(maxHeight: .infinity, alignment: .top)
            .transition(.asymmetric(
                insertion: .move(edge: .top).combined(with: .opacity),
                removal: .opacity.animation(.easeOut(duration: 0.15))
            ))
        }
        .onAppear {
            // Auto-foco del input al abrir el modal (⌘⌥Space → escribir ya).
            // Pequeño delay para que la ventana sea key antes de pedir el foco.
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { replyFocused = true }
        }
        .onKeyPress(.escape) { onClose(); return .handled }
        .onKeyPress(.return, phases: .down) { event in
            if event.modifiers.contains(.command),
               let conf = state.pendingConfirmation {
                onConfirm(conf.id, true)
                return .handled
            }
            return .ignored
        }
    }

    private var modalContent: some View {
        VStack(spacing: 0) {
            header
            Divider().opacity(0.15)

            // Historial de conversación (P4b)
            if !state.conversationHistory.isEmpty {
                conversationHistory
                Divider().opacity(0.10)
            }

            // Respuesta actual (streaming)
            if !responseText.isEmpty {
                responseArea
                Divider().opacity(0.12)
            }

            // ConfirmationCard (si hay acción pendiente)
            if let conf = state.pendingConfirmation {
                ConfirmationCard(
                    request: conf,
                    onConfirm: { onConfirm(conf.id, true) },
                    onCancel: { onConfirm(conf.id, false) }
                )
                .padding(12)
                Divider().opacity(0.12)
            }

            // Action log
            if !logSteps.isEmpty {
                actionLog
                Divider().opacity(0.12)
            }

            // Input inline (P4a)
            inlineReply
            Divider().opacity(0.08)

            // Footer hint + metadata de modelo (P4d)
            footer
        }
    }

    // MARK: Subviews

    private var header: some View {
        HStack(spacing: 10) {
            Circle()
                .fill(blue)
                .frame(width: 24, height: 24)
                .overlay(
                    Text("J")
                        .font(.system(size: 12, weight: .bold, design: .rounded))
                        .foregroundStyle(.white)
                )
            Text("JARVIS")
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(.white)
            Spacer()
            if state.currentProgress > 0 && state.currentProgress < 1 {
                ProgressView(value: state.currentProgress)
                    .tint(blue)
                    .frame(width: 60)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
    }

    // Historial scrollable (últimos mensajes del turno)
    private var conversationHistory: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 8) {
                    ForEach(state.conversationHistory) { msg in
                        MessageBubble(message: msg)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
            }
            .frame(maxHeight: 180)
            .onChange(of: state.conversationHistory.count) { _, _ in
                if let last = state.conversationHistory.last {
                    withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                }
            }
        }
    }

    private var responseArea: some View {
        ScrollView {
            Text(responseText)
                .font(.system(size: 13))
                .foregroundStyle(.white.opacity(0.92))
                .lineSpacing(8)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 20)
                .padding(.vertical, 14)
                .textSelection(.enabled)
        }
        .frame(maxHeight: 200)
    }

    private var actionLog: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(logSteps.suffix(5)) { step in
                HStack(spacing: 8) {
                    stepIcon(step)
                    Text(step.description)
                        .font(.system(size: 10))
                        .foregroundStyle(textMuted)
                        .lineLimit(1)
                }
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 10)
    }

    // Input inline para respuesta rápida (P4a)
    private var inlineReply: some View {
        HStack(spacing: 8) {
            TextField("responder…", text: $replyText)
                .textFieldStyle(.plain)
                .font(.system(size: 12))
                .foregroundStyle(.white)
                .focused($replyFocused)
                .onSubmit { _sendReply() }

            if !replyText.isEmpty {
                Button(action: _sendReply) {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.system(size: 18))
                        .foregroundStyle(blue)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
        .background(Color.white.opacity(0.05))
        .cornerRadius(8)
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
    }

    // Footer con hint + metadata del modelo (P4d)
    private var footer: some View {
        HStack(spacing: 0) {
            Text("Esc · ⌘⌥Space para cerrar")
                .font(.system(size: 10))
                .foregroundStyle(textMuted)

            Spacer()

            if let model = state.lastModelUsed {
                Text(model)
                    .font(.system(size: 10))
                    .foregroundStyle(textMuted)
            }
            if let tokens = state.lastTokenCount {
                Text("  \(tokens) tok")
                    .font(.system(size: 10))
                    .foregroundStyle(textMuted)
            }
            if let cost = state.lastCostUsd, cost > 0 {
                Text(String(format: "  $%.4f", cost))
                    .font(.system(size: 10))
                    .foregroundStyle(textMuted)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 8)
    }

    @ViewBuilder
    private func stepIcon(_ step: LogStep) -> some View {
        switch step.status {
        case .completed:
            Image(systemName: "checkmark")
                .font(.system(size: 9, weight: .bold))
                .foregroundStyle(.green.opacity(0.8))
        case .active:
            ProgressView().scaleEffect(0.5).tint(blue)
        case .failed:
            Image(systemName: "xmark")
                .font(.system(size: 9))
                .foregroundStyle(.red.opacity(0.7))
        case .pending:
            Circle().fill(textMuted).frame(width: 4, height: 4)
        }
    }

    private func _sendReply() {
        let text = replyText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        replyText = ""
        state.addUserMessage(text)
        onSend(text)
    }
}

// MARK: - Burbuja de mensaje en historial

private struct MessageBubble: View {
    let message: ChatMessage

    private let blue = Color(red: 0.22, green: 0.54, blue: 0.87)

    var body: some View {
        HStack {
            if message.role == .user { Spacer(minLength: 40) }

            Text(message.content)
                .font(.system(size: 12))
                .foregroundStyle(message.role == .user ? .white : .white.opacity(0.85))
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(
                    message.role == .user
                        ? blue.opacity(0.3)
                        : Color.white.opacity(0.06),
                    in: RoundedRectangle(cornerRadius: 10)
                )
                .lineLimit(6)

            if message.role == .assistant { Spacer(minLength: 40) }
        }
    }
}

// MARK: - NSVisualEffectView wrapper

struct VisualEffectBlur: NSViewRepresentable {
    var material: NSVisualEffectView.Material
    var blendingMode: NSVisualEffectView.BlendingMode

    func makeNSView(context: Context) -> NSVisualEffectView {
        let v = NSVisualEffectView()
        v.material = material
        v.blendingMode = blendingMode
        v.state = .active
        return v
    }

    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {
        nsView.material = material
        nsView.blendingMode = blendingMode
    }
}
