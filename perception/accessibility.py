"""Acceso al árbol de accesibilidad de macOS (AX API).

Permite leer la jerarquía de elementos UI de cualquier app activa, lo que
es preferible al OCR cuando la información está disponible: es más rápido,
preciso y robusto frente a cambios de tema.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class NodoUI:
    """Nodo del árbol de accesibilidad."""

    rol: str
    titulo: str | None = None
    valor: str | None = None
    descripcion: str | None = None
    posicion: tuple[int, int] | None = None
    tamano: tuple[int, int] | None = None
    habilitado: bool = True
    hijos: list["NodoUI"] = field(default_factory=list)
    atributos: dict[str, Any] = field(default_factory=dict)


class ArbolAccesibilidad:
    """Lector del árbol AX de la app frontal o de un PID concreto."""

    async def app_frontal(self) -> NodoUI:
        """Devuelve el árbol AX de la app actualmente en primer plano."""
        return await asyncio.to_thread(self._leer_app_frontal)

    async def app_por_pid(self, pid: int) -> NodoUI:
        """Devuelve el árbol AX de la app con el PID indicado."""
        return await asyncio.to_thread(self._leer_app_por_pid, pid)

    async def buscar(self, raiz: NodoUI, predicado_rol: str) -> list[NodoUI]:
        """Busca recursivamente nodos por rol AX (ej. 'AXButton')."""
        encontrados: list[NodoUI] = []
        self._buscar_recursivo(raiz, predicado_rol, encontrados)
        return encontrados

    # ------------------------------------------------------------------
    # Internos: pyobjc / ApplicationServices
    # ------------------------------------------------------------------

    def _leer_app_frontal(self) -> NodoUI:
        from AppKit import NSWorkspace  # type: ignore[import-not-found]

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return self._leer_app_por_pid(app.processIdentifier())

    def _leer_app_por_pid(self, pid: int) -> NodoUI:
        from ApplicationServices import (  # type: ignore[import-not-found]
            AXUIElementCreateApplication,
        )

        elemento = AXUIElementCreateApplication(pid)
        return self._serializar(elemento)

    def _serializar(self, elemento: Any, profundidad: int = 0, max_profundidad: int = 8) -> NodoUI:
        """Convierte un AXUIElement en un `NodoUI` recursivamente."""
        from ApplicationServices import (  # type: ignore[import-not-found]
            AXUIElementCopyAttributeValue,
        )

        def attr(nombre: str) -> Any:
            err, valor = AXUIElementCopyAttributeValue(elemento, nombre, None)
            return valor if err == 0 else None

        nodo = NodoUI(
            rol=attr("AXRole") or "",
            titulo=attr("AXTitle"),
            valor=attr("AXValue"),
            descripcion=attr("AXDescription"),
        )
        if profundidad < max_profundidad:
            for hijo in attr("AXChildren") or []:
                nodo.hijos.append(self._serializar(hijo, profundidad + 1, max_profundidad))
        return nodo

    def _buscar_recursivo(
        self, nodo: NodoUI, rol: str, acumulador: list[NodoUI]
    ) -> None:
        if nodo.rol == rol:
            acumulador.append(nodo)
        for h in nodo.hijos:
            self._buscar_recursivo(h, rol, acumulador)
