"""
WhatsApp Client - 360dialog API

Centraliza el envío de mensajes de WhatsApp.
Soporta: texto, templates, media.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("dental.whatsapp")

DIALOG360_BASE_URL = "https://waba.360dialog.io/v1"


class WhatsAppClient:
    """Cliente para 360dialog WhatsApp Business API."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("DIALOG360_API_KEY")
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=15.0,
                headers={
                    "D360-API-KEY": self.api_key or "",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def send_text(self, to: str, text: str) -> dict:
        """
        Envía mensaje de texto.
        
        Args:
            to: Número de teléfono con código país (ej: +34612345678)
            text: Contenido del mensaje
            
        Returns:
            Respuesta de la API o dict con error
        """
        if not self.is_configured:
            logger.info(f"[DEV MODE] WhatsApp → {to}: {text[:80]}...")
            return {"status": "dev_mode", "message_id": "dev_" + to[-6:]}

        # Normalizar número (quitar espacios, +, etc)
        phone = to.replace(" ", "").replace("+", "").replace("-", "")
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone,
            "type": "text",
            "text": {"body": text},
        }

        try:
            client = await self._get_client()
            response = await client.post(
                f"{DIALOG360_BASE_URL}/messages",
                json=payload,
            )

            if response.status_code == 200:
                data = response.json()
                message_id = data.get("messages", [{}])[0].get("id", "unknown")
                logger.info(f"✓ WhatsApp enviado a {to} (id: {message_id})")
                return {"status": "sent", "message_id": message_id, "response": data}
            else:
                logger.error(f"✗ 360dialog error {response.status_code}: {response.text[:200]}")
                return {
                    "status": "error",
                    "error_code": response.status_code,
                    "error": response.text[:500],
                }

        except httpx.TimeoutException:
            logger.error(f"✗ Timeout enviando a {to}")
            return {"status": "error", "error": "timeout"}
        except Exception as e:
            logger.error(f"✗ Excepción enviando WhatsApp: {e}")
            return {"status": "error", "error": str(e)}

    async def send_template(
        self,
        to: str,
        template_name: str,
        language_code: str = "es",
        components: Optional[list] = None,
    ) -> dict:
        """
        Envía mensaje con template pre-aprobado.
        Útil para: confirmaciones, recordatorios, marketing.
        """
        if not self.is_configured:
            logger.info(f"[DEV MODE] Template '{template_name}' → {to}")
            return {"status": "dev_mode", "template": template_name}

        phone = to.replace(" ", "").replace("+", "").replace("-", "")

        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
            },
        }

        if components:
            payload["template"]["components"] = components

        try:
            client = await self._get_client()
            response = await client.post(
                f"{DIALOG360_BASE_URL}/messages",
                json=payload,
            )

            if response.status_code == 200:
                data = response.json()
                logger.info(f"✓ Template '{template_name}' enviado a {to}")
                return {"status": "sent", "response": data}
            else:
                logger.error(f"✗ Template error {response.status_code}: {response.text[:200]}")
                return {"status": "error", "error": response.text[:500]}

        except Exception as e:
            logger.error(f"✗ Excepción enviando template: {e}")
            return {"status": "error", "error": str(e)}

    async def mark_as_read(self, message_id: str) -> bool:
        """Marca un mensaje como leído (doble check azul)."""
        if not self.is_configured:
            return True

        try:
            client = await self._get_client()
            response = await client.post(
                f"{DIALOG360_BASE_URL}/messages",
                json={
                    "messaging_product": "whatsapp",
                    "status": "read",
                    "message_id": message_id,
                },
            )
            return response.status_code == 200
        except Exception:
            return False


# Singleton para uso global
_client: Optional[WhatsAppClient] = None


def get_whatsapp_client() -> WhatsAppClient:
    """Obtiene el cliente singleton."""
    global _client
    if _client is None:
        _client = WhatsAppClient()
    return _client


async def send_whatsapp(to: str, text: str, clinic_id: str = "") -> bool:
    """
    Función helper para envío rápido.
    Compatible con la firma existente en scheduler.py
    """
    client = get_whatsapp_client()
    result = await client.send_text(to, text)
    return result.get("status") in ("sent", "dev_mode")
