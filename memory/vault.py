"""Vault de 1Password: acceso seguro a secretos sin persistencia local."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from config import settings


AuthCallback = Callable[[], Awaitable[bool]]


class VaultItem(BaseModel):
    """Item de 1Password expuesto en la interfaz de vault."""

    title: str
    category: str
    username: str | None = None
    url: str | None = None


class Vault:
    """Interfaz segura hacia la CLI de 1Password (`op`)."""

    def __init__(
        self,
        auth_callback: AuthCallback | None = None,
        timeout_seconds: int = settings.vault_timeout_seconds,
    ) -> None:
        self._auth_callback = auth_callback or self._deny_by_default
        self._timeout = timeout_seconds

    async def is_available(self) -> bool:
        """Devuelve `True` si la CLI `op` está instalada y accesible."""
        return shutil.which("op") is not None

    async def list_items(self, category_filter: str | None = None) -> list[VaultItem]:
        """Lista items disponibles en 1Password, opcionalmente filtrados por categoría."""
        await self._authorize()
        salida = await self._run_op("item", "list", "--format", "json")
        datos = json.loads(salida)
        items: list[VaultItem] = []
        for item in datos:
            categoria = item.get("category", "unknown")
            if category_filter and categoria.lower() != category_filter.lower():
                continue
            items.append(
                VaultItem(
                    title=item.get("title", ""),
                    category=categoria,
                    username=None,
                    url=None,
                )
            )
        return items

    async def get_password(self, title: str) -> str | None:
        """Recupera la contraseña de un item; requiere autorización previa."""
        await self._authorize()
        item = await self._get_item_json(title)
        for campo in item.get("fields", []):
            if campo.get("designation") in ("password", "api key") or campo.get("type") == "PASSWORD":
                return campo.get("value")
        return None

    async def get_api_key(self, service_name: str) -> str | None:
        """Recupera una API key para un servicio registrado en 1Password."""
        await self._authorize()
        item = await self._get_item_json(service_name)
        for campo in item.get("fields", []):
            if campo.get("designation", "").lower() in ("api key", "password"):
                return campo.get("value")
        return None

    async def get_login(self, url: str) -> tuple[str, str] | None:
        """Devuelve usuario y contraseña para el login asociado a una URL."""
        await self._authorize()
        salida = await self._run_op("item", "list", "--format", "json")
        datos = json.loads(salida)
        for item in datos:
            urls = [u.get("url", "") for u in item.get("urls", [])]
            if any(url.lower() in u.lower() for u in urls):
                detalle = await self._get_item_json(item.get("title", ""))
                usuario = None
                contraseña = None
                for campo in detalle.get("fields", []):
                    if campo.get("type") == "USERNAME":
                        usuario = campo.get("value")
                    if campo.get("designation") in ("password", "api key") or campo.get("type") == "PASSWORD":
                        contraseña = campo.get("value")
                if usuario and contraseña:
                    return usuario, contraseña
        return None

    async def store_note(self, title: str, content: str) -> bool:
        """Guarda una nota segura en 1Password."""
        await self._authorize()
        await self._run_op(
            "item",
            "create",
            "--category",
            "secureNote",
            "--title",
            title,
            "--notesPlain",
            content,
            "--format",
            "json",
        )
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _authorize(self) -> None:
        try:
            autorizado = await asyncio.wait_for(self._auth_callback(), timeout=self._timeout)
        except asyncio.TimeoutError as exc:
            raise TimeoutError("Autenticación Face ID no completada en tiempo") from exc
        if not autorizado:
            raise PermissionError("Autenticación requerida para acceder al vault")

    async def _get_item_json(self, title: str) -> dict[str, Any]:
        salida = await self._run_op("item", "get", title, "--format", "json")
        return json.loads(salida)

    async def _run_op(self, *args: str) -> str:
        if not await self.is_available():
            raise FileNotFoundError(
                "La CLI 'op' de 1Password no está instalada. Instálala con: "
                "brew install --cask 1password-cli y ejecuta `op signin`."
            )
        proceso = await asyncio.create_subprocess_exec(
            "op",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        salida, error = await asyncio.wait_for(proceso.communicate(), timeout=self._timeout)
        if proceso.returncode != 0:
            raise RuntimeError(
                f"op CLI falló con código {proceso.returncode}: {error.decode(errors='ignore')}"
            )
        return salida.decode("utf-8")

    @staticmethod
    async def _deny_by_default() -> bool:
        return False
