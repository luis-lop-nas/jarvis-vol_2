import AppKit
import ApplicationServices

// MARK: - Contexto de la app activa

struct AppContext {
    let bundleId: String
    let windowTitle: String
    let selectedText: String
    let cursorPosition: CGPoint
}

// MARK: - AppContextDetector
// Detecta app activa y ventana usando AXUIElement. Polling cada 0.5s.

@MainActor
final class AppContextDetector {
    static let shared = AppContextDetector()

    private(set) var current: AppContext = AppContext(
        bundleId: "", windowTitle: "", selectedText: "", cursorPosition: .zero
    )
    var onChange: ((AppContext) -> Void)?

    private var timer: Timer?

    private init() {}

    func start() {
        timer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in self?.poll() }
        }
    }

    func stop() {
        timer?.invalidate()
        timer = nil
    }

    // MARK: Private

    private func poll() {
        guard PermissionsManager.shared.accessibilityGranted else { return }

        let app = NSWorkspace.shared.frontmostApplication
        let bundleId = app?.bundleIdentifier ?? ""

        let axApp = AXUIElementCreateApplication(app?.processIdentifier ?? 0)
        let windowTitle = _windowTitle(for: axApp) ?? ""
        let selectedText = _selectedText(for: axApp) ?? ""
        let cursor = _cursorPosition()

        let ctx = AppContext(
            bundleId: bundleId,
            windowTitle: windowTitle,
            selectedText: selectedText,
            cursorPosition: cursor
        )

        if ctx.bundleId != current.bundleId || ctx.windowTitle != current.windowTitle {
            current = ctx
            onChange?(ctx)
        }
    }

    private func _windowTitle(for axApp: AXUIElement) -> String? {
        var window: CFTypeRef?
        guard AXUIElementCopyAttributeValue(axApp, kAXFocusedWindowAttribute as CFString, &window) == .success,
              let win = window else { return nil }
        var title: CFTypeRef?
        guard AXUIElementCopyAttributeValue(win as! AXUIElement, kAXTitleAttribute as CFString, &title) == .success else {
            return nil
        }
        return title as? String
    }

    private func _selectedText(for axApp: AXUIElement) -> String? {
        var focused: CFTypeRef?
        guard AXUIElementCopyAttributeValue(axApp, kAXFocusedUIElementAttribute as CFString, &focused) == .success,
              let el = focused else { return nil }
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(el as! AXUIElement, kAXSelectedTextAttribute as CFString, &value) == .success else {
            return nil
        }
        return value as? String
    }

    private func _cursorPosition() -> CGPoint {
        let event = CGEvent(source: nil)
        return event?.location ?? .zero
    }
}
