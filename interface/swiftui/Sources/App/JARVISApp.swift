import SwiftUI

// App principal como menu bar app (LSUIElement=true en Info.plist).
// Sin icono en Dock. Solo vive en la barra de menú y como overlay.
// Al arrancar verifica que FastAPI esté corriendo en :8765.
// Si no: lanza el proceso Python automáticamente.

@main
struct JARVISApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        // Sin ventana principal. Toda la UI vive en ventanas flotantes
        // gestionadas por WindowManager desde AppDelegate.
        Settings {
            EmptyView()
        }
    }
}

// MARK: - Verificación y arranque del backend

extension AppDelegate {
    func checkAndLaunchBackend() {
        Task {
            let running = await _isAPIRunning()
            if !running {
                await _launchPythonBackend()
            }
        }
    }

    private func _isAPIRunning() async -> Bool {
        guard let url = URL(string: "http://127.0.0.1:8765/status") else { return false }
        do {
            let (_, response) = try await URLSession.shared.data(from: url)
            return (response as? HTTPURLResponse)?.statusCode == 200
        } catch {
            return false
        }
    }

    private func _launchPythonBackend() async {
        // Busca el main.py junto al .app
        let appDir = Bundle.main.bundlePath
        let candidates = [
            "\(appDir)/../../../../main.py",  // durante desarrollo
            "\(NSHomeDirectory())/Applications/JARVIS/main.py",
        ]

        let python = _findPython()

        for candidate in candidates {
            let expanded = (candidate as NSString).standardizingPath
            if FileManager.default.fileExists(atPath: expanded) {
                let process = Process()
                process.executableURL = URL(fileURLWithPath: python)
                process.arguments = [expanded]
                process.currentDirectoryURL = URL(fileURLWithPath: expanded).deletingLastPathComponent()
                try? process.run()
                return
            }
        }
    }

    private func _findPython() -> String {
        for candidate in ["/usr/local/bin/python3", "/usr/bin/python3", "/opt/homebrew/bin/python3"] {
            if FileManager.default.fileExists(atPath: candidate) { return candidate }
        }
        return "python3"
    }
}
