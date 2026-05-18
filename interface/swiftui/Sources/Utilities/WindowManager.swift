import AppKit
import SwiftUI

// MARK: - WindowManager
// Gestiona ventanas flotantes sin titlebar en niveles de ventana correctos.

final class WindowManager {
    static let shared = WindowManager()

    private var notchWindow: NSWindow?
    private var edgeWindow: NSWindow?
    private var modalWindow: NSWindow?
    private var inlineWindow: NSWindow?

    private init() {}

    // MARK: - Notch window (statusBar level, top-center)

    func showNotch<V: View>(content: V) {
        let screen = NSScreen.main ?? NSScreen.screens[0]
        let screenFrame = screen.frame
        let width: CGFloat = 240
        let height: CGFloat = 38
        let x = screenFrame.midX - width / 2
        let y = screenFrame.maxY - height

        notchWindow = _makeWindow(
            frame: NSRect(x: x, y: y, width: width, height: height),
            level: .statusBar,
            content: content
        )
        notchWindow?.orderFront(nil)
    }

    func hideNotch() {
        notchWindow?.orderOut(nil)
        notchWindow = nil
    }

    // MARK: - Edge window (right edge, statusBar level)

    func showEdge<V: View>(content: V) {
        let screen = NSScreen.main ?? NSScreen.screens[0]
        let screenFrame = screen.visibleFrame
        let width: CGFloat = 3  // starts collapsed; SwiftUI manages expansion
        let height = screenFrame.height
        let x = screenFrame.maxX - width
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

    // MARK: - Modal window (center-screen, modal level)

    func showModal<V: View>(content: V) {
        let screen = NSScreen.main ?? NSScreen.screens[0]
        let screenFrame = screen.frame
        let width: CGFloat = 480
        let height: CGFloat = 600
        let x = screenFrame.midX - width / 2
        let y = screenFrame.maxY - 130 - height

        modalWindow = _makeWindow(
            frame: NSRect(x: x, y: y, width: width, height: height),
            level: .modalPanel,
            content: content
        )
        modalWindow?.orderFront(nil)
    }

    func hideModal() {
        modalWindow?.orderOut(nil)
        modalWindow = nil
    }

    // MARK: - Inline window (near cursor/active window)

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

    // MARK: Private

    private func _makeWindow<V: View>(
        frame: NSRect,
        level: NSWindow.Level,
        content: V
    ) -> NSWindow {
        let window = NSWindow(
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
