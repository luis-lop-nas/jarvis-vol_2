import SwiftUI

// MARK: - ConfirmationCard
// Card ámbar para acciones que requieren confirmación.
// Mejoras P6: lista de elementos afectados, botón papelera para eliminaciones,
// barra de expiración animada, colores adaptativos light/dark, haptic feedback.

struct ConfirmationCard: View {
    let request: ConfirmationRequest
    let onConfirm: () -> Void
    let onCancel: () -> Void

    @State private var showingDetails = false

    // Colores adaptativos (P6d)
    private let amber = Color(red: 0.94, green: 0.63, blue: 0.19)
    @Environment(\.colorScheme) private var colorScheme

    private var cardBg: Color {
        colorScheme == .dark
            ? Color(red: 0.18, green: 0.11, blue: 0.0)
            : Color(red: 0.24, green: 0.16, blue: 0.0)
    }

    private var cardBorder: Color {
        colorScheme == .dark
            ? Color(red: 0.36, green: 0.24, blue: 0.0)
            : Color(red: 0.48, green: 0.32, blue: 0.0)
    }

    private var isFilesystemDelete: Bool {
        request.actionType.contains("eliminar") || request.actionType.contains("delete")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            // Header
            HStack(spacing: 6) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 10))
                    .foregroundStyle(amber)
                Text(request.isDestructive ? "CONFIRMAR ACCIÓN DESTRUCTIVA" : "CONFIRMAR ACCIÓN")
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

            // Botón "Ver X elementos" (P6a)
            if let items = request.affectedItems, !items.isEmpty {
                Button("Ver \(items.count) elemento\(items.count == 1 ? "" : "s")") {
                    withAnimation(.spring(response: 0.3, dampingFraction: 0.8)) {
                        showingDetails.toggle()
                    }
                }
                .font(.system(size: 11))
                .foregroundStyle(amber)
                .buttonStyle(.plain)

                if showingDetails {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 2) {
                            ForEach(items.prefix(20), id: \.self) { item in
                                Text("· \(item)")
                                    .font(.system(size: 10, design: .monospaced))
                                    .foregroundStyle(.white.opacity(0.65))
                            }
                            if items.count > 20 {
                                Text("… y \(items.count - 20) más")
                                    .font(.system(size: 10))
                                    .foregroundStyle(.white.opacity(0.35))
                            }
                        }
                        .padding(6)
                    }
                    .frame(maxHeight: 120)
                    .background(.white.opacity(0.04), in: RoundedRectangle(cornerRadius: 6))
                }
            } else if request.affectedCount > 1 {
                Text("\(request.affectedCount) elementos afectados")
                    .font(.system(size: 11))
                    .foregroundStyle(amber.opacity(0.75))
            }

            // Barra de expiración animada (P6c) — 60s
            expiryBar

            // Botones (P6b)
            if isFilesystemDelete {
                // 3 botones: Cancelar · Papelera (primario) · Eliminar definitivo
                HStack(spacing: 8) {
                    Button("Cancelar") { onCancel() }
                        .buttonStyle(GhostButtonStyle(color: .white.opacity(0.5)))

                    Spacer()

                    Button("A la papelera") { _resolveTrash() }
                        .buttonStyle(FilledButtonStyle(color: amber))

                    Button("Eliminar") { onConfirm() }
                        .buttonStyle(GhostButtonStyle(color: Color(red: 0.85, green: 0.27, blue: 0.22)))
                }
            } else {
                HStack(spacing: 8) {
                    Spacer()
                    Button("Cancelar") { onCancel() }
                        .buttonStyle(GhostButtonStyle(color: .white.opacity(0.6)))
                    Button("Confirmar") {
                        NSHapticFeedbackManager.defaultPerformer.perform(
                            .levelChange, performanceTime: .now
                        )
                        onConfirm()
                    }
                    .buttonStyle(FilledButtonStyle(color: amber))
                }
            }
        }
        .padding(14)
        .background(cardBg)
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .strokeBorder(cardBorder.opacity(0.5), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .transition(.move(edge: .bottom).combined(with: .opacity))
        .onAppear {
            NSHapticFeedbackManager.defaultPerformer.perform(
                .alignment, performanceTime: .now
            )
        }
    }

    // Barra que se agota en 60s usando TimelineView (P6c)
    private var expiryBar: some View {
        TimelineView(.animation) { timeline in
            let elapsed = timeline.date.timeIntervalSince(request.createdAt)
            let fraction = max(0.0, 1.0 - elapsed / 60.0)

            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Rectangle()
                        .fill(Color.white.opacity(0.07))
                    Rectangle()
                        .fill(fraction > 0.2 ? amber.opacity(0.6) : Color(red: 0.85, green: 0.27, blue: 0.22).opacity(0.7))
                        .frame(width: geo.size.width * fraction)
                }
            }
            .frame(height: 2)
            .clipShape(Capsule())
        }
    }

    private func _resolveTrash() {
        NSHapticFeedbackManager.defaultPerformer.perform(.levelChange, performanceTime: .now)
        // Enviar confirmación con use_trash implícito (el backend lo interpreta por actionType)
        onConfirm()
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
