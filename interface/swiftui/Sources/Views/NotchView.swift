import SwiftUI

// MARK: - NotchView
// Panel que se expande desde el notch hacia abajo.
// Collapsed: 120×22px — dot + "JARVIS" muted
// Expanded: 240×38px — dot + status + herramienta activa + model badge
// El color del dot refleja la fase del agente (P2).

struct NotchView: View {
    let status: String
    let model: String
    let agentPhase: AgentPhase
    let currentToolName: String?
    let errorMessage: String?
    let progressFraction: Double  // 0.0–1.0 para barra de progreso

    @State private var expanded = false

    private let bg = Color(red: 0.10, green: 0.10, blue: 0.12)
    private let textMuted = Color.white.opacity(0.55)

    // Color semántico por fase (P2)
    var dotColor: Color {
        switch agentPhase {
        case .thinking:  return Color(red: 0.36, green: 0.78, blue: 1.0)   // azul
        case .acting:    return Color(red: 0.95, green: 0.62, blue: 0.15)  // ámbar
        case .completed: return Color(red: 0.11, green: 0.62, blue: 0.46)  // verde
        case .error:     return Color(red: 0.85, green: 0.27, blue: 0.22)  // rojo
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                PulsingDot(color: dotColor)

                if expanded {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("JARVIS")
                            .font(.system(size: 11, weight: .semibold, design: .rounded))
                            .foregroundStyle(.white)
                        // Error: mostrar mensaje; actuando: mostrar herramienta; resto: status
                        if agentPhase == .error, let err = errorMessage {
                            HStack(spacing: 4) {
                                Image(systemName: "exclamationmark.circle")
                                    .font(.system(size: 9))
                                    .foregroundStyle(dotColor)
                                Text(err)
                                    .font(.system(size: 10))
                                    .foregroundStyle(dotColor.opacity(0.9))
                                    .lineLimit(1)
                                    .truncationMode(.tail)
                            }
                        } else if agentPhase == .acting, let tool = currentToolName {
                            Text(tool)
                                .font(.system(size: 10))
                                .foregroundStyle(dotColor.opacity(0.85))
                                .lineLimit(1)
                        } else {
                            Text(status)
                                .font(.system(size: 10))
                                .foregroundStyle(textMuted)
                                .lineLimit(1)
                        }
                    }
                    Spacer()
                    if !model.isEmpty {
                        Text(model)
                            .font(.system(size: 9, weight: .medium))
                            .foregroundStyle(dotColor)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(dotColor.opacity(0.15), in: Capsule())
                    }
                } else {
                    Text("JARVIS")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(textMuted)
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, expanded ? 8 : 4)
            .frame(width: expanded ? 240 : 120, height: expanded ? 36 : 22)

            // Barra de progreso (P2): solo visible durante .acting
            if expanded && agentPhase == .acting {
                GeometryReader { geo in
                    Rectangle()
                        .fill(dotColor.opacity(0.7))
                        .frame(width: geo.size.width * progressFraction)
                        .animation(.linear(duration: 0.5), value: progressFraction)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(height: 2)
            }
        }
        .background(bg)
        .clipShape(
            .rect(
                topLeadingRadius: 0,
                bottomLeadingRadius: 14,
                bottomTrailingRadius: 14,
                topTrailingRadius: 0
            )
        )
        .frame(height: expanded ? 38 : 22)
        .animation(.spring(response: 0.3, dampingFraction: 0.8), value: expanded)
        .animation(.easeInOut(duration: 0.3), value: agentPhase)
        .onTapGesture { expanded.toggle() }
    }
}

// MARK: - Dot pulsante

private struct PulsingDot: View {
    let color: Color
    @State private var scale = 1.0

    var body: some View {
        Circle()
            .fill(color)
            .frame(width: 7, height: 7)
            .scaleEffect(scale)
            .animation(.easeInOut(duration: 0.3), value: color)
            .onAppear {
                withAnimation(
                    .easeInOut(duration: 1.2).repeatForever(autoreverses: true)
                ) { scale = 1.35 }
            }
    }
}

#Preview {
    VStack(spacing: 20) {
        NotchView(status: "Analizando…", model: "kimi-k2", agentPhase: .thinking,
                  currentToolName: nil, errorMessage: nil, progressFraction: 0)
        NotchView(status: "Ejecutando", model: "kimi-k2", agentPhase: .acting,
                  currentToolName: "filesystem.read", errorMessage: nil, progressFraction: 0.6)
        NotchView(status: "Completado", model: "kimi-k2", agentPhase: .completed,
                  currentToolName: nil, errorMessage: nil, progressFraction: 1)
        NotchView(status: "Error", model: "", agentPhase: .error,
                  currentToolName: nil, errorMessage: "Timeout en la API", progressFraction: 0)
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity)
    .background(.black)
}
