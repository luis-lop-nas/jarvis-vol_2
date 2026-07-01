import AppKit
import Carbon.HIToolbox

// API privada de CoreGraphics para activar/desactivar los "symbolic hotkeys" del
// sistema en runtime. Se usa para liberar ⌘⌥Space (ver más abajo). No añade
// dependencias: es una función del propio sistema declarada con @_silgen_name.
@_silgen_name("CGSSetSymbolicHotKeyEnabled")
private func CGSSetSymbolicHotKeyEnabled(_ hotKey: CInt, _ enabled: Bool) -> CInt

// MARK: - HotkeyManager
// Hotkey global ⌘⌥Space vía Carbon RegisterEventHotKey.
//
// Motivo del cambio (P1): había DOS causas por las que "el modal no aparece":
//   1. CGEventTap y NSEvent.addGlobalMonitorForEvents(.keyDown) requieren permiso
//      de Accesibilidad. El binario se firma ad-hoc y su identidad cambia en cada
//      rebuild, así que macOS invalida la Accesibilidad concedida. RegisterEventHotKey
//      NO necesita Accesibilidad.
//   2. ⌘⌥Space está reservado por macOS para "búsqueda en Finder" (symbolic hotkey
//      65). El sistema lo consume antes que la app, así que ni siquiera llegaba a
//      nuestro handler. Lo desactivamos en runtime con CGSSetSymbolicHotKeyEnabled
//      y lo restauramos al cerrar la app (para no dejar el atajo del usuario roto).
// Carbon ya estaba importado; no se añaden dependencias nuevas.

// ID del symbolic hotkey de macOS "Show Finder search window" (⌘⌥Space).
private let kFinderSearchHotKeyID: CInt = 65

final class HotkeyManager {
    static let shared = HotkeyManager()

    var onFocusModal: (() -> Void)?

    private var hotKeyRef: EventHotKeyRef?
    private var eventHandler: EventHandlerRef?
    private var finderHotKeyDisabled = false

    private init() {}

    func start() {
        // Liberar ⌘⌥Space desactivando el atajo de Finder (symbolic hotkey 65).
        if CGSSetSymbolicHotKeyEnabled(kFinderSearchHotKeyID, false) == 0 {
            finderHotKeyDisabled = true
        } else {
            NSLog("JARVIS: no se pudo desactivar el atajo de Finder (⌘⌥Space)")
        }

        var eventType = EventTypeSpec(
            eventClass: OSType(kEventClassKeyboard),
            eventKind: OSType(kEventHotKeyPressed)
        )
        let selfPtr = Unmanaged.passUnretained(self).toOpaque()

        InstallEventHandler(
            GetApplicationEventTarget(),
            { _, _, userData -> OSStatus in
                guard let userData else { return noErr }
                let manager = Unmanaged<HotkeyManager>.fromOpaque(userData).takeUnretainedValue()
                manager._fire()
                return noErr
            },
            1,
            &eventType,
            selfPtr,
            &eventHandler
        )

        // 'JRS1' como firma del hotkey; id 1.
        let hotKeyID = EventHotKeyID(signature: OSType(0x4A525331), id: 1)
        let modifiers = UInt32(cmdKey | optionKey)

        let status = RegisterEventHotKey(
            UInt32(kVK_Space),
            modifiers,
            hotKeyID,
            GetApplicationEventTarget(),
            0,
            &hotKeyRef
        )
        if status != noErr {
            NSLog("JARVIS: RegisterEventHotKey falló con código \(status)")
        }
    }

    func stop() {
        if let hotKeyRef {
            UnregisterEventHotKey(hotKeyRef)
            self.hotKeyRef = nil
        }
        if let eventHandler {
            RemoveEventHandler(eventHandler)
            self.eventHandler = nil
        }
        // Restaurar el atajo de Finder si lo habíamos desactivado.
        if finderHotKeyDisabled {
            _ = CGSSetSymbolicHotKeyEnabled(kFinderSearchHotKeyID, true)
            finderHotKeyDisabled = false
        }
    }

    private func _fire() {
        DispatchQueue.main.async { [weak self] in self?.onFocusModal?() }
    }
}
