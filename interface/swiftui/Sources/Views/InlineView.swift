import SwiftUI

// MARK: - InlineView
// Vista contextual que se adapta a la app activa.
// Desaparece al hacer click fuera. Sin robar foco.

struct InlineView: View {
    let app: String
    let suggestion: String
    let onApply: () -> Void
    let onDismiss: () -> Void

    var body: some View {
        Group {
            switch _appKind() {
            case .vscode:
                VSCodeInline(suggestion: suggestion, onApply: onApply, onDismiss: onDismiss)
            case .finder:
                FinderInline(suggestion: suggestion, onApply: onApply, onDismiss: onDismiss)
            case .safari:
                SafariInline(suggestion: suggestion, onApply: onApply, onDismiss: onDismiss)
            case .generic:
                GenericInline(suggestion: suggestion, onApply: onApply, onDismiss: onDismiss)
            }
        }
    }

    private enum AppKind { case vscode, finder, safari, generic }

    private func _appKind() -> AppKind {
        let lower = app.lowercased()
        if lower.contains("code") || lower.contains("xcode") { return .vscode }
        if lower.contains("finder") { return .finder }
        if lower.contains("safari") { return .safari }
        return .generic
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
