import SwiftUI

// MARK: - OnboardingView
// Panel de bienvenida de 3 pasos. Aparece solo la primera vez.
// Controlado por UserDefaults "jarvis.onboardingCompleted".

struct OnboardingStep {
    let icon: String   // SF Symbol name
    let title: String
    let body: String
    let action: String
}

struct OnboardingView: View {
    @State private var currentStep = 0

    private let bg = Color(red: 0.07, green: 0.07, blue: 0.09)
    private let blue = Color(red: 0.22, green: 0.54, blue: 0.87)

    private let steps: [OnboardingStep] = [
        OnboardingStep(
            icon: "hand.wave",
            title: "Hola, soy JARVIS",
            body: "Tu asistente personal para macOS. Puedo controlar tu Mac, leer archivos, " +
                  "navegar por la web y mucho más — de forma autónoma.",
            action: "Siguiente"
        ),
        OnboardingStep(
            icon: "keyboard",
            title: "⌘⌥Space para activarme",
            body: "Pulsa ⌘⌥Space desde cualquier app para abrirme. " +
                  "También puedes hacer click en el icono de la barra de menú.",
            action: "Siguiente"
        ),
        OnboardingStep(
            icon: "lock.shield",
            title: "Siempre te pido permiso",
            body: "Para borrar archivos, enviar emails o ejecutar comandos, " +
                  "siempre verás una confirmación antes de que actúe.",
            action: "Empezar"
        ),
    ]

    var body: some View {
        ZStack {
            VisualEffectBlur(material: .hudWindow, blendingMode: .behindWindow)
            bg.opacity(0.85)

            VStack(spacing: 0) {
                Spacer()

                // Icono
                Image(systemName: steps[currentStep].icon)
                    .font(.system(size: 48, weight: .light))
                    .foregroundStyle(blue)
                    .padding(.bottom, 24)
                    .id(currentStep)
                    .transition(.opacity.combined(with: .scale(scale: 0.8)))

                // Título
                Text(steps[currentStep].title)
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(.white)
                    .multilineTextAlignment(.center)
                    .padding(.bottom, 12)
                    .id("title_\(currentStep)")
                    .transition(.opacity)

                // Cuerpo
                Text(steps[currentStep].body)
                    .font(.system(size: 13))
                    .foregroundStyle(.white.opacity(0.7))
                    .multilineTextAlignment(.center)
                    .lineSpacing(5)
                    .frame(maxWidth: 320)
                    .padding(.bottom, 32)
                    .id("body_\(currentStep)")
                    .transition(.opacity)

                Spacer()

                // Indicador de paso (dots)
                HStack(spacing: 8) {
                    ForEach(0..<steps.count, id: \.self) { i in
                        Circle()
                            .fill(i == currentStep ? blue : .white.opacity(0.25))
                            .frame(width: 7, height: 7)
                            .animation(.spring(response: 0.3), value: currentStep)
                    }
                }
                .padding(.bottom, 24)

                // Botón primario
                Button(action: _advance) {
                    Text(steps[currentStep].action)
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12)
                        .background(blue, in: RoundedRectangle(cornerRadius: 10))
                }
                .buttonStyle(.plain)
                .padding(.horizontal, 32)
                .padding(.bottom, 32)
            }
        }
        .frame(width: 400, height: 320)
        .clipShape(RoundedRectangle(cornerRadius: 20))
        .overlay(
            RoundedRectangle(cornerRadius: 20)
                .strokeBorder(blue.opacity(0.2), lineWidth: 0.5)
        )
        .shadow(color: .black.opacity(0.5), radius: 30, y: 15)
    }

    private func _advance() {
        if currentStep < steps.count - 1 {
            withAnimation(.spring(response: 0.4, dampingFraction: 0.8)) {
                currentStep += 1
            }
        } else {
            UserDefaults.standard.set(true, forKey: "jarvis.onboardingCompleted")
            WindowManager.shared.closeOnboarding()
        }
    }
}

#Preview {
    OnboardingView()
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(.black)
}
