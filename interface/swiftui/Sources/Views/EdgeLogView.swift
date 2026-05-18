import SwiftUI

// MARK: - EdgeLogView
// Strip de 3px en el borde derecho. Al hover (<20px) expande a 200px.
// Sin border-radius en lado derecho. BR=10 en lado izquierdo.
// Fondo: rgba(13,13,15, 0.92) sin blur.

struct EdgeLogView: View {
    let steps: [LogStep]
    @State private var hovered = false

    private let stripColor = Color(red: 0.22, green: 0.54, blue: 0.87).opacity(0.4)
    private let bg = Color(red: 0.05, green: 0.05, blue: 0.06).opacity(0.92)
    private let expandedWidth: CGFloat = 200

    var body: some View {
        HStack(spacing: 0) {
            if hovered {
                stepList
                    .transition(.move(edge: .trailing).combined(with: .opacity))
            }

            // Strip visual
            Rectangle()
                .fill(hovered ? Color.clear : stripColor)
                .frame(width: hovered ? 0 : 3)
        }
        .frame(width: hovered ? expandedWidth : 3)
        .frame(maxHeight: min(CGFloat(steps.count) * 36 + 20, 400))
        .background(hovered ? bg : .clear)
        .clipShape(
            .rect(
                topLeadingRadius: 10,
                bottomLeadingRadius: 10,
                bottomTrailingRadius: 0,
                topTrailingRadius: 0
            )
        )
        .onHover { over in
            withAnimation(.spring(response: 0.25, dampingFraction: 0.85)) {
                hovered = over
            }
        }
        .animation(.spring(response: 0.25, dampingFraction: 0.85), value: hovered)
    }

    private var stepList: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(steps) { step in
                    StepRow(step: step)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
        }
        .frame(width: expandedWidth)
    }
}

// MARK: - Fila de paso

private struct StepRow: View {
    let step: LogStep

    var body: some View {
        HStack(spacing: 8) {
            stepIcon
            Text(step.description)
                .font(.system(size: 11))
                .foregroundStyle(.white.opacity(0.85))
                .lineLimit(2)
        }
    }

    @ViewBuilder
    private var stepIcon: some View {
        switch step.status {
        case .completed:
            Image(systemName: "checkmark")
                .font(.system(size: 9, weight: .bold))
                .foregroundStyle(Color.green)
        case .active:
            ProgressView()
                .scaleEffect(0.55)
                .tint(Color(red: 0.22, green: 0.54, blue: 0.87))
        case .failed:
            Image(systemName: "xmark")
                .font(.system(size: 9, weight: .bold))
                .foregroundStyle(Color.red.opacity(0.8))
        case .pending:
            Circle()
                .fill(.white.opacity(0.3))
                .frame(width: 4, height: 4)
        }
    }
}

#Preview {
    EdgeLogView(steps: [
        LogStep(id: "1", description: "Leyendo archivo…", status: .completed),
        LogStep(id: "2", description: "Procesando datos", status: .active),
        LogStep(id: "3", description: "Guardando resultado", status: .pending),
    ])
    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .trailing)
    .background(.black)
}
