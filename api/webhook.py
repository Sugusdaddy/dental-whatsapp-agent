"""
Webhook FastAPI — recibe mensajes de WhatsApp (360dialog / Cloud API)
y los procesa con el agente.

Modos de operación:
- ASYNC_MODE=true  → Encola en Celery, responde HTTP 200 inmediato
- ASYNC_MODE=false → Procesa síncronamente (desarrollo)

Endpoints:
  GET  /health
  GET  /webhook/{clinic_id}   — verificación inicial de 360dialog
  POST /webhook/{clinic_id}   — mensajes entrantes
  GET  /api/conversations/{clinic_id} — lista conversaciones (para dashboard)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from dental.core.database import get_db
from dental.core.whatsapp_client import get_whatsapp_client, send_whatsapp

logger = logging.getLogger("dental.webhook")
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title       = "Dental Agent Webhook",
    description = "Agente de WhatsApp para clínicas dentales",
    version     = "1.0.0",
)

# CORS para dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción: restringir a dominio del dashboard
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WEBHOOK_SECRET = os.getenv("WHATSAPP_WEBHOOK_SECRET", "dev_secret_changeme")
ASYNC_MODE = os.getenv("ASYNC_MODE", "false").lower() == "true"
MADRID_TZ = ZoneInfo("Europe/Madrid")


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
    db = get_db()
    clinic = db.get_clinic("clinic_001")
    whatsapp = get_whatsapp_client()
    
    # Check Redis/Celery si está en modo async
    celery_status = "disabled"
    if ASYNC_MODE:
        try:
            from dental.core.worker import celery_app
            celery_app.control.ping(timeout=1)
            celery_status = "ok"
        except Exception:
            celery_status = "error"
    
    return {
        "status": "ok",
        "db": "ok" if clinic else "sin_datos",
        "whatsapp": "configured" if whatsapp.is_configured else "dev_mode",
        "async_mode": ASYNC_MODE,
        "celery": celery_status,
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
    
    Si ASYNC_MODE=true:
      - Encola en Celery
      - Responde HTTP 200 inmediatamente
      
    Si ASYNC_MODE=false:
      - Procesa síncronamente
      - Envía respuesta por WhatsApp
    """
    body = await request.body()
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
    db = get_db()
    clinic = db.get_clinic(clinic_id)
    if not clinic:
        raise HTTPException(status_code=404, detail=f"Clínica {clinic_id} no encontrada")

    # Parsear mensaje
    msg = parse_whatsapp_payload(payload)
    if not msg:
        # Payload válido pero sin mensaje de texto (ej: delivery receipt)
        return JSONResponse({"status": "ignored", "reason": "no_text_message"})

    logger.info(f"[{clinic_id}] Mensaje de {msg['phone']}: {msg['text'][:50]}...")

    # Marcar como leído
    whatsapp = get_whatsapp_client()
    await whatsapp.mark_as_read(msg["message_id"])

    # ═══════════════════════════════════════════
    # MODO ASYNC: Encolar en Celery
    # ═══════════════════════════════════════════
    if ASYNC_MODE:
        from dental.core.worker import process_whatsapp_message
        
        task = process_whatsapp_message.delay(
            clinic_id=clinic_id,
            patient_phone=msg["phone"],
            message_text=msg["text"],
            patient_name=msg.get("name"),
            message_id=msg["message_id"],
        )
        
        logger.info(f"[{clinic_id}] Mensaje encolado: task_id={task.id}")
        
        return JSONResponse({
            "status": "queued",
            "task_id": task.id,
            "clinic_id": clinic_id,
            "patient_phone": msg["phone"],
        })

    # ═══════════════════════════════════════════
    # MODO SYNC: Procesar directamente
    # ═══════════════════════════════════════════
    from dental.core.agent import process_message
    
    try:
        response_text = process_message(
            patient_phone=msg["phone"],
            message_text=msg["text"],
            clinic_id=clinic_id,
            patient_name=msg.get("name"),
        )
    except Exception as e:
        logger.error(f"Error en agente: {e}", exc_info=True)
        response_text = (
            "Lo siento, ha ocurrido un error técnico. "
            f"Por favor llama directamente a la clínica: {clinic.phone}"
        )

    # Enviar respuesta por WhatsApp
    send_result = await send_whatsapp(
        to=msg["phone"],
        text=response_text,
        clinic_id=clinic_id,
    )

    return JSONResponse({
        "status": "processed",
        "clinic_id": clinic_id,
        "patient_phone": msg["phone"],
        "response": response_text,
        "whatsapp_sent": send_result,
    })


# ─────────────────────────────────────────────
# API PARA DASHBOARD
# ─────────────────────────────────────────────

@app.get("/api/stats/{clinic_id}")
async def get_clinic_stats(clinic_id: str):
    """Métricas del día para el dashboard del dentista."""
    db = get_db()
    clinic = db.get_clinic(clinic_id)
    if not clinic:
        raise HTTPException(status_code=404, detail="Clínica no encontrada")

    now = datetime.now(MADRID_TZ)

    # Obtener citas de hoy
    all_apts = [
        a for a in db._appointments.values()
        if a.clinic_id == clinic_id
        and a.appointment_datetime.date() == now.date()
    ]

    from dental.core.models import AppointmentStatus

    return {
        "clinic_id": clinic_id,
        "clinic_name": clinic.name,
        "date": now.strftime("%Y-%m-%d"),
        "total_appointments": len(all_apts),
        "confirmed": sum(1 for a in all_apts if a.confirmation_received),
        "pending": sum(1 for a in all_apts if not a.confirmation_received 
                      and a.status == AppointmentStatus.CONFIRMED),
        "cancelled": sum(1 for a in all_apts if a.status == AppointmentStatus.CANCELLED),
        "no_shows": sum(1 for a in all_apts if a.status == AppointmentStatus.NO_SHOW),
    }


@app.get("/api/conversations/{clinic_id}")
async def get_conversations(clinic_id: str, limit: int = 20):
    """Lista de conversaciones recientes para el dashboard."""
    db = get_db()
    clinic = db.get_clinic(clinic_id)
    if not clinic:
        raise HTTPException(status_code=404, detail="Clínica no encontrada")

    # Por ahora devolver pacientes con citas recientes
    recent_apts = sorted(
        [a for a in db._appointments.values() if a.clinic_id == clinic_id],
        key=lambda x: x.appointment_datetime,
        reverse=True,
    )[:limit]

    conversations = []
    seen_phones = set()
    for apt in recent_apts:
        if apt.patient_phone not in seen_phones:
            seen_phones.add(apt.patient_phone)
            patient = db.get_patient(clinic_id, apt.patient_phone)
            conversations.append({
                "phone": apt.patient_phone,
                "name": apt.patient_name or (patient.name if patient else "Paciente"),
                "last_appointment": apt.appointment_datetime.isoformat(),
                "status": apt.status.value,
                "human_takeover": False,
            })

    return {"clinic_id": clinic_id, "conversations": conversations}


@app.post("/api/conversations/{clinic_id}/{phone}/takeover")
async def takeover_conversation(clinic_id: str, phone: str):
    """El dentista toma control de una conversación."""
    db = get_db()
    clinic = db.get_clinic(clinic_id)
    if not clinic:
        raise HTTPException(status_code=404, detail="Clínica no encontrada")

    # TODO: Guardar flag en DB
    logger.info(f"[{clinic_id}] Takeover de conversación con {phone}")

    return {
        "status": "takeover_active",
        "clinic_id": clinic_id,
        "phone": phone,
        "message": "El agente ya no responderá automáticamente a este paciente.",
    }


@app.post("/api/conversations/{clinic_id}/{phone}/release")
async def release_conversation(clinic_id: str, phone: str):
    """Devuelve el control de la conversación al agente."""
    db = get_db()
    clinic = db.get_clinic(clinic_id)
    if not clinic:
        raise HTTPException(status_code=404, detail="Clínica no encontrada")

    logger.info(f"[{clinic_id}] Release de conversación con {phone}")

    return {
        "status": "agent_active",
        "clinic_id": clinic_id,
        "phone": phone,
        "message": "El agente volverá a responder automáticamente.",
    }


# ─────────────────────────────────────────────
# CELERY TASK STATUS
# ─────────────────────────────────────────────

@app.get("/api/task/{task_id}")
async def get_task_status(task_id: str):
    """Consulta el estado de una tarea de Celery."""
    if not ASYNC_MODE:
        raise HTTPException(status_code=400, detail="Async mode not enabled")
    
    from dental.core.worker import celery_app
    result = celery_app.AsyncResult(task_id)
    
    return {
        "task_id": task_id,
        "status": result.status,
        "result": result.result if result.ready() else None,
    }


# ─────────────────────────────────────────────
# ARRANQUE LOCAL
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
