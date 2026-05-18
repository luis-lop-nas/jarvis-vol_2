import AppKit
import ApplicationServices
import AVFoundation
import UserNotifications

@MainActor
final class PermissionsManager {
    static let shared = PermissionsManager()

    private(set) var accessibilityGranted = false
    private(set) var screenRecordingGranted = false

    private init() {}

    func checkAll() {
        accessibilityGranted = AXIsProcessTrusted()
        screenRecordingGranted = _checkScreenRecording()
    }

    func requestAccessibility() {
        let options: CFDictionary = [
            kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true
        ] as CFDictionary
        accessibilityGranted = AXIsProcessTrustedWithOptions(options)
    }

    func openAccessibilitySettings() {
        let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")!
        NSWorkspace.shared.open(url)
    }

    func openScreenRecordingSettings() {
        let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")!
        NSWorkspace.shared.open(url)
    }

    var allGranted: Bool {
        accessibilityGranted && screenRecordingGranted
    }

    // MARK: Private

    private func _checkScreenRecording() -> Bool {
        // CGWindowListCopyWindowInfo con un campo de imagen falla si no hay permiso.
        let windowList = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID)
        return windowList != nil
    }
}
