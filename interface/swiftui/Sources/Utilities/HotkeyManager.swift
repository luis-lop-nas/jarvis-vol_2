import AppKit
import Carbon

// MARK: - HotkeyManager
// Global hotkey ⌘Space (con fallback a ⌘⌥Space) via CGEventTap.

final class HotkeyManager {
    static let shared = HotkeyManager()

    var onFocusModal: (() -> Void)?

    private var eventTap: CFMachPort?
    private var runLoopSource: CFRunLoopSource?

    // UserDefaults key para persistir preferencia de hotkey
    private let preferenceKey = "jarvis.hotkey.useAltSpace"
    private(set) var useAltSpace: Bool

    private init() {
        useAltSpace = UserDefaults.standard.bool(forKey: "jarvis.hotkey.useAltSpace")
    }

    func start() {
        let mask: CGEventMask = 1 << CGEventType.keyDown.rawValue

        let selfPtr = Unmanaged.passUnretained(self).toOpaque()
        eventTap = CGEvent.tapCreate(
            tap: .cgSessionEventTap,
            place: .headInsertEventTap,
            options: .defaultTap,
            eventsOfInterest: mask,
            callback: { proxy, type, event, refcon -> Unmanaged<CGEvent>? in
                guard let refcon else { return Unmanaged.passUnretained(event) }
                let manager = Unmanaged<HotkeyManager>.fromOpaque(refcon).takeUnretainedValue()
                return manager._handle(proxy: proxy, type: type, event: event)
            },
            userInfo: selfPtr
        )

        guard let tap = eventTap else {
            // Si no se puede crear el tap, intentar con el hotkey de Cocoa
            _registerCocoaHotkey()
            return
        }

        runLoopSource = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0)
        if let source = runLoopSource {
            CFRunLoopAddSource(CFRunLoopGetCurrent(), source, .commonModes)
            CGEvent.tapEnable(tap: tap, enable: true)
        }
    }

    func stop() {
        if let tap = eventTap {
            CGEvent.tapEnable(tap: tap, enable: false)
        }
        if let source = runLoopSource {
            CFRunLoopRemoveSource(CFRunLoopGetCurrent(), source, .commonModes)
        }
    }

    func switchToAltSpace() {
        useAltSpace = true
        UserDefaults.standard.set(true, forKey: preferenceKey)
    }

    // MARK: Private

    private func _handle(
        proxy: CGEventTapProxy,
        type: CGEventType,
        event: CGEvent
    ) -> Unmanaged<CGEvent>? {
        guard type == .keyDown else { return Unmanaged.passUnretained(event) }

        let keyCode = event.getIntegerValueField(.keyboardEventKeycode)
        let flags = event.flags

        let isSpace = keyCode == 49  // kVK_Space
        let isCmd = flags.contains(.maskCommand)
        let isAlt = flags.contains(.maskAlternate)

        let triggered = useAltSpace
            ? isSpace && isCmd && isAlt
            : isSpace && isCmd && !isAlt

        if triggered {
            DispatchQueue.main.async { [weak self] in self?.onFocusModal?() }
            return nil  // consume el evento
        }
        return Unmanaged.passUnretained(event)
    }

    private func _registerCocoaHotkey() {
        // Fallback: NSEvent global monitor (no consume el evento)
        NSEvent.addGlobalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self else { return }
            let isSpace = event.keyCode == 49
            let isCmd = event.modifierFlags.contains(.command)
            let isAlt = event.modifierFlags.contains(.option)
            let triggered = self.useAltSpace
                ? isSpace && isCmd && isAlt
                : isSpace && isCmd && !isAlt
            if triggered { self.onFocusModal?() }
        }
    }
}
