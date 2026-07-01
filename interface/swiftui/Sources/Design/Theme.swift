import SwiftUI
import AppKit

// MARK: - Sistema de diseño JARVIS
// Fuente única de verdad para color, tipografía, espaciado, radios, sombras,
// animaciones y métricas del notch. Todas las vistas consumen estos tokens en
// lugar de valores hardcodeados → coherencia visual ("look JARVIS").

enum Theme {

    // MARK: Color

    enum Palette {
        /// Fondo del notch: negro casi puro para fundirse con el notch físico.
        static let notch = Color.black
        static let surface = Color(red: 0.09, green: 0.09, blue: 0.11)
        static let surfaceElevated = Color(red: 0.13, green: 0.13, blue: 0.16)
        static let stroke = Color.white.opacity(0.08)

        static let textPrimary = Color.white
        static let textSecondary = Color.white.opacity(0.62)
        static let textTertiary = Color.white.opacity(0.38)

        // Acento base de JARVIS (cian frío, toque HUD sutil).
        static let accent = Color(red: 0.36, green: 0.78, blue: 1.0)
    }

    /// Colores semánticos por fase del agente.
    static func phaseColor(_ phase: AgentPhase, disconnected: Bool = false) -> Color {
        if disconnected { return Semantic.error }
        switch phase {
        case .thinking:  return Semantic.thinking
        case .acting:    return Semantic.acting
        case .completed: return Semantic.completed
        case .error:     return Semantic.error
        }
    }

    enum Semantic {
        static let thinking = Color(red: 0.36, green: 0.78, blue: 1.0)   // cian
        static let acting = Color(red: 0.98, green: 0.66, blue: 0.20)    // ámbar
        static let completed = Color(red: 0.24, green: 0.80, blue: 0.52) // verde
        static let error = Color(red: 0.98, green: 0.36, blue: 0.33)     // rojo
    }

    // MARK: Tipografía (SF Pro Rounded para un carácter cálido y legible)

    enum Font {
        static func label(_ weight: SwiftUI.Font.Weight = .semibold) -> SwiftUI.Font {
            .system(size: 12, weight: weight, design: .rounded)
        }
        static func caption(_ weight: SwiftUI.Font.Weight = .medium) -> SwiftUI.Font {
            .system(size: 10.5, weight: weight, design: .rounded)
        }
        static func micro(_ weight: SwiftUI.Font.Weight = .semibold) -> SwiftUI.Font {
            .system(size: 9, weight: weight, design: .rounded)
        }
        static func title(_ weight: SwiftUI.Font.Weight = .bold) -> SwiftUI.Font {
            .system(size: 15, weight: weight, design: .rounded)
        }
        static let mono = SwiftUI.Font.system(size: 11, weight: .medium, design: .monospaced)
    }

    // MARK: Espaciado (escala 4pt)

    enum Space {
        static let xs: CGFloat = 4
        static let sm: CGFloat = 6
        static let md: CGFloat = 8
        static let lg: CGFloat = 12
        static let xl: CGFloat = 16
    }

    // MARK: Animaciones (coherentes en toda la UI — ADR-D2)

    enum Motion {
        /// Apertura/expansión del notch: rebote corto (DNK + boring.notch).
        static let expand = Animation.spring(response: 0.42, dampingFraction: 0.72)
        /// Cierre: sin rebote.
        static let collapse = Animation.spring(response: 0.38, dampingFraction: 0.9)
        /// Cambio de contenido interno: rápido y limpio.
        static let content = Animation.spring(response: 0.3, dampingFraction: 0.82)
        /// Cambios de color/fase.
        static let phase = Animation.easeInOut(duration: 0.35)
    }
}

// MARK: - Métricas del notch físico

enum NotchMetrics {
    /// Ancho real del notch físico de la pantalla principal (fallback 185pt en
    /// M-series si la API no lo expone). Basado en boring.notch getClosedNotchSize.
    static var physicalWidth: CGFloat {
        guard let screen = NSScreen.main else { return 185 }
        // safeAreaInsets.top > 0 indica que hay notch. El ancho se deriva de las
        // áreas auxiliares izquierda/derecha de la barra superior (macOS 12+).
        let left = screen.auxiliaryTopLeftArea?.width ?? 0
        let right = screen.auxiliaryTopRightArea?.width ?? 0
        if left > 0, right > 0 {
            return screen.frame.width - left - right
        }
        return 185
    }

    /// Alto del notch físico (safe-area top) — ~32-37pt en M-series.
    static var physicalHeight: CGFloat {
        guard let screen = NSScreen.main else { return 32 }
        let inset = screen.safeAreaInsets.top
        return inset > 0 ? inset : 32
    }

    /// `true` si la pantalla principal tiene notch físico.
    static var hasNotch: Bool {
        (NSScreen.main?.safeAreaInsets.top ?? 0) > 0
    }

    // Radios de la forma del notch (cuelga del borde: top pequeño, bottom grande).
    static let closedTopRadius: CGFloat = 6
    static let closedBottomRadius: CGFloat = 13
    static let openTopRadius: CGFloat = 10
    static let openBottomRadius: CGFloat = 22

    // Tamaño de la ventana del notch (contenedor máximo; la vista anima dentro).
    static let windowWidth: CGFloat = 620
    static let windowHeight: CGFloat = 220
}
