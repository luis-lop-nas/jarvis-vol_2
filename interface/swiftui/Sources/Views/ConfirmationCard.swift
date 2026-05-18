import SwiftUI

// MARK: - ConfirmationCard
// Card ámbar para acciones destructivas.
// Aparece dentro del FocusModal entre response y log.
// bg: #3d2800, border: #f0a030 @ 0.4

struct ConfirmationCard: View {
    let request: ConfirmationRequest
    let onConfirm: () -> Void
    let onCancel: () -> Void

    private let cardBg = Color(red: 0.24, green: 0.16, blue: 0.0)
    private let amber = Color(red: 0.94, green: 0.63, blue: 0.19)

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            // Header
            HStack(spacing: 6) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 10))
                    .foregroundStyle(amber)
                Text("CONFIRMAR ACCIÓN DESTRUCTIVA")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(amber)
                    .tracking(0.5)
            }

            // Descripción
            Text(request.actionDescription)
                .font(.system(size: 12))
                .foregroundStyle(.white.opacity(0.9))

            // Comando (si existe)
            if let cmd = request.command {
                Text(cmd)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(amber.opacity(0.85))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(.white.opacity(0.05), in: RoundedRectangle(cornerRadius: 4))
            }

            // Botones
            HStack(spacing: 8) {
                Spacer()
                Button("Cancelar") { onCancel() }
                    .buttonStyle(GhostButtonStyle(color: .white.opacity(0.6)))

                Button("Confirmar") { onConfirm() }
                    .buttonStyle(FilledButtonStyle(color: amber))
            }
        }
        .padding(14)
        .background(cardBg)
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .strokeBorder(amber.opacity(0.4), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }
}

// MARK: - Button Styles

private struct GhostButtonStyle: ButtonStyle {
    let color: Color

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 12, weight: .medium))
            .foregroundStyle(color)
            .padding(.horizontal, 14)
            .padding(.vertical, 6)
            .background(
                RoundedRectangle(cornerRadius: 6)
                    .strokeBorder(color, lineWidth: 1)
            )
            .opacity(configuration.isPressed ? 0.7 : 1.0)
    }
}

private struct FilledButtonStyle: ButtonStyle {
    let color: Color

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 12, weight: .semibold))
            .foregroundStyle(.black)
            .padding(.horizontal, 14)
            .padding(.vertical, 6)
            .background(color, in: RoundedRectangle(cornerRadius: 6))
            .opacity(configuration.isPressed ? 0.8 : 1.0)
    }
}
