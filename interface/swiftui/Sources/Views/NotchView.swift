import SwiftUI

// MARK: - NotchView
// Panel que se expande desde el notch hacia abajo.
// Collapsed: 120×22px — dot + "JARVIS" muted
// Expanded: 240×38px — dot + status + model badge
// Pegado al notch superior del M3.

struct NotchView: View {
    let status: String
    let model: String
    @State private var expanded = false

    // Colores de diseño
    private let bg = Color(red: 0.10, green: 0.10, blue: 0.12)
    private let dotColor = Color(red: 0.22, green: 0.54, blue: 0.87)
    private let textMuted = Color.white.opacity(0.55)

    var body: some View {
        HStack(spacing: 8) {
            PulsingDot(color: dotColor)

            if expanded {
                VStack(alignment: .leading, spacing: 2) {
                    Text("JARVIS")
                        .font(.system(size: 11, weight: .semibold, design: .rounded))
                        .foregroundStyle(.white)
                    Text(status)
                        .font(.system(size: 10))
                        .foregroundStyle(textMuted)
                        .lineLimit(1)
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
        .frame(width: expanded ? 240 : 120, height: expanded ? 38 : 22)
        .background(bg)
        .clipShape(
            .rect(
                topLeadingRadius: 0,
                bottomLeadingRadius: 14,
                bottomTrailingRadius: 14,
                topTrailingRadius: 0
            )
        )
        .animation(.spring(response: 0.3, dampingFraction: 0.8), value: expanded)
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
            .onAppear {
                withAnimation(
                    .easeInOut(duration: 1.2).repeatForever(autoreverses: true)
                ) { scale = 1.35 }
            }
    }
}

#Preview {
    NotchView(status: "Analizando tarea…", model: "gemma4:4b")
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(.black)
}
