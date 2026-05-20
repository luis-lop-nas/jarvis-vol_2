import SwiftUI

// MARK: - InlineView
// Vista contextual que se adapta a la app activa.
// Auto-dismiss a los 8s sin interacción (P5b).
// Posición configurada por bundleId en WindowManager (P5a).

struct InlineView: View {
    let app: String
    let suggestion: String
    let onApply: () -> Void
    let onDismiss: () -> Void

    @State private var dismissTimer: Timer?
    @State private var isHovered = false

    var body: some View {
        Group {
            switch _appKind() {
            case .vscode:
                VSCodeInline(suggestion: suggestion, onApply: _apply, onDismiss: _dismiss)
            case .finder:
                FinderInline(suggestion: suggestion, onApply: _apply, onDismiss: _dismiss)
            case .safari:
                SafariInline(suggestion: suggestion, onApply: _apply, onDismiss: _dismiss)
            case .terminal:
                TerminalChip(suggestion: suggestion, onDismiss: _dismiss)
            case .mail:
                MailChip(suggestion: suggestion, onApply: _apply, onDismiss: _dismiss)
            case .generic:
                GenericInline(suggestion: suggestion, onApply: _apply, onDismiss: _dismiss)
            }
        }
        .onHover { over in
            isHovered = over
            if over {
                dismissTimer?.invalidate()
            } else {
                _resetDismissTimer()
            }
        }
        .onAppear { _resetDismissTimer() }
        .onDisappear { dismissTimer?.invalidate() }
    }

    // MARK: Private

    private enum AppKind { case vscode, finder, safari, terminal, mail, generic }

    private func _appKind() -> AppKind {
        let lower = app.lowercased()
        if lower.contains("vscode") || lower.contains("code") || lower.contains("xcode") { return .vscode }
        if lower.contains("finder") { return .finder }
        if lower.contains("safari") || lower.contains("chrome") || lower.contains("firefox") { return .safari }
        if lower.contains("terminal") || lower.contains("iterm") || lower.contains("warp") { return .terminal }
        if lower.contains("mail") { return .mail }
        return .generic
    }

    private func _resetDismissTimer() {
        dismissTimer?.invalidate()
        dismissTimer = Timer.scheduledTimer(withTimeInterval: 8.0, repeats: false) { _ in
            DispatchQueue.main.async {
                withAnimation(.easeOut(duration: 0.3)) { onDismiss() }
            }
        }
    }

    private func _apply() {
        dismissTimer?.invalidate()
        onApply()
    }

    private func _dismiss() {
        dismissTimer?.invalidate()
        onDismiss()
    }
}

// MARK: - VS Code inline card

private struct VSCodeInline: View {
    let suggestion: String
    let onApply: () -> Void
    let onDismiss: () -> Void

    private let blue = Color(red: 0.22, green: 0.54, blue: 0.87)

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Rectangle()
                .fill(blue)
                .frame(width: 2)
                .frame(maxHeight: .infinity)
            VStack(alignment: .leading, spacing: 10) {
                Text(suggestion)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(.white.opacity(0.9))
                    .lineLimit(4)

                HStack(spacing: 6) {
                    Spacer()
                    Button("Ignorar") { onDismiss() }
                        .buttonStyle(SmallGhostStyle())
                    Button("Aplicar") { onApply() }
                        .buttonStyle(SmallFilledStyle(color: blue))
                }
            }
            .padding(12)
        }
        .frame(width: 280)
        .background(Color(red: 0.10, green: 0.10, blue: 0.12).opacity(0.96))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .strokeBorder(blue.opacity(0.3), lineWidth: 1)
        )
    }
}

// MARK: - Finder sidebar suggestion

private struct FinderInline: View {
    let suggestion: String
    let onApply: () -> Void
    let onDismiss: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(suggestion)
                .font(.system(size: 11))
                .foregroundStyle(.white.opacity(0.85))
                .lineLimit(3)

            Button("Organizar") { onApply() }
                .buttonStyle(SmallFilledStyle(color: Color(red: 0.22, green: 0.54, blue: 0.87)))
                .frame(maxWidth: .infinity)
        }
        .padding(12)
        .frame(width: 140)
        .background(Color(red: 0.10, green: 0.10, blue: 0.12).opacity(0.95))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

// MARK: - Safari popover

private struct SafariInline: View {
    let suggestion: String
    let onApply: () -> Void
    let onDismiss: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Text(suggestion)
                .font(.system(size: 11))
                .foregroundStyle(.white.opacity(0.88))
                .lineLimit(1)
            Button("OK") { onApply() }
                .buttonStyle(SmallFilledStyle(color: Color(red: 0.22, green: 0.54, blue: 0.87)))
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(Color(red: 0.10, green: 0.10, blue: 0.12).opacity(0.95))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

// MARK: - Terminal chip (P5c)
// Chip compacto en esquina inferior izquierda. Muestra la sugerencia contextual.

private struct TerminalChip: View {
    let suggestion: String
    let onDismiss: () -> Void

    private let green = Color(red: 0.11, green: 0.62, blue: 0.46)

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "terminal")
                .font(.system(size: 10))
                .foregroundStyle(green)
            Text(suggestion)
                .font(.system(size: 10, design: .monospaced))
                .foregroundStyle(.white.opacity(0.85))
                .lineLimit(1)
            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .font(.system(size: 8))
                    .foregroundStyle(.white.opacity(0.4))
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(Color(red: 0.08, green: 0.10, blue: 0.09).opacity(0.96))
        .clipShape(RoundedRectangle(cornerRadius: 6))
        .overlay(
            RoundedRectangle(cornerRadius: 6)
                .strokeBorder(green.opacity(0.3), lineWidth: 1)
        )
    }
}

// MARK: - Mail chip (P5c)

private struct MailChip: View {
    let suggestion: String
    let onApply: () -> Void
    let onDismiss: () -> Void

    private let blue = Color(red: 0.22, green: 0.54, blue: 0.87)

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "envelope")
                .font(.system(size: 10))
                .foregroundStyle(blue)
            Text(suggestion)
                .font(.system(size: 11))
                .foregroundStyle(.white.opacity(0.88))
                .lineLimit(1)
            Button("Ver") { onApply() }
                .buttonStyle(SmallFilledStyle(color: blue))
            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .font(.system(size: 8))
                    .foregroundStyle(.white.opacity(0.4))
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(Color(red: 0.10, green: 0.10, blue: 0.12).opacity(0.95))
        .clipShape(RoundedRectangle(cornerRadius: 6))
    }
}

// MARK: - Generic

private struct GenericInline: View {
    let suggestion: String
    let onApply: () -> Void
    let onDismiss: () -> Void

    var body: some View {
        SafariInline(suggestion: suggestion, onApply: onApply, onDismiss: onDismiss)
    }
}

// MARK: - Button styles

struct SmallGhostStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 10, weight: .medium))
            .foregroundStyle(.white.opacity(0.6))
            .padding(.horizontal, 10)
            .padding(.vertical, 4)
            .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(.white.opacity(0.3)))
            .opacity(configuration.isPressed ? 0.7 : 1.0)
    }
}

struct SmallFilledStyle: ButtonStyle {
    let color: Color

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 10, weight: .semibold))
            .foregroundStyle(.white)
            .padding(.horizontal, 10)
            .padding(.vertical, 4)
            .background(color, in: RoundedRectangle(cornerRadius: 4))
            .opacity(configuration.isPressed ? 0.8 : 1.0)
    }
}
