"""
Webhook FastAPI — recibe mensajes de WhatsApp (360dialog / Cloud API)
y los procesa con el agente.

Endpoints:
  GET  /health
  GET  /webhook/{clinic_id}   — verificación inicial de 360dialog
  POST /webhook/{clinic_id}   — mensajes entrantes
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from dental.core.agent import process_message
from dental.core.database import get_db

logger = logging.getLogger("dental.webhook")
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title       = "Dental Agent Webhook",
    description = "Agente de WhatsApp para clínicas dentales",
    version     = "1.0.0",
)

WEBHOOK_SECRET = os.getenv("WHATSAPP_WEBHOOK_SECRET", "dev_secret_changeme")


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def verify_whatsapp_signature(body: bytes, signature_header: Optional[str]) -> bool:
    """Verifica la firma HMAC-SHA256 de 360dialog/Meta."""
    if not signature_header:
        return False
    sig = signature_header.replace("sha256=", "")
    expected = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def parse_whatsapp_payload(payload: dict) -> Optional[dict]:
    """
    Extrae teléfono, texto y nombre del formato de WhatsApp Cloud API / 360dialog.
    Devuelve None si el mensaje no es de texto o el payload es incompleto.
    """
    try:
        entry   = payload["entry"][0]
        changes = entry["changes"][0]
        value   = changes["value"]

        if "messages" not in value:
            return None

        message = value["messages"][0]
        if message.get("type") != "text":
            return None   # ignoramos imágenes, audio, etc.

        phone = message["from"]
        text  = message["text"]["body"].strip()
        mid   = message["id"]

        contacts = value.get("contacts", [])
        name = contacts[0].get("profile", {}).get("name") if contacts else None

        return {"phone": phone, "text": text, "message_id": mid, "name": name}

    except (KeyError, IndexError, TypeError):
        return None


# ─────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────

@app.get("/health")
async def health():
    db     = get_db()
    clinic = db.get_clinic("clinic_001")
    return {
        "status": "ok",
        "db":     "ok" if clinic else "sin_datos",
        "clinic_demo": clinic.name if clinic else None,
    }


@app.get("/webhook/{clinic_id}")
async def verify_webhook(
    clinic_id:         str,
    hub_mode:          Optional[str] = None,
    hub_challenge:     Optional[str] = None,
    hub_verify_token:  Optional[str] = None,
):
    """
    Verificación inicial del webhook por 360dialog/Meta.
    Deben coincidir hub_verify_token == WEBHOOK_SECRET.
    """
    db     = get_db()
    clinic = db.get_clinic(clinic_id)
    if not clinic:
        raise HTTPException(status_code=404, detail=f"Clínica {clinic_id} no encontrada")

    if hub_mode == "subscribe" and hub_verify_token == WEBHOOK_SECRET:
        logger.info(f"Webhook verificado para clínica {clinic_id}")
        return PlainTextResponse(hub_challenge or "")

    raise HTTPException(status_code=403, detail="Token de verificación incorrecto")


@app.post("/webhook/{clinic_id}")
async def receive_message(
    clinic_id:              str,
    request:                Request,
    x_hub_signature_256:    Optional[str] = Header(None),
):
    """
    Recibe mensajes de WhatsApp para una clínica.
    Valida la firma, parsea el payload, y llama al agente.
    """
    body    = await request.body()
    payload = {}

    # Parsear JSON
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Payload no es JSON válido")

    # Verificar firma (desactivar solo en desarrollo local)
    verify_signatures = os.getenv("VERIFY_SIGNATURES", "false").lower() == "true"
    if verify_signatures and not verify_whatsapp_signature(body, x_hub_signature_256):
        logger.warning(f"Firma inválida para clínica {clinic_id}")
        raise HTTPException(status_code=401, detail="Firma inválida")

    # Verificar que la clínica existe
    db     = get_db()
    clinic = db.get_clinic(clinic_id)
    if not clinic:
        raise HTTPException(status_code=404, detail=f"Clínica {clinic_id} no encontrada")

    # Parsear mensaje
    msg = parse_whatsapp_payload(payload)
    if not msg:
        # Payload válido pero sin mensaje de texto (ej: delivery receipt)
        return JSONResponse({"status": "ignored", "reason": "no_text_message"})

    logger.info(f"[{clinic_id}] Mensaje de {msg['phone']}: {msg['text'][:50]}...")

    # Procesar con el agente
    try:
        response_text = process_message(
            patient_phone = msg["phone"],
            message_text  = msg["text"],
            clinic_id     = clinic_id,
            patient_name  = msg.get("name"),
        )
    except Exception as e:
        logger.error(f"Error en agente: {e}", exc_info=True)
        # Respuesta de fallback — nunca dejar al paciente sin respuesta
        response_text = (
            "Lo siento, ha ocurrido un error técnico. "
            f"Por favor llama directamente a la clínica: {clinic.phone}"
        )

    # En producción: enviar response_text via 360dialog API
    # await send_whatsapp(to=msg["phone"], text=response_text, clinic=clinic)

    return JSONResponse({
        "status":         "processed",
        "clinic_id":      clinic_id,
        "patient_phone":  msg["phone"],
        "response":       response_text,
    })


# ─────────────────────────────────────────────
# ARRANQUE LOCAL
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
