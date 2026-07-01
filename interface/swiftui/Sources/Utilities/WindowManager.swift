import AppKit
import SwiftUI

// MARK: - Ventana borderless que puede recibir foco de teclado
// Una NSWindow .borderless devuelve canBecomeKey=false por defecto, así que su
// TextField no acepta escritura. El modal y el onboarding la necesitan key.
final class KeyableWindow: NSWindow {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
}

// MARK: - Posición preferida para InlineView por app (P5a)

enum InlinePosition {
    case topRight, topLeft, bottomRight, bottomLeft, bottomCenter
}

// MARK: - WindowManager
// Gestiona ventanas flotantes sin titlebar en niveles de ventana correctos.

final class WindowManager {
    static let shared = WindowManager()

    private var notchWindow: NSWindow?
    private var edgeWindow: NSWindow?
    private var modalWindow: NSWindow?
    private var inlineWindow: NSWindow?
    private var onboardingWindow: NSWindow?

    // Posición preferida de InlineView por bundleIdentifier de la app activa (P5a).
    // Extensible sin recompilar añadiendo entradas a este dict.
    private let appPositionPreferences: [String: InlinePosition] = [
        "com.microsoft.VSCode":                .bottomCenter,  // lejos de CodeLens
        "com.apple.dt.Xcode":                  .bottomCenter,
        "com.apple.finder":                    .topRight,
        "com.apple.Safari":                    .topRight,
        "com.google.Chrome":                   .topRight,
        "org.mozilla.firefox":                 .topRight,
        "com.apple.mail":                      .bottomRight,
        "com.tinyspeck.slackmacgap":           .bottomRight,
        "com.apple.Terminal":                  .bottomLeft,
        "com.googlecode.iterm2":               .bottomLeft,
        "dev.warp.Warp-Stable":                .bottomLeft,
    ]

    private init() {}

    // MARK: - Notch window (statusBar level, top-center)

    // El notch es PERSISTENTE: se crea una sola vez con una vista que observa el
    // estado (@Observable). No se recrea en cada actualización — así SwiftUI anima
    // los cambios de modo (closed↔live↔expanded) dentro del mismo árbol de vistas
    // en lugar de reiniciar la animación al reemplazar el NSHostingView.
    func showNotch<V: View>(content: V) {
        if notchWindow != nil {
            notchWindow?.orderFront(nil)
            return
        }
        let screen = NSScreen.main ?? NSScreen.screens[0]
        let screenFrame = screen.frame
        // Contenedor amplio anclado al borde superior; el island anima su tamaño
        // dentro. El área transparente no captura clics (hit-test de SwiftUI).
        let width = NotchMetrics.windowWidth
        let height = NotchMetrics.windowHeight
        let x = screenFrame.midX - width / 2
        let y = screenFrame.maxY - height
        let frame = NSRect(x: x, y: y, width: width, height: height)

        notchWindow = _makeWindow(frame: frame, level: .statusBar, content: content)
        notchWindow?.orderFront(nil)
    }

    func hideNotch() {
        notchWindow?.orderOut(nil)
        notchWindow = nil
    }

    // MARK: - Edge window (right edge, floating level)

    func showEdge<V: View>(content: V) {
        let screen = NSScreen.main ?? NSScreen.screens[0]
        let screenFrame = screen.visibleFrame
        let height = screenFrame.height
        let x = screenFrame.maxX - 200
        let y = screenFrame.minY

        edgeWindow = _makeWindow(
            frame: NSRect(x: x, y: y, width: 200, height: height),
            level: .floating,
            content: content
        )
        edgeWindow?.isOpaque = false
        edgeWindow?.backgroundColor = .clear
        edgeWindow?.orderFront(nil)
    }

    func hideEdge() {
        edgeWindow?.orderOut(nil)
        edgeWindow = nil
    }

    // MARK: - Modal window (center-screen, modalPanel level)

    func showModal<V: View>(content: V) {
        let screen = NSScreen.main ?? NSScreen.screens[0]
        let screenFrame = screen.frame
        let width: CGFloat = 480
        let height: CGFloat = 620
        let x = screenFrame.midX - width / 2
        let y = screenFrame.maxY - 130 - height

        modalWindow = _makeWindow(
            frame: NSRect(x: x, y: y, width: width, height: height),
            level: .modalPanel,
            content: content,
            canBecomeKey: true
        )
        NSApp.activate(ignoringOtherApps: true)
        modalWindow?.makeKeyAndOrderFront(nil)
    }

    func hideModal() {
        modalWindow?.orderOut(nil)
        modalWindow = nil
    }

    // MARK: - Inline window (posición adaptativa por app)

    func showInline<V: View>(content: V) {
        let bundleId = NSWorkspace.shared.frontmostApplication?.bundleIdentifier ?? ""
        let position = appPositionPreferences[bundleId] ?? .bottomRight
        let frame = _inlineFrame(for: position)

        inlineWindow = _makeWindow(frame: frame, level: .floating, content: content)
        inlineWindow?.isOpaque = false
        inlineWindow?.backgroundColor = .clear
        inlineWindow?.orderFront(nil)
    }

    // Sobrecarga con punto explícito (retrocompatibilidad)
    func showInline<V: View>(at point: CGPoint, content: V) {
        inlineWindow = _makeWindow(
            frame: NSRect(x: point.x, y: point.y, width: 280, height: 120),
            level: .floating,
            content: content
        )
        inlineWindow?.orderFront(nil)
    }

    func hideInline() {
        inlineWindow?.orderOut(nil)
        inlineWindow = nil
    }

    // MARK: - Onboarding window (P8)

    func showOnboarding<V: View>(content: V) {
        let screen = NSScreen.main ?? NSScreen.screens[0]
        let screenFrame = screen.frame
        let width: CGFloat = 400
        let height: CGFloat = 320
        let x = screenFrame.midX - width / 2
        let y = screenFrame.midY - height / 2

        onboardingWindow = _makeWindow(
            frame: NSRect(x: x, y: y, width: width, height: height),
            level: .modalPanel,
            content: content,
            canBecomeKey: true
        )
        NSApp.activate(ignoringOtherApps: true)
        onboardingWindow?.makeKeyAndOrderFront(nil)
    }

    func closeOnboarding() {
        onboardingWindow?.orderOut(nil)
        onboardingWindow = nil
    }

    // MARK: Private

    private func _inlineFrame(for position: InlinePosition) -> NSRect {
        let screen = NSScreen.main ?? NSScreen.screens[0]
        let sf = screen.visibleFrame
        let w: CGFloat = 280
        let h: CGFloat = 80
        let margin: CGFloat = 16

        switch position {
        case .topRight:
            return NSRect(x: sf.maxX - w - margin, y: sf.maxY - h - margin, width: w, height: h)
        case .topLeft:
            return NSRect(x: sf.minX + margin, y: sf.maxY - h - margin, width: w, height: h)
        case .bottomRight:
            return NSRect(x: sf.maxX - w - margin, y: sf.minY + margin, width: w, height: h)
        case .bottomLeft:
            return NSRect(x: sf.minX + margin, y: sf.minY + margin, width: w, height: h)
        case .bottomCenter:
            return NSRect(x: sf.midX - w / 2, y: sf.minY + margin, width: w, height: h)
        }
    }

    private func _makeWindow<V: View>(
        frame: NSRect,
        level: NSWindow.Level,
        content: V,
        canBecomeKey: Bool = false
    ) -> NSWindow {
        let window: NSWindow = canBecomeKey
            ? KeyableWindow(
                contentRect: frame,
                styleMask: [.borderless],
                backing: .buffered,
                defer: false
            )
            : NSWindow(
                contentRect: frame,
                styleMask: [.borderless],
                backing: .buffered,
                defer: false
            )
        window.level = level
        window.isOpaque = false
        window.backgroundColor = .clear
        window.ignoresMouseEvents = false
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        window.contentView = NSHostingView(rootView: content)
        return window
    }
}
