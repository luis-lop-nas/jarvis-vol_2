import SwiftUI

// MARK: - EdgeLogView
// Strip de 3px en el borde derecho. Al hover (<20px) expande a 200px.
// Click ancla el panel abierto (isPinned). Timestamps relativos en cada paso.

struct EdgeLogView: View {
    let steps: [LogStep]
    @State private var isHovered = false
    @State private var isPinned = false

    private let stripColor = Color(red: 0.22, green: 0.54, blue: 0.87).opacity(0.4)
    private let bg = Color(red: 0.05, green: 0.05, blue: 0.06).opacity(0.92)
    private let expandedWidth: CGFloat = 200

    private var isExpanded: Bool { isHovered || isPinned }

    var body: some View {
        HStack(spacing: 0) {
            if isExpanded {
                stepList
                    .transition(.move(edge: .trailing).combined(with: .opacity))
            }

            // Strip visual — desaparece cuando está expandido
            Rectangle()
                .fill(isExpanded ? Color.clear : stripColor)
                .frame(width: isExpanded ? 0 : 3)
        }
        .frame(width: isExpanded ? expandedWidth : 3)
        .frame(maxHeight: min(CGFloat(steps.count) * 36 + 20, 400))
        .background(isExpanded ? bg : .clear)
        .clipShape(
            .rect(
                topLeadingRadius: 10,
                bottomLeadingRadius: 10,
                bottomTrailingRadius: 0,
                topTrailingRadius: 0
            )
        )
        .overlay(alignment: .topTrailing) {
            // Indicador de anclado (P3c)
            if isPinned {
                Image(systemName: "pin.fill")
                    .font(.system(size: 8))
                    .foregroundStyle(.white.opacity(0.4))
                    .padding(6)
            }
        }
        .onHover { over in
            withAnimation(.interpolatingSpring(stiffness: 300, damping: 28)) {
                isHovered = over
                if !over && isPinned { /* mantener abierto */ }
            }
        }
        .onTapGesture {
            withAnimation(.interpolatingSpring(stiffness: 300, damping: 28)) {
                isPinned.toggle()
            }
        }
        .animation(.interpolatingSpring(stiffness: 300, damping: 28), value: isExpanded)
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

// MARK: - Fila de paso (con elapsed time)

private struct StepRow: View {
    let step: LogStep

    var body: some View {
        HStack(spacing: 8) {
            stepIcon

            Text(step.description)
                .font(.system(size: 10))
                .foregroundStyle(.white.opacity(0.8))
                .lineLimit(2)

            Spacer(minLength: 4)

            Text(step.elapsed)
                .font(.system(size: 9))
                .foregroundStyle(.white.opacity(0.35))
        }
    }

    @ViewBuilder
    private var stepIcon: some View {
        switch step.status {
        case .completed:
            Image(systemName: "checkmark")
                .font(.system(size: 9, weight: .bold))
                .foregroundStyle(Color(red: 0.11, green: 0.62, blue: 0.46))
                .frame(width: 12)
        case .active:
            ProgressView()
                .scaleEffect(0.55)
                .tint(Color(red: 0.36, green: 0.78, blue: 1.0))
                .frame(width: 12)
        case .failed:
            Image(systemName: "xmark")
                .font(.system(size: 9, weight: .bold))
                .foregroundStyle(Color(red: 0.85, green: 0.27, blue: 0.22).opacity(0.8))
                .frame(width: 12)
        case .pending:
            Circle()
                .fill(.white.opacity(0.3))
                .frame(width: 4, height: 4)
                .frame(width: 12)
        }
    }
}

#Preview {
    EdgeLogView(steps: [
        LogStep(id: "1", description: "Leyendo archivo main.py", status: .completed),
        LogStep(id: "2", description: "Procesando dependencias del módulo", status: .active),
        LogStep(id: "3", description: "Guardando resultado en disco", status: .pending),
    ])
    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .trailing)
    .background(.black)
}
