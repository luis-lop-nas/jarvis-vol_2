import SwiftUI

// MARK: - NotchShape
// Forma que "cuelga" del borde superior imitando la Dynamic Island: los vértices
// superiores tienen un flare CÓNCAVO (curva hacia dentro) que funde el panel con
// la barra de menús / notch físico; los inferiores son redondeados convexos.
// Basado en el patrón de boring.notch / DynamicNotchKit (ver DESIGN_NOTES.md).

struct NotchShape: Shape {
    var topRadius: CGFloat
    var bottomRadius: CGFloat

    // Permite animar los radios con el resto de la expansión.
    var animatableData: AnimatablePair<CGFloat, CGFloat> {
        get { AnimatablePair(topRadius, bottomRadius) }
        set { topRadius = newValue.first; bottomRadius = newValue.second }
    }

    func path(in rect: CGRect) -> Path {
        var p = Path()
        let t = min(topRadius, rect.width / 2)
        let b = min(bottomRadius, (rect.width - 2 * t) / 2, rect.height - t)

        // Esquina superior izquierda: flare cóncavo hacia dentro.
        p.move(to: CGPoint(x: rect.minX, y: rect.minY))
        p.addQuadCurve(
            to: CGPoint(x: rect.minX + t, y: rect.minY + t),
            control: CGPoint(x: rect.minX + t, y: rect.minY)
        )
        // Lado izquierdo hacia abajo.
        p.addLine(to: CGPoint(x: rect.minX + t, y: rect.maxY - b))
        // Esquina inferior izquierda (convexa).
        p.addQuadCurve(
            to: CGPoint(x: rect.minX + t + b, y: rect.maxY),
            control: CGPoint(x: rect.minX + t, y: rect.maxY)
        )
        // Borde inferior.
        p.addLine(to: CGPoint(x: rect.maxX - t - b, y: rect.maxY))
        // Esquina inferior derecha (convexa).
        p.addQuadCurve(
            to: CGPoint(x: rect.maxX - t, y: rect.maxY - b),
            control: CGPoint(x: rect.maxX - t, y: rect.maxY)
        )
        // Lado derecho hacia arriba.
        p.addLine(to: CGPoint(x: rect.maxX - t, y: rect.minY + t))
        // Esquina superior derecha: flare cóncavo.
        p.addQuadCurve(
            to: CGPoint(x: rect.maxX, y: rect.minY),
            control: CGPoint(x: rect.maxX - t, y: rect.minY)
        )
        p.closeSubpath()
        return p
    }
}
