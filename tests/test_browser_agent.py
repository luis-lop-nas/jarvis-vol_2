"""Tests de GestorSesiones y SesionNavegador con páginas HTML locales (file://).

Requiere: playwright install chromium
Se saltan automáticamente si Playwright no está disponible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("playwright.async_api", reason="playwright no instalado — ejecuta: playwright install chromium")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _aprobar(_: str) -> bool:
    return True


async def _denegar(_: str) -> bool:
    return False


@pytest.fixture
def paginas(tmp_path: Path) -> dict[str, str]:
    """Crea páginas HTML locales y devuelve sus URLs file://."""
    contenidos: dict[str, str] = {
        "inicio": (
            "<html><body>"
            "<h1>Página de inicio</h1>"
            "<p>Texto de prueba para verificar extracción de contenido</p>"
            "<a href='formulario.html' id='link-form'>Ir al formulario</a>"
            "</body></html>"
        ),
        "formulario": (
            "<html><body>"
            "<form action='resultado.html' method='get'>"
            "<label for='nombre'>Nombre</label>"
            "<input id='nombre' name='nombre' type='text' />"
            "<label for='email'>Email</label>"
            "<input id='email' name='email' type='email' />"
            "<input type='submit' value='Enviar' />"
            "</form>"
            "</body></html>"
        ),
        "resultado": (
            "<html><body>"
            "<p id='ok'>Formulario enviado correctamente</p>"
            "</body></html>"
        ),
        "enlaces": (
            "<html><body>"
            "<a href='inicio.html'>Inicio</a>"
            "<a href='formulario.html'>Formulario</a>"
            "<a href='https://example.com' id='ext'>Externo</a>"
            "</body></html>"
        ),
    }
    urls: dict[str, str] = {}
    for nombre, html in contenidos.items():
        path = tmp_path / f"{nombre}.html"
        path.write_text(html, encoding="utf-8")
        urls[nombre] = path.as_uri()
    return urls


@pytest.fixture
async def gestor():
    """GestorSesiones headless con permisos externos pre-aprobados."""
    from actions.browser import GestorSesiones, PermisosBrowser

    async with GestorSesiones(
        headless=True,
        confirmar=_aprobar,
        permisos={PermisosBrowser.NAVEGACION_EXTERNA},
    ) as g:
        yield g


# ---------------------------------------------------------------------------
# open_url y get_text
# ---------------------------------------------------------------------------


async def test_open_url_ok(gestor, paginas) -> None:
    sesion = await gestor.obtener_sesion("s1")
    res = await sesion.open_url(paginas["inicio"])
    assert res.ok
    assert "inicio.html" in res.url_actual


async def test_open_url_cambia_url(gestor, paginas) -> None:
    sesion = await gestor.obtener_sesion("s1")
    await sesion.open_url(paginas["inicio"])
    res = await sesion.open_url(paginas["formulario"])
    assert res.url_cambio
    assert "formulario.html" in res.url_actual


async def test_get_text_extrae_contenido(gestor, paginas) -> None:
    sesion = await gestor.obtener_sesion("s1")
    await sesion.open_url(paginas["inicio"])
    texto = await sesion.get_text()
    assert "Página de inicio" in texto
    assert "Texto de prueba" in texto


# ---------------------------------------------------------------------------
# click
# ---------------------------------------------------------------------------


async def test_click_por_texto_navega(gestor, paginas) -> None:
    sesion = await gestor.obtener_sesion("s1")
    await sesion.open_url(paginas["inicio"])
    res = await sesion.click("Ir al formulario")
    assert res.ok
    assert res.url_cambio
    assert "formulario.html" in res.url_actual


async def test_click_por_selector_navega(gestor, paginas) -> None:
    sesion = await gestor.obtener_sesion("s1")
    await sesion.open_url(paginas["inicio"])
    res = await sesion.click("#link-form")
    assert res.ok
    assert res.url_cambio


async def test_click_selector_inexistente_falla(gestor, paginas) -> None:
    sesion = await gestor.obtener_sesion("s1")
    await sesion.open_url(paginas["inicio"])
    res = await sesion.click("#no-existe-este-elemento")
    assert not res.ok
    assert res.mensaje != ""


# ---------------------------------------------------------------------------
# fill
# ---------------------------------------------------------------------------


async def test_fill_por_label(gestor, paginas) -> None:
    sesion = await gestor.obtener_sesion("s1")
    await sesion.open_url(paginas["formulario"])
    res = await sesion.fill("Nombre", "Luis")
    assert res.ok


async def test_fill_por_selector(gestor, paginas) -> None:
    sesion = await gestor.obtener_sesion("s1")
    await sesion.open_url(paginas["formulario"])
    res = await sesion.fill("#email", "luis@example.com")
    assert res.ok


async def test_fill_campo_inexistente_falla(gestor, paginas) -> None:
    sesion = await gestor.obtener_sesion("s1")
    await sesion.open_url(paginas["formulario"])
    res = await sesion.fill("#campo-que-no-existe", "valor")
    assert not res.ok


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------


async def test_submit_envio_exitoso(gestor, paginas) -> None:
    sesion = await gestor.obtener_sesion("s1")
    await sesion.open_url(paginas["formulario"])
    await sesion.fill("Nombre", "Luis")
    res = await sesion.submit()
    assert res.ok
    assert res.mensaje == "formulario enviado"


async def test_submit_sin_formulario_falla(gestor, paginas) -> None:
    sesion = await gestor.obtener_sesion("s1")
    await sesion.open_url(paginas["inicio"])
    res = await sesion.submit()
    assert not res.ok
    assert "botón" in res.mensaje


# ---------------------------------------------------------------------------
# wait_for
# ---------------------------------------------------------------------------


async def test_wait_for_texto_existente(gestor, paginas) -> None:
    sesion = await gestor.obtener_sesion("s1")
    await sesion.open_url(paginas["inicio"])
    ok = await sesion.wait_for("Página de inicio", timeout=3_000)
    assert ok


async def test_wait_for_selector_existente(gestor, paginas) -> None:
    sesion = await gestor.obtener_sesion("s1")
    await sesion.open_url(paginas["inicio"])
    ok = await sesion.wait_for("#link-form", timeout=3_000)
    assert ok


async def test_wait_for_texto_inexistente_devuelve_false(gestor, paginas) -> None:
    sesion = await gestor.obtener_sesion("s1")
    await sesion.open_url(paginas["inicio"])
    ok = await sesion.wait_for("Texto que jamás aparecerá en la página", timeout=500)
    assert not ok


# ---------------------------------------------------------------------------
# screenshot
# ---------------------------------------------------------------------------


async def test_screenshot_devuelve_bytes_png(gestor, paginas) -> None:
    sesion = await gestor.obtener_sesion("s1")
    await sesion.open_url(paginas["inicio"])
    png = await sesion.screenshot()
    assert isinstance(png, bytes)
    assert len(png) > 0
    assert png[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# extract_links y extract_forms
# ---------------------------------------------------------------------------


async def test_extract_links_devuelve_lista(gestor, paginas) -> None:
    sesion = await gestor.obtener_sesion("s1")
    await sesion.open_url(paginas["enlaces"])
    enlaces = await sesion.extract_links()
    hrefs = [e.href for e in enlaces]
    assert any("inicio.html" in h for h in hrefs)
    assert any("formulario.html" in h for h in hrefs)
    assert any("example.com" in h for h in hrefs)


async def test_extract_links_texto_correcto(gestor, paginas) -> None:
    sesion = await gestor.obtener_sesion("s1")
    await sesion.open_url(paginas["enlaces"])
    enlaces = await sesion.extract_links()
    textos = [e.texto for e in enlaces]
    assert "Inicio" in textos
    assert "Formulario" in textos


async def test_extract_forms_devuelve_formulario(gestor, paginas) -> None:
    sesion = await gestor.obtener_sesion("s1")
    await sesion.open_url(paginas["formulario"])
    forms = await sesion.extract_forms()
    assert len(forms) == 1
    form = forms[0]
    assert "resultado.html" in form.accion
    nombres = [c.nombre for c in form.campos]
    assert "nombre" in nombres
    assert "email" in nombres


async def test_extract_forms_etiquetas(gestor, paginas) -> None:
    sesion = await gestor.obtener_sesion("s1")
    await sesion.open_url(paginas["formulario"])
    forms = await sesion.extract_forms()
    etiquetas = [c.etiqueta for c in forms[0].campos if c.etiqueta]
    assert "Nombre" in etiquetas
    assert "Email" in etiquetas


async def test_extract_forms_pagina_sin_form(gestor, paginas) -> None:
    sesion = await gestor.obtener_sesion("s1")
    await sesion.open_url(paginas["inicio"])
    forms = await sesion.extract_forms()
    assert forms == []


# ---------------------------------------------------------------------------
# Gestión de sesiones
# ---------------------------------------------------------------------------


async def test_multiples_sesiones_independientes(gestor, paginas) -> None:
    s1 = await gestor.obtener_sesion("sesion-a")
    s2 = await gestor.obtener_sesion("sesion-b")
    await s1.open_url(paginas["inicio"])
    await s2.open_url(paginas["formulario"])
    assert "inicio.html" in s1.url_actual
    assert "formulario.html" in s2.url_actual


async def test_obtener_sesion_misma_id_devuelve_misma(gestor, paginas) -> None:
    s1 = await gestor.obtener_sesion("unique")
    s2 = await gestor.obtener_sesion("unique")
    assert s1 is s2


async def test_sesiones_activas_lista(gestor, paginas) -> None:
    await gestor.obtener_sesion("alpha")
    await gestor.obtener_sesion("beta")
    activas = gestor.sesiones_activas()
    assert "alpha" in activas
    assert "beta" in activas


async def test_cerrar_sesion_la_elimina(gestor, paginas) -> None:
    await gestor.obtener_sesion("temporal")
    assert "temporal" in gestor.sesiones_activas()
    await gestor.cerrar_sesion("temporal")
    assert "temporal" not in gestor.sesiones_activas()


# ---------------------------------------------------------------------------
# Permisos
# ---------------------------------------------------------------------------


async def test_navegacion_externa_denegada_sin_permiso(paginas) -> None:
    from actions.browser import GestorSesiones

    async with GestorSesiones(headless=True, confirmar=_denegar) as gestor:
        sesion = await gestor.obtener_sesion("s")
        res = await sesion.open_url("https://example.com")
    assert not res.ok
    assert "no autorizada" in res.mensaje


async def test_navegacion_local_no_requiere_permiso(paginas) -> None:
    from actions.browser import GestorSesiones

    async with GestorSesiones(headless=True, confirmar=_denegar) as gestor:
        sesion = await gestor.obtener_sesion("s")
        res = await sesion.open_url(paginas["inicio"])
    assert res.ok


async def test_permiso_se_persiste_en_sesion(paginas) -> None:
    """Tras conceder el permiso en la primera navegación externa, no vuelve a preguntar."""
    from actions.browser import GestorSesiones

    llamadas = 0

    async def _contar_y_aprobar(_: str) -> bool:
        nonlocal llamadas
        llamadas += 1
        return True

    async with GestorSesiones(headless=True, confirmar=_contar_y_aprobar) as gestor:
        sesion = await gestor.obtener_sesion("s")
        await sesion.open_url(paginas["inicio"])

    assert llamadas == 0
