import AppKit
import Carbon
import UserNotifications

// MARK: - HotkeyManager
// Hotkey principal: ⌘⌥Space (evita conflicto con Spotlight de ⌘Space).
// Fallback si CGEventTap falla: ⌘⇧Space via NSEvent global monitor.

final class HotkeyManager {
    static let shared = HotkeyManager()

    var onFocusModal: (() -> Void)?

    private var eventTap: CFMachPort?
    private var runLoopSource: CFRunLoopSource?

    private let kTargetKeyCode: CGKeyCode = 49  // kVK_Space

    private init() {}

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
            // CGEventTap requiere Accesibilidad. Si falla, usar monitor Cocoa.
            _notifyTapFailed()
            _registerFallbackHotkey()
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

    // MARK: Private

    private func _handle(
        proxy: CGEventTapProxy,
        type: CGEventType,
        event: CGEvent
    ) -> Unmanaged<CGEvent>? {
        guard type == .keyDown else { return Unmanaged.passUnretained(event) }

        let keyCode = event.getIntegerValueField(.keyboardEventKeycode)
        let flags = event.flags

        // Primario: ⌘⌥Space
        let isCmdAltSpace = keyCode == kTargetKeyCode
            && flags.contains(.maskCommand)
            && flags.contains(.maskAlternate)
            && !flags.contains(.maskShift)

        if isCmdAltSpace {
            DispatchQueue.main.async { [weak self] in self?.onFocusModal?() }
            return nil  // consume el evento
        }
        return Unmanaged.passUnretained(event)
    }

    // Fallback: ⌘⇧Space (NSEvent no consume el evento)
    private func _registerFallbackHotkey() {
        NSEvent.addGlobalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self else { return }
            let isCmdShiftSpace = event.keyCode == self.kTargetKeyCode
                && event.modifierFlags.contains(.command)
                && event.modifierFlags.contains(.shift)
                && !event.modifierFlags.contains(.option)
            if isCmdShiftSpace { self.onFocusModal?() }
        }
    }

    private func _notifyTapFailed() {
        // Solo notificar una vez
        let key = "jarvis.hotkey.tapFailedNotified"
        guard !UserDefaults.standard.bool(forKey: key) else { return }
        UserDefaults.standard.set(true, forKey: key)

        let content = UNMutableNotificationContent()
        content.title = "JARVIS"
        content.body = "⌘Space está ocupado por Spotlight. Usando ⌘⇧Space como alternativa. " +
                       "Puedes cambiar Spotlight en Ajustes del Sistema → Siri y Spotlight."

        let request = UNNotificationRequest(
            identifier: "jarvis.hotkey.conflict",
            content: content,
            trigger: UNTimeIntervalNotificationTrigger(timeInterval: 1, repeats: false)
        )
        UNUserNotificationCenter.current().add(request, withCompletionHandler: nil)
    }
}
