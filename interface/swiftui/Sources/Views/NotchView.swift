import SwiftUI

// MARK: - NotchView (Dynamic Island adaptativa)
// Notch persistente que OBSERVA el estado (no se reconstruye) y anima entre 3 modos:
//   • closed   — se funde con el notch físico, casi invisible. No intrusivo.
//   • live     — "live activity" compacta: contenido partido a los lados del notch
//                (izquierda: fase+icono / derecha: progreso o herramienta).
//   • expanded — panel que cuelga con el contexto de la tarea (hover / evento).
// Consume Theme.* y NotchShape. Ver DESIGN_NOTES.md para medidas.

enum NotchMode { case closed, peek, live, expanded }

struct NotchView: View {
    @Environment(JARVISState.self) private var state
    @State private var hovering = false
    @State private var pinnedExpanded = false

    // El notch físico deja un hueco central que el contenido debe respetar.
    private var gap: CGFloat { NotchMetrics.hasNotch ? NotchMetrics.physicalWidth : 0 }
    private var notchHeight: CGFloat { max(NotchMetrics.physicalHeight, 32) }

    private var phase: AgentPhase { state.agentPhase }
    private var disconnected: Bool { state.isDisconnected }
    private var accent: Color { Theme.phaseColor(phase, disconnected: disconnected) }

    /// El agente está "vivo" (trabajando o en un estado que merece señal). En
    /// reposo (uiState == .silent) el notch se cierra aunque la fase por defecto
    /// sea .thinking — evita mostrar "Pensando…" cuando no hay tarea en curso.
    private var isActive: Bool {
        if disconnected || state.pendingConfirmation != nil { return true }
        if case .silent = state.uiState { return false }
        return phase == .thinking || phase == .acting || phase == .error
    }

    private var mode: NotchMode {
        // Clic (pinned) o confirmación pendiente → abierto del todo.
        if pinnedExpanded || state.pendingConfirmation != nil { return .expanded }
        // Hover → "peek": crece un poco para revelar que hay algo detrás.
        if hovering { return .peek }
        if isActive { return .live }
        return .closed
    }

    // Radios de la forma: closed/peek abrazan el notch; live/expanded se abren más.
    private var topR: CGFloat {
        (mode == .live || mode == .expanded) ? NotchMetrics.openTopRadius : NotchMetrics.closedTopRadius
    }
    private var bottomR: CGFloat {
        (mode == .live || mode == .expanded) ? NotchMetrics.openBottomRadius : NotchMetrics.closedBottomRadius
    }

    // Dimensiones del island por modo.
    private var islandWidth: CGFloat {
        switch mode {
        case .closed:   return gap > 0 ? gap + 8 : 180
        case .peek:     return gap + 176
        case .live:     return gap + 260
        case .expanded: return 440
        }
    }
    private var islandHeight: CGFloat {
        switch mode {
        case .closed:   return notchHeight
        case .peek:     return notchHeight + 5
        case .live:     return notchHeight + 6
        case .expanded: return state.pendingConfirmation != nil ? 168 : 132
        }
    }

    var body: some View {
        VStack {
            island
                .frame(width: islandWidth, height: islandHeight)
                .background(
                    NotchShape(topRadius: topR, bottomRadius: bottomR)
                        .fill(Theme.Palette.notch)
                        .shadow(color: .black.opacity(mode == .closed ? 0 : 0.35), radius: 12, y: 6)
                )
                .overlay(
                    // Halo sutil del acento cuando no está en reposo (toque HUD).
                    NotchShape(topRadius: topR, bottomRadius: bottomR)
                        .stroke(accent.opacity(mode == .closed ? 0 : 0.18), lineWidth: 1)
                )
                .clipShape(NotchShape(topRadius: topR, bottomRadius: bottomR))
                .contentShape(Rectangle())
                .onHover { h in
                    withAnimation(h ? Theme.Motion.expand : Theme.Motion.collapse) { hovering = h }
                }
                .onTapGesture { tapped() }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .animation(mode == .closed ? Theme.Motion.collapse : Theme.Motion.expand, value: mode)
        .animation(Theme.Motion.phase, value: accent)
    }

    // MARK: Contenido por modo

    @ViewBuilder private var island: some View {
        switch mode {
        case .closed:   closedContent
        case .peek:     peekContent
        case .live:     liveContent
        case .expanded: expandedContent
        }
    }

    // — Peek: al pasar el ratón, crece un poco y revela la identidad "JARVIS".
    private var peekContent: some View {
        HStack(spacing: 0) {
            HStack(spacing: Theme.Space.sm) {
                PhaseIndicator(phase: phase, disconnected: disconnected, color: accent)
                Text("JARVIS")
                    .font(Theme.Font.caption(.semibold))
                    .foregroundStyle(Theme.Palette.textSecondary)
                    .lineLimit(1)
                    .fixedSize()
            }
            .padding(.leading, Theme.Space.lg)
            .frame(maxWidth: .infinity, alignment: .leading)

            Spacer().frame(width: gap)

            Image(systemName: "chevron.down")
                .font(Theme.Font.micro())
                .foregroundStyle(Theme.Palette.textTertiary)
                .padding(.trailing, Theme.Space.lg)
                .frame(maxWidth: .infinity, alignment: .trailing)
        }
        .padding(.top, 1)
        .transition(.opacity)
    }

    // — Closed: prácticamente invisible; solo un punto de acento si está conectado.
    private var closedContent: some View {
        HStack {
            Spacer()
            if state.isConnected && !disconnected {
                Circle().fill(Theme.Palette.accent.opacity(0.0)).frame(width: 4, height: 4)
            }
            Spacer()
        }
    }

    // — Live: contenido partido a los lados del notch físico.
    private var liveContent: some View {
        HStack(spacing: 0) {
            HStack(spacing: Theme.Space.sm) {
                PhaseIndicator(phase: phase, disconnected: disconnected, color: accent)
                Text(shortStatus)
                    .font(Theme.Font.caption())
                    .foregroundStyle(Theme.Palette.textSecondary)
                    .lineLimit(1)
            }
            .padding(.leading, Theme.Space.lg)
            .frame(maxWidth: .infinity, alignment: .leading)

            Spacer().frame(width: gap)

            HStack(spacing: Theme.Space.sm) {
                if phase == .acting {
                    ProgressRing(progress: state.currentProgress, color: accent)
                        .frame(width: 15, height: 15)
                } else if let model = modelShort {
                    Text(model)
                        .font(Theme.Font.micro())
                        .foregroundStyle(accent)
                }
            }
            .padding(.trailing, Theme.Space.lg)
            .frame(maxWidth: .infinity, alignment: .trailing)
        }
        .padding(.top, 1)
        .transition(.opacity)
    }

    // — Expanded: panel con contexto de la tarea / confirmación.
    private var expandedContent: some View {
        VStack(alignment: .leading, spacing: Theme.Space.md) {
            // Cabecera: identidad + fase + modelo.
            HStack(spacing: Theme.Space.sm) {
                PhaseIndicator(phase: phase, disconnected: disconnected, color: accent)
                Text("JARVIS")
                    .font(Theme.Font.label())
                    .foregroundStyle(Theme.Palette.textPrimary)
                Spacer()
                if let model = modelShort {
                    Text(model)
                        .font(Theme.Font.micro())
                        .foregroundStyle(accent)
                        .padding(.horizontal, Theme.Space.sm)
                        .padding(.vertical, 2)
                        .background(accent.opacity(0.15), in: Capsule())
                }
            }

            if let conf = state.pendingConfirmation {
                confirmationBody(conf)
            } else {
                taskBody
            }
        }
        .padding(.horizontal, Theme.Space.xl)
        .padding(.top, notchHeight * 0.28)
        .padding(.bottom, Theme.Space.lg)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .transition(.opacity.combined(with: .move(edge: .top)))
    }

    // Cuerpo de tarea en curso (o invitación a hablar si está en reposo).
    private var taskBody: some View {
        VStack(alignment: .leading, spacing: Theme.Space.sm) {
            Text(isActive ? state.notchStatusText : "¿En qué puedo ayudarte?")
                .font(Theme.Font.caption())
                .foregroundStyle(Theme.Palette.textSecondary)
                .lineLimit(2)
            if phase == .acting {
                ProgressBar(progress: state.currentProgress, color: accent)
                    .frame(height: 3)
                if let tool = state.currentToolName {
                    Text(tool)
                        .font(Theme.Font.mono)
                        .foregroundStyle(Theme.Palette.textTertiary)
                        .lineLimit(1)
                }
            }
        }
    }

    private func confirmationBody(_ conf: ConfirmationRequest) -> some View {
        VStack(alignment: .leading, spacing: Theme.Space.md) {
            HStack(spacing: Theme.Space.xs) {
                Image(systemName: conf.isDestructive ? "exclamationmark.triangle.fill" : "questionmark.circle.fill")
                    .font(Theme.Font.caption())
                    .foregroundStyle(conf.isDestructive ? Theme.Semantic.error : accent)
                Text(conf.isDestructive ? "Confirmar acción sensible" : "Confirmación")
                    .font(Theme.Font.caption(.semibold))
                    .foregroundStyle(Theme.Palette.textPrimary)
            }
            Text(conf.actionDescription)
                .font(Theme.Font.caption())
                .foregroundStyle(Theme.Palette.textSecondary)
                .lineLimit(2)
            if let cmd = conf.command {
                Text(cmd)
                    .font(Theme.Font.mono)
                    .foregroundStyle(Theme.Palette.textTertiary)
                    .lineLimit(1)
            }
            HStack(spacing: Theme.Space.md) {
                Spacer()
                Text("Abre el panel para confirmar")
                    .font(Theme.Font.micro(.medium))
                    .foregroundStyle(Theme.Palette.textTertiary)
            }
        }
    }

    // MARK: Helpers

    private func tapped() {
        // Clic = solo expandir/colapsar el notch (no abre ningún panel).
        withAnimation(pinnedExpanded ? Theme.Motion.collapse : Theme.Motion.expand) {
            pinnedExpanded.toggle()
        }
    }

    private var shortStatus: String {
        if disconnected { return "Sin conexión" }
        switch phase {
        case .thinking:  return "Pensando…"
        case .acting:    return state.currentToolName ?? "Ejecutando"
        case .completed: return "Listo"
        case .error:     return state.errorMessage ?? "Error"
        }
    }

    private var modelShort: String? {
        guard let m = state.lastModelUsed, !m.isEmpty else { return nil }
        // "gemini-2.5-flash" → "gemini", "kimi-k2.6" → "kimi"
        return m.split(separator: "-").first.map(String.init) ?? m
    }
}

// MARK: - Componentes reutilizables

/// Punto/indicador de fase con pulso suave.
struct PhaseIndicator: View {
    let phase: AgentPhase
    var disconnected: Bool = false
    let color: Color
    @State private var pulse = false

    var body: some View {
        ZStack {
            Circle()
                .fill(color.opacity(0.25))
                .frame(width: 14, height: 14)
                .scaleEffect(pulse ? 1.25 : 0.85)
                .opacity(pulse ? 0 : 0.8)
            Circle()
                .fill(color)
                .frame(width: 7, height: 7)
        }
        .onAppear {
            guard phase == .thinking || phase == .acting || disconnected else { return }
            withAnimation(.easeOut(duration: 1.1).repeatForever(autoreverses: false)) { pulse = true }
        }
        .animation(Theme.Motion.phase, value: color)
    }
}

/// Anillo de progreso compacto.
struct ProgressRing: View {
    let progress: Double
    let color: Color
    var body: some View {
        ZStack {
            Circle().stroke(color.opacity(0.2), lineWidth: 2)
            Circle()
                .trim(from: 0, to: max(0.02, min(1, progress)))
                .stroke(color, style: StrokeStyle(lineWidth: 2, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .animation(Theme.Motion.content, value: progress)
        }
    }
}

/// Barra de progreso fina.
struct ProgressBar: View {
    let progress: Double
    let color: Color
    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(color.opacity(0.18))
                Capsule().fill(color)
                    .frame(width: geo.size.width * max(0.02, min(1, progress)))
                    .animation(Theme.Motion.content, value: progress)
            }
        }
    }
}
