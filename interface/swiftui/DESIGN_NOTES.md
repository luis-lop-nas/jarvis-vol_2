# JARVIS Overlay — Notas de diseño (medidas y fuentes)

> Investigación previa al pulido del overlay (P1–P8). Solo se han extraído **medidas
> y patrones** de proyectos open-source; no se ha copiado código con licencia incompatible.

## Máquina de referencia
- **Modelo:** `Mac15,12` — MacBook Air 15" M3 (2024). **Tiene notch físico.**
- **Resolución:** 2560×1664 @2x → **1280×832 pt**.
- **Safe-area top (banda del notch/menu bar):** ~37 pt en los MacBook con notch
  (24 pt es la barra de menús estándar sin notch).

## Medidas reales del notch físico (M-series)
| Dato | Valor | Fuente |
|------|-------|--------|
| Ancho del notch (fallback cuando no hay API) | **185 pt** | boring.notch `sizing/matters.swift` (`notchWidth = 185`) |
| Ancho real (cálculo) | `screen.frame.width − auxiliaryTopLeftArea − auxiliaryTopRightArea + 4` | boring.notch `getClosedNotchSize()` |
| Alto del notch (default) | **32 pt** | boring.notch `Constants.swift` (`notchHeight default: 32`) |
| Alto real | `screen.safeAreaInsets.top` (~37 pt) | boring.notch modo `matchRealNotchSize` |

## Medidas y animaciones de las referencias

### MrKai77/DynamicNotchKit (referencia principal)
- `NotchShape` cerrado: **topCornerRadius 6, bottomCornerRadius 14**.
- Preset *notch* abierto: **top 15, bottom 20**. Preset *floating*: cornerRadius 20.
- Muestra de contenido: 200×32, padding 10.
- Animaciones (`DynamicNotchStyle`):
  - Apertura *notch*: `.bouncy(duration: 0.4)`; *floating*: `.snappy(duration: 0.4)`.
  - Cierre: `.smooth(duration: 0.4)`. Conversión compact↔expanded: `.snappy(duration: 0.4)`.

### TheBoredTeam/boring.notch
- `openNotchSize`: **640×190** (panel multimedia completo, más grande que el nuestro).
- `cornerRadiusInsets`: abierto **(top 19, bottom 24)**, cerrado **(top 6, bottom 14)**.
- Animación principal: `spring(.bouncy(duration: 0.4))`; alternativa de énfasis
  `timingCurve(0.16, 1, 0.3, 1, duration: 0.7)` (easeOutExpo).
- `minimumHoverDuration`: 0.3 s. `spacing`: 16.

### Lakr233/NotchDrop, NotchNook, Alcove
- Confirman el patrón: el panel **cuelga del borde superior** (top corners casi rectos,
  bottom corners redondeados) y se expande hacia abajo con spring bouncy corto (~0.35–0.45 s).

## Medidas ADOPTADAS por JARVIS y por qué

| Elemento | Antes | Ahora | Justificación |
|----------|-------|-------|---------------|
| Notch colapsado (ancho×alto) | 120×22 | **200×32** | 120 era más estrecho que el notch físico (185) → el pill quedaba **oculto tras el notch**. 200 lo envuelve y sus esquinas inferiores asoman. Alto 32 = alto de notch (boring.notch). |
| Notch expandido | 240×38 | **340×44** | Cabe dot + status + herramienta + badge de modelo sin apretar. Más pequeño que boring (640×190) porque es un status pill, no panel multimedia. |
| Radio esquinas colapsado | top 0 / bottom 14 | **top 6 / bottom 14** | Coincide con DNK y boring (cerrado 6/14). El top 6 redondea sutilmente el encuentro con el notch. |
| Radio esquinas expandido | top 0 / bottom 14 | **top 6 / bottom 20** | boring abierto bottom 24, DNK notch 20 → 20 como término medio. |
| Animación abrir/expandir | `spring(response:0.3, damping:0.8)` | **`.bouncy(duration: 0.4)`** | Estándar compartido por DNK y boring para apertura de notch. |
| Animación cerrar | `easeInOut(0.3)` | **`.smooth(duration: 0.4)`** | Cierre sin rebote (DNK closing). |

## ADRs de diseño
- **ADR-D1 (tamaño del notch):** el colapsado iguala el notch físico (200×32) para no
  quedar oculto tras él; fuente boring.notch (185 fallback) + margen visual.
- **ADR-D2 (curvas):** apertura `.bouncy(0.4)`, cierre `.smooth(0.4)`, coherente con
  DynamicNotchKit y boring.notch. Se evita mezclar curvas ad-hoc por estado.
- **ADR-D3 (radios):** cerrado 6/14, abierto 6/20 — top pequeño (encuentro con notch),
  bottom mayor (cuelgue del panel).

## Fuentes
- https://github.com/MrKai77/DynamicNotchKit
- https://github.com/TheBoredTeam/boring.notch
- https://github.com/Lakr233/NotchDrop
