"""
Celery Worker para procesamiento asíncrono de mensajes.

El webhook encola tareas aquí para:
1. Responder inmediatamente HTTP 200 a WhatsApp (evita timeout)
2. Procesar el mensaje con el agente en background
3. Enviar la respuesta por WhatsApp

Arrancar con:
    celery -A dental.core.worker worker --loglevel=info
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from celery import Celery

# Re-exported at module level so tests (and callers) can patch
# `dental.core.worker.get_db` / `send_whatsapp` / `process_message` directly.
from dental.core.database import get_db  # noqa: E402
from dental.core.whatsapp_client import send_whatsapp  # noqa: E402
from dental.core.agent import process_message  # noqa: E402

logger = logging.getLogger("dental.worker")

# ─────────────────────────────────────────────
# CELERY CONFIG
# ─────────────────────────────────────────────

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "dental",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Madrid",
    enable_utc=True,
    # Retry settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Rate limiting
    task_default_rate_limit="10/s",
    # Results expire after 1 hour
    result_expires=3600,
)


# ─────────────────────────────────────────────
# TASKS
# ─────────────────────────────────────────────

@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    autoretry_for=(Exception,),
)
def process_whatsapp_message(
    self,
    clinic_id: str,
    patient_phone: str,
    message_text: str,
    patient_name: Optional[str] = None,
    message_id: Optional[str] = None,
):
    """
    Procesa un mensaje de WhatsApp de forma asíncrona.
    
    1. Llama al agente para generar respuesta
    2. Envía la respuesta por WhatsApp
    3. Guarda el historial de conversación
    """
    import asyncio

    logger.info(f"[{clinic_id}] Procesando mensaje de {patient_phone}: {message_text[:50]}...")

    # Verificar clínica
    db = get_db()
    clinic = db.get_clinic(clinic_id)
    if not clinic:
        logger.error(f"Clínica {clinic_id} no encontrada")
        return {"status": "error", "error": "clinic_not_found"}

    # Verificar si el dentista tomó control de la conversación
    if db.is_human_takeover(clinic_id, patient_phone):
        logger.info(f"[{clinic_id}] Takeover activo para {patient_phone} — agente silenciado")
        return {"status": "skipped", "reason": "human_takeover"}

    # Procesar con el agente
    try:
        response_text = process_message(
            patient_phone=patient_phone,
            message_text=message_text,
            clinic_id=clinic_id,
            patient_name=patient_name,
        )
    except Exception as e:
        logger.error(f"Error en agente: {e}", exc_info=True)
        response_text = (
            "Lo siento, ha ocurrido un error técnico. "
            f"Por favor llama directamente a la clínica: {clinic.phone}"
        )

    # Enviar respuesta por WhatsApp
    async def send():
        return await send_whatsapp(patient_phone, response_text, clinic_id)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        sent = loop.run_until_complete(send())
    finally:
        loop.close()

    logger.info(f"[{clinic_id}] Respuesta enviada a {patient_phone}: {response_text[:50]}...")

    return {
        "status": "processed",
        "clinic_id": clinic_id,
        "patient_phone": patient_phone,
        "response": response_text[:200],
        "whatsapp_sent": sent,
    }


@celery_app.task
def send_scheduled_reminder(
    clinic_id: str,
    appointment_id: str,
    reminder_type: str,  # "48h" or "2h"
):
    """
    Envía recordatorio programado para una cita.
    Llamado por el scheduler.
    """
    import asyncio
    from dental.core.scheduler import build_reminder_48h, build_reminder_2h

    db = get_db()
    apt = db.get_appointment(appointment_id)
    if not apt:
        logger.error(f"Cita {appointment_id} no encontrada")
        return {"status": "error", "error": "appointment_not_found"}

    clinic = db.get_clinic(clinic_id)
    if not clinic:
        logger.error(f"Clínica {clinic_id} no encontrada")
        return {"status": "error", "error": "clinic_not_found"}

    # Construir mensaje según tipo
    if reminder_type == "48h":
        message = build_reminder_48h(apt, clinic.name)
    else:
        message = build_reminder_2h(apt, clinic.address)

    # Enviar
    async def send():
        return await send_whatsapp(apt.patient_phone, message, clinic_id)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        sent = loop.run_until_complete(send())
    finally:
        loop.close()

    # Marcar como enviado
    if sent:
        if reminder_type == "48h":
            apt.reminder_48h_sent = True
        else:
            apt.reminder_2h_sent = True
        db.save_appointment(apt)

    return {
        "status": "sent" if sent else "failed",
        "appointment_id": appointment_id,
        "reminder_type": reminder_type,
    }


@celery_app.task
def send_weekly_report(clinic_id: str):
    """
    Envía reporte semanal al dentista.
    Llamado por el scheduler los lunes a las 8:00.
    """
    import asyncio
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from dental.core.scheduler import build_weekly_report
    from dental.core.models import AppointmentStatus

    MADRID_TZ = ZoneInfo("Europe/Madrid")
    db = get_db()
    clinic = db.get_clinic(clinic_id)
    if not clinic:
        return {"status": "error", "error": "clinic_not_found"}

    now = datetime.now(MADRID_TZ)
    week_start = now - timedelta(days=7)

    # Calcular métricas
    all_apts = [
        a for a in db._appointments.values()
        if a.clinic_id == clinic_id
        and week_start <= a.appointment_datetime <= now
    ]
    total = len(all_apts)
    no_shows = sum(1 for a in all_apts if a.status == AppointmentStatus.NO_SHOW)
    unconfirmed = sum(
        1 for a in all_apts
        if not a.confirmation_received and a.status == AppointmentStatus.CONFIRMED
    )

    # Huecos próxima semana
    next_monday = (now + timedelta(days=(7 - now.weekday()))).strftime("%Y-%m-%d")
    free_slots = len(db.get_available_slots(clinic_id, next_monday))

    message = build_weekly_report(clinic.name, total, no_shows, unconfirmed, free_slots)

    async def send():
        return await send_whatsapp(clinic.whatsapp_number, message, clinic_id)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        sent = loop.run_until_complete(send())
    finally:
        loop.close()

    return {"status": "sent" if sent else "failed", "clinic_id": clinic_id}


# ─────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────

@celery_app.task
def health_check():
    """Task de prueba para verificar que Celery funciona."""
    return {"status": "ok", "worker": "dental"}
