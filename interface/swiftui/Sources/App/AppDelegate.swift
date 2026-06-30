import AppKit
import SwiftUI

// MARK: - AppDelegate
// Configura el overlay, permisos y arranque al inicio.

final class AppDelegate: NSObject, NSApplicationDelegate {
    var statusItem: NSStatusItem?
    let state = JARVISState()
    let wsClient = WebSocketClient()

    private var notchWindowController: NSWindowController?
    private var edgeWindowController: NSWindowController?
    private var modalWindowController: NSWindowController?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)  // sin icono en Dock

        _setupStatusBar()
        _checkPermissions()
        _startWebSocket()
        _startHotkey()
        _startContextDetector()
        _showInitialState()
        _checkOnboarding()
    }

    func applicationWillTerminate(_ notification: Notification) {
        wsClient.disconnect()
        HotkeyManager.shared.stop()
        AppContextDetector.shared.stop()
    }

    // MARK: - Setup

    private func _setupStatusBar() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem?.button {
            button.image = NSImage(systemSymbolName: "waveform", accessibilityDescription: "JARVIS")
            button.toolTip = "JARVIS · ⌘⌥Space para activar"
            button.action = #selector(_statusBarTapped)
            button.target = self
        }
    }

    @objc private func _statusBarTapped() {
        state.focusModalShown.toggle()
        if state.focusModalShown { _showFocusModal() } else { _hideFocusModal() }
    }

    private func _checkPermissions() {
        PermissionsManager.shared.checkAll()
        if !PermissionsManager.shared.allGranted {
            PermissionsManager.shared.requestAccessibility()
        }
    }

    private func _startWebSocket() {
        wsClient.onUpdate = { [weak self] update in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.state.applyUpdate(update)
                self._syncWindowsToState()
            }
        }
        wsClient.onConnectionChange = { [weak self] connected in
            Task { @MainActor [weak self] in
                self?.state.isConnected = connected
            }
        }
        wsClient.onLongDisconnect = { [weak self] in
            Task { @MainActor [weak self] in
                self?.state.isDisconnected = true
            }
        }
        wsClient.onConfirmation = { [weak self] data in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.state.applyConfirmation(data)
                self._syncWindowsToState()
            }
        }
        wsClient.onSessionState = { [weak self] msg in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.state.applySessionState(msg)
                self._syncWindowsToState()
            }
        }
        wsClient.connect(sessionId: state.sessionId)
    }

    private func _startHotkey() {
        HotkeyManager.shared.onFocusModal = { [weak self] in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.state.focusModalShown.toggle()
                if self.state.focusModalShown {
                    self._showFocusModal()
                } else {
                    self._hideFocusModal()
                }
            }
        }
        HotkeyManager.shared.start()
    }

    private func _startContextDetector() {
        AppContextDetector.shared.onChange = { [weak self] ctx in
            Task { @MainActor [weak self] in
                guard let self else { return }
                if case .inline = self.state.uiState {
                    self.state.uiState = .inline(
                        app: ctx.bundleId,
                        suggestion: "JARVIS detectó \(ctx.windowTitle)"
                    )
                }
            }
        }
        AppContextDetector.shared.start()
    }

    private func _showInitialState() {
        WindowManager.shared.showNotch(content:
            NotchView(
                status: "Listo",
                model: "",
                agentPhase: state.agentPhase,
                currentToolName: state.currentToolName,
                errorMessage: state.errorMessage,
                progressFraction: 0.0
            )
            .environment(state)
        )
    }

    private func _checkOnboarding() {
        guard !UserDefaults.standard.bool(forKey: "jarvis.onboardingCompleted") else { return }
        WindowManager.shared.showOnboarding(content: OnboardingView())
    }

    // MARK: - Sincronización UI ↔ Estado

    @MainActor
    private func _syncWindowsToState() {
        switch state.uiState {
        case .silent:
            WindowManager.shared.hideEdge()
            _hideFocusModal()

        case .notchPulse(let status, let model):
            WindowManager.shared.showNotch(content:
                NotchView(
                    status: status,
                    model: model,
                    agentPhase: state.agentPhase,
                    currentToolName: state.currentToolName,
                    errorMessage: state.errorMessage,
                    progressFraction: state.currentProgress
                )
                .environment(state)
            )

        case .edgeLog(let steps):
            WindowManager.shared.showEdge(content:
                EdgeLogView(steps: steps)
            )

        case .focusModal:
            if state.focusModalShown { _showFocusModal() }

        case .inline(let app, let suggestion):
            WindowManager.shared.showInline(content:
                InlineView(
                    app: app,
                    suggestion: suggestion,
                    onApply: { [weak self] in self?._sendConfirm(true) },
                    onDismiss: { WindowManager.shared.hideInline() }
                )
            )
        }
    }

    private func _showFocusModal() {
        state.focusModalShown = true
        if case .focusModal = state.uiState {} else {
            state.uiState = .focusModal(query: "", response: "", steps: [])
        }
        WindowManager.shared.showModal(content:
            FocusModalView(
                state: state,
                onClose: { [weak self] in self?._hideFocusModal() },
                onSend: { [weak self] text in self?._sendMessage(text) },
                onConfirm: { [weak self] actionId, confirmed in
                    self?._sendConfirmWithId(actionId, confirmed: confirmed)
                }
            )
        )
    }

    private func _hideFocusModal() {
        state.focusModalShown = false
        WindowManager.shared.hideModal()
    }

    private func _sendMessage(_ text: String) {
        wsClient.send(.message(content: text, sessionId: state.sessionId))
        state.reset()
        state.uiState = .focusModal(query: text, response: "", steps: [])
    }

    private func _sendConfirm(_ confirmed: Bool) {
        guard let conf = state.pendingConfirmation else { return }
        _sendConfirmWithId(conf.id, confirmed: confirmed)
    }

    private func _sendConfirmWithId(_ actionId: String, confirmed: Bool) {
        wsClient.send(.confirm(
            actionId: actionId,
            confirmed: confirmed,
            sessionId: state.sessionId
        ))
        state.pendingConfirmation = nil
    }
}
