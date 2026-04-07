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

# ─────────────────────────────────────────────
# INCLUIR ROUTERS ANTES DEL MIDDLEWARE
# ─────────────────────────────────────────────

try:
    from dental.core.auth import router as auth_router
    app.include_router(auth_router)
    logger.info("Auth router loaded")
except ImportError as e:
    logger.warning(f"Auth router not available: {e}")

try:
    from dental.core.onboarding import router as onboarding_router
    app.include_router(onboarding_router)
    logger.info("Onboarding router loaded")
except ImportError as e:
    logger.warning(f"Onboarding router not available: {e}")

try:
    from dental.core.billing import router as billing_router
    app.include_router(billing_router)
    logger.info("Billing router loaded")
except ImportError as e:
    logger.warning(f"Billing router not available: {e}")

# ─────────────────────────────────────────────
# CORS MIDDLEWARE (después de routers)
# ─────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# IN-MEMORY EVENT LOG (ring buffer, max 500)
# ─────────────────────────────────────────────
# Para debug en producción. Ojo: se pierde al reiniciar el proceso —
# para persistir hace falta una tabla `events` en Postgres y migrar.
# Suficiente para los primeros pilotos.

from collections import deque
from threading import Lock

_event_log: deque = deque(maxlen=500)
_event_log_lock = Lock()


def log_event(
    *,
    clinic_id: str,
    type: str,            # message_in | message_out | takeover_on | takeover_off | error | action
    summary: str,
    phone: Optional[str] = None,
    level: str = "info",  # info | warn | error
    extra: Optional[dict] = None,
) -> None:
    """Registra un evento visible desde el dashboard /api/logs/{clinic_id}."""
    with _event_log_lock:
        _event_log.append({
            "ts": datetime.now(MADRID_TZ).isoformat(),
            "clinic_id": clinic_id,
            "type": type,
            "level": level,
            "phone": phone,
            "summary": summary[:300],  # cap por si llega un mensaje gigante
            "extra": extra or {},
        })

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
    log_event(
        clinic_id=clinic_id,
        type="message_in",
        phone=msg["phone"],
        summary=msg["text"],
    )

    # Registrar contacto del paciente (alimenta active_conversations en el dashboard)
    try:
        from dental.core.models import Patient
        existing = db.get_patient(clinic_id, msg["phone"])
        db.upsert_patient(Patient(
            patient_id=existing.patient_id if existing else 0,
            clinic_id=clinic_id,
            phone=msg["phone"],
            name=msg.get("name") or (existing.name if existing else None),
            email=existing.email if existing else None,
            last_visit=existing.last_visit if existing else None,
            last_contact=datetime.now(MADRID_TZ),
        ))
    except Exception as e:
        logger.warning(f"No se pudo actualizar last_contact: {e}")

    # Marcar como leído
    whatsapp = get_whatsapp_client()
    await whatsapp.mark_as_read(msg["message_id"])

    # ═══════════════════════════════════════════
    # HUMAN TAKEOVER: si el dentista tomó el control,
    # NO respondemos. El mensaje queda visible en el
    # dashboard pero el bot se mantiene en silencio.
    # ═══════════════════════════════════════════
    if db.is_human_takeover(clinic_id, msg["phone"]):
        logger.info(
            f"[{clinic_id}] Takeover activo para {msg['phone']} — agente silenciado"
        )
        log_event(
            clinic_id=clinic_id,
            type="action",
            phone=msg["phone"],
            summary="Mensaje recibido — agente en modo manual, no responde",
        )
        return JSONResponse({
            "status": "human_handling",
            "clinic_id": clinic_id,
            "patient_phone": msg["phone"],
        })

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
        log_event(
            clinic_id=clinic_id,
            type="message_out",
            phone=msg["phone"],
            summary=response_text,
        )
    except Exception as e:
        logger.error(f"Error en agente: {e}", exc_info=True)
        log_event(
            clinic_id=clinic_id,
            type="error",
            phone=msg["phone"],
            level="error",
            summary=f"Error en agente: {e}",
        )
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
    """Métricas globales de la clínica para el dashboard."""
    db = get_db()
    clinic = db.get_clinic(clinic_id)
    if not clinic:
        raise HTTPException(status_code=404, detail="Clínica no encontrada")

    now = datetime.now(MADRID_TZ)

    # Todas las citas de la clínica (no solo hoy — el dashboard muestra agregados)
    all_apts = [
        a for a in db._appointments.values() if a.clinic_id == clinic_id
    ]
    today_apts = [
        a for a in all_apts if a.appointment_datetime.date() == now.date()
    ]

    from dental.core.models import AppointmentStatus

    confirmed = sum(1 for a in all_apts if a.status == AppointmentStatus.CONFIRMED)
    pending = sum(1 for a in all_apts if a.status == AppointmentStatus.PENDING)
    cancelled = sum(1 for a in all_apts if a.status == AppointmentStatus.CANCELLED)

    return {
        "clinic_id": clinic_id,
        "clinic_name": clinic.name,
        "date": now.strftime("%Y-%m-%d"),
        "total_appointments": len(all_apts),
        "today_appointments": len(today_apts),
        "confirmed": confirmed,
        "pending": pending,
        "cancelled": cancelled,
        "no_shows": sum(1 for a in all_apts if a.status == AppointmentStatus.NO_SHOW),
    }


# ─────────────────────────────────────────────
# CLINIC DETAIL & UPDATE
# ─────────────────────────────────────────────

@app.get("/api/clinics/{clinic_id}")
async def get_clinic_detail(clinic_id: str):
    """Detalle completo de una clínica (para precargar la pantalla de Settings)."""
    db = get_db()
    clinic = db.get_clinic(clinic_id)
    if not clinic:
        raise HTTPException(status_code=404, detail="Clínica no encontrada")

    return {
        "clinic_id": clinic.clinic_id,
        "name": clinic.name,
        "address": clinic.address,
        "phone": clinic.phone,
        "whatsapp_number": clinic.whatsapp_number,
        "whatsapp_connected": bool(clinic.whatsapp_number),
        "services": [
            {"name": s.name, "price_from": s.price_from} for s in clinic.services
        ],
        "insurance_accepted": clinic.insurance_accepted,
    }


class ClinicUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    whatsapp_number: Optional[str] = None


@app.patch("/api/clinics/{clinic_id}")
async def update_clinic_endpoint(clinic_id: str, payload: ClinicUpdate):
    """Actualiza los datos editables de una clínica desde el dashboard."""
    db = get_db()
    if not db.get_clinic(clinic_id):
        raise HTTPException(status_code=404, detail="Clínica no encontrada")

    updated = db.update_clinic(clinic_id, payload.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(status_code=500, detail="No se pudo actualizar la clínica")

    logger.info(f"[{clinic_id}] Clínica actualizada: {payload.model_dump(exclude_none=True)}")
    return {
        "clinic_id": updated.clinic_id,
        "name": updated.name,
        "address": updated.address,
        "phone": updated.phone,
        "whatsapp_number": updated.whatsapp_number,
    }


# ─────────────────────────────────────────────
# APPOINTMENTS LIST (para dashboard)
# ─────────────────────────────────────────────

@app.get("/api/appointments/{clinic_id}")
async def list_appointments(
    clinic_id: str,
    status: Optional[str] = None,
    when: str = "all",  # all | upcoming | past | today
    limit: int = 100,
):
    """
    Lista de citas para el dashboard. Soporta filtros básicos.

    - status:  confirmed | pending | cancelled | no_show | completed
    - when:    all | upcoming | past | today
    - limit:   máximo de resultados (default 100)
    """
    db = get_db()
    clinic = db.get_clinic(clinic_id)
    if not clinic:
        raise HTTPException(status_code=404, detail="Clínica no encontrada")

    from dental.core.models import AppointmentStatus

    now = datetime.now(MADRID_TZ)
    apts = [a for a in db._appointments.values() if a.clinic_id == clinic_id]

    if status:
        try:
            target_status = AppointmentStatus(status)
            apts = [a for a in apts if a.status == target_status]
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Estado inválido: {status}")

    if when == "upcoming":
        apts = [a for a in apts if a.appointment_datetime >= now]
    elif when == "past":
        apts = [a for a in apts if a.appointment_datetime < now]
    elif when == "today":
        apts = [a for a in apts if a.appointment_datetime.date() == now.date()]

    # Más recientes / próximas primero
    apts.sort(key=lambda a: a.appointment_datetime, reverse=(when != "upcoming"))
    apts = apts[:limit]

    return {
        "clinic_id": clinic_id,
        "total": len(apts),
        "appointments": [
            {
                "appointment_id": a.appointment_id,
                "patient_phone": a.patient_phone,
                "patient_name": a.patient_name or "Paciente",
                "datetime": a.appointment_datetime.isoformat(),
                "treatment": a.treatment,
                "dentist": a.dentist,
                "duration_min": a.duration_min,
                "status": a.status.value,
                "confirmation_received": a.confirmation_received,
            }
            for a in apts
        ],
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
                "human_takeover": db.is_human_takeover(clinic_id, apt.patient_phone),
            })

    return {"clinic_id": clinic_id, "conversations": conversations}


@app.post("/api/takeover/{clinic_id}")
async def takeover_conversation(clinic_id: str, request: Request):
    """El dentista toma/libera control de una conversación."""
    db = get_db()
    clinic = db.get_clinic(clinic_id)
    if not clinic:
        raise HTTPException(status_code=404, detail="Clínica no encontrada")

    data = await request.json()
    phone = data.get("phone")
    if not phone:
        raise HTTPException(status_code=400, detail="phone es obligatorio")
    enable = bool(data.get("enable", True))

    db.set_human_takeover(clinic_id, phone, enable)

    if enable:
        logger.info(f"[{clinic_id}] Takeover ACTIVADO para {phone}")
        log_event(
            clinic_id=clinic_id, type="takeover_on", phone=phone,
            summary="El dentista tomó el control de la conversación",
        )
        return {
            "status": "takeover_active",
            "clinic_id": clinic_id,
            "phone": phone,
            "human_takeover": True,
            "message": "El agente ya no responderá automáticamente a este paciente.",
        }
    else:
        logger.info(f"[{clinic_id}] Takeover DESACTIVADO para {phone}")
        log_event(
            clinic_id=clinic_id, type="takeover_off", phone=phone,
            summary="El dentista devolvió la conversación al agente",
        )
        return {
            "status": "agent_active",
            "clinic_id": clinic_id,
            "phone": phone,
            "human_takeover": False,
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
# APPOINTMENT ACTIONS (confirmar/cancelar desde dashboard)
# ─────────────────────────────────────────────

class CancelPayload(BaseModel):
    reason: Optional[str] = ""


@app.post("/api/appointments/{appointment_id}/confirm")
async def confirm_appointment_endpoint(appointment_id: str):
    """Marca una cita como confirmada por el dentista desde el dashboard."""
    db = get_db()
    apt = db.get_appointment(appointment_id)
    if not apt:
        raise HTTPException(status_code=404, detail="Cita no encontrada")

    updated = db.confirm_appointment(appointment_id)
    log_event(
        clinic_id=apt.clinic_id,
        type="action",
        phone=apt.patient_phone,
        summary=f"Cita {appointment_id} confirmada manualmente",
    )
    return {
        "appointment_id": appointment_id,
        "status": updated.status.value if updated else "unknown",
        "confirmation_received": updated.confirmation_received if updated else False,
    }


@app.post("/api/appointments/{appointment_id}/cancel")
async def cancel_appointment_endpoint(appointment_id: str, payload: CancelPayload):
    """Cancela una cita desde el dashboard."""
    db = get_db()
    apt = db.get_appointment(appointment_id)
    if not apt:
        raise HTTPException(status_code=404, detail="Cita no encontrada")

    updated = db.cancel_appointment(appointment_id, payload.reason or "")
    log_event(
        clinic_id=apt.clinic_id,
        type="action",
        phone=apt.patient_phone,
        summary=f"Cita {appointment_id} cancelada manualmente: {payload.reason or '(sin motivo)'}",
    )
    return {
        "appointment_id": appointment_id,
        "status": updated.status.value if updated else "unknown",
        "reason": payload.reason or "",
    }


# ─────────────────────────────────────────────
# EVENT LOGS (debug en producción)
# ─────────────────────────────────────────────

@app.get("/api/logs/{clinic_id}")
async def get_logs(
    clinic_id: str,
    limit: int = 100,
    type: Optional[str] = None,
    level: Optional[str] = None,
):
    """
    Devuelve los eventos recientes del agente para una clínica.

    El log es un ring buffer en memoria (max 500 eventos globales).
    Se pierde al reiniciar el proceso. Para auditoría persistente
    hace falta migrar a una tabla en Postgres.
    """
    db = get_db()
    if not db.get_clinic(clinic_id):
        raise HTTPException(status_code=404, detail="Clínica no encontrada")

    with _event_log_lock:
        events = list(_event_log)

    # Filtrar por clínica + filtros opcionales
    events = [e for e in events if e["clinic_id"] == clinic_id]
    if type:
        events = [e for e in events if e["type"] == type]
    if level:
        events = [e for e in events if e["level"] == level]

    # Más recientes primero
    events.reverse()
    return {
        "clinic_id": clinic_id,
        "total": len(events),
        "events": events[:limit],
    }


# ─────────────────────────────────────────────
# ARRANQUE LOCAL
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
