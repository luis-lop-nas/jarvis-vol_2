import SwiftUI

// MARK: - FocusModalView
// Panel central — invocado con ⌘Space.
// Tamaño: 480×auto (máx 600px).
// Posición: center-screen, 130px desde arriba.
// Fondo: #0d0d0f opacity 0.94 con NSVisualEffectView vibrancy.
// Ring: 0.5px rgba(55,138,221,0.2). BR: 20px.

struct FocusModalView: View {
    @Bindable var state: JARVISState
    let onClose: () -> Void
    let onSend: (String) -> Void
    let onConfirm: (String, Bool) -> Void

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
            .frame(maxHeight: 600)
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
            // Header
            header
            Divider().opacity(0.15)

            // Response (streaming)
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

            // Input bar
            inputBar

            // Footer hint
            footer
        }
    }

    // MARK: Subviews

    private var header: some View {
        HStack(spacing: 10) {
            Circle()
                .fill(Color(red: 0.22, green: 0.54, blue: 0.87))
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
        .frame(maxHeight: 240)
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

    private var inputBar: some View {
        HStack(spacing: 10) {
            TextField("Escribe un mensaje…", text: $state.inputText)
                .textFieldStyle(.plain)
                .font(.system(size: 13))
                .foregroundStyle(.white)
                .onSubmit { _sendMessage() }

            Button(action: _sendMessage) {
                Image(systemName: "arrow.up")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(.white)
                    .padding(6)
                    .background(blue, in: Circle())
            }
            .buttonStyle(.plain)
            .disabled(state.inputText.isEmpty)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
    }

    private var footer: some View {
        Text("Esc para cerrar · ⌘↵ para confirmar")
            .font(.system(size: 10))
            .foregroundStyle(textMuted)
            .padding(.bottom, 10)
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

    private func _sendMessage() {
        let text = state.inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        state.inputText = ""
        onSend(text)
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
