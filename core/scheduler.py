"""
Scheduler de recordatorios automáticos.

Jobs:
  - reminder_48h  → cada hora 9-20, busca citas en 48h y manda recordatorio
  - reminder_2h   → cada hora 8-20, busca citas en 2h y manda confirmación
  - weekly_report → lunes 08:00, resumen semanal al dentista

En producción: integra send_whatsapp() con la API de 360dialog.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from dental.core.database import get_db
from dental.core.models import Appointment, AppointmentStatus, ReminderType

logger    = logging.getLogger("dental.scheduler")
MADRID_TZ = ZoneInfo("Europe/Madrid")


# ─────────────────────────────────────────────
# MENSAJES — plantillas por tipo
# ─────────────────────────────────────────────

def build_reminder_48h(apt: Appointment, clinic_name: str) -> str:
    name = apt.patient_name or "paciente"
    return (
        f"Hola {name} 👋 Te escribimos de {clinic_name}.\n\n"
        f"Tienes cita el {apt.datetime_es()} "
        f"con {apt.dentist} para: *{apt.treatment}*.\n\n"
        f"¿Confirmas tu asistencia? Responde *SÍ* o *NO* 😊"
    )


def build_reminder_2h(apt: Appointment, clinic_address: str) -> str:
    name = apt.patient_name or "paciente"
    return (
        f"¡Hola {name}! ⏰ Recordatorio: tu cita es HOY "
        f"{apt.appointment_datetime.strftime('%H:%M')}.\n\n"
        f"Te esperamos en {clinic_address}.\n"
        f"¿Necesitas cómo llegar?"
    )


def build_weekly_report(
    clinic_name: str,
    total_week: int,
    no_shows: int,
    pending_confirmations: int,
    next_week_slots: int,
) -> str:
    no_show_pct = round((no_shows / total_week * 100) if total_week else 0)
    return (
        f"📊 *Resumen semanal — {datetime.now(MADRID_TZ).strftime('%d/%m/%Y')}*\n\n"
        f"✅ Citas esta semana: {total_week}\n"
        f"❌ No-shows: {no_shows} ({no_show_pct}%)\n"
        f"⏳ Sin confirmar: {pending_confirmations}\n"
        f"📅 Huecos libres próx. semana: {next_week_slots}\n\n"
        f"_Generado automáticamente por tu asistente {clinic_name}_"
    )


# ─────────────────────────────────────────────
# ENVÍO — stub reemplazable por 360dialog
# ─────────────────────────────────────────────

# Importar cliente WhatsApp centralizado
from dental.core.whatsapp_client import send_whatsapp


# ─────────────────────────────────────────────
# JOBS
# ─────────────────────────────────────────────

async def job_reminder_48h():
    """Recordatorio 48h — busca citas y manda WhatsApp."""
    db = get_db()
    # En producción: iterar sobre todas las clínicas activas
    clinic_ids = [c for c in ["clinic_001"] if db.get_clinic(c)]

    total_sent = 0
    for clinic_id in clinic_ids:
        clinic = db.get_clinic(clinic_id)
        apts   = db.get_appointments_needing_reminder(clinic_id, ReminderType.HOURS_48)

        for apt in apts:
            msg     = build_reminder_48h(apt, clinic.name)
            success = await send_whatsapp(apt.patient_phone, msg, clinic_id)

            if success:
                apt.reminder_48h_sent = True
                db.save_appointment(apt)
                total_sent += 1
                logger.info(f"[48h] Recordatorio enviado: {apt.appointment_id} → {apt.patient_phone}")

    if total_sent:
        logger.info(f"[48h] Total enviados: {total_sent}")


async def job_reminder_2h():
    """Recordatorio 2h — busca citas y manda confirmación."""
    db = get_db()
    clinic_ids = [c for c in ["clinic_001"] if db.get_clinic(c)]

    total_sent = 0
    for clinic_id in clinic_ids:
        clinic = db.get_clinic(clinic_id)
        apts   = db.get_appointments_needing_reminder(clinic_id, ReminderType.HOURS_2)

        for apt in apts:
            msg     = build_reminder_2h(apt, clinic.address)
            success = await send_whatsapp(apt.patient_phone, msg, clinic_id)

            if success:
                apt.reminder_2h_sent = True
                db.save_appointment(apt)
                total_sent += 1

    if total_sent:
        logger.info(f"[2h] Total enviados: {total_sent}")


async def job_weekly_report():
    """Reporte semanal — lunes a las 8:00."""
    db    = get_db()
    now   = datetime.now(MADRID_TZ)
    week_start = now - timedelta(days=7)

    clinic_ids = [c for c in ["clinic_001"] if db.get_clinic(c)]

    for clinic_id in clinic_ids:
        clinic = db.get_clinic(clinic_id)

        # Calcular métricas de la semana
        all_apts = [
            a for a in db._appointments.values()
            if a.clinic_id == clinic_id
            and week_start <= a.appointment_datetime <= now
        ]
        total      = len(all_apts)
        no_shows   = sum(1 for a in all_apts if a.status == AppointmentStatus.NO_SHOW)
        unconfirmed = sum(1 for a in all_apts if not a.confirmation_received
                         and a.status == AppointmentStatus.CONFIRMED)

        # Huecos libres próxima semana (lunes)
        next_monday = (now + timedelta(days=(7 - now.weekday()))).strftime("%Y-%m-%d")
        free_slots  = len(db.get_available_slots(clinic_id, next_monday))

        msg = build_weekly_report(clinic.name, total, no_shows, unconfirmed, free_slots)

        # Enviar al número de WhatsApp del dentista (en prod: tabla staff)
        await send_whatsapp(clinic.whatsapp_number, msg, clinic_id)
        logger.info(f"[report] Enviado a {clinic_id}: {total} citas esta semana")


# ─────────────────────────────────────────────
# SCHEDULER
# ─────────────────────────────────────────────

def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=MADRID_TZ)

    # Recordatorio 48h: cada hora en punto, de 9:00 a 20:00
    scheduler.add_job(
        job_reminder_48h,
        CronTrigger(hour="9-20", minute="0", timezone=MADRID_TZ),
        id="reminder_48h", name="Recordatorio 48h", replace_existing=True,
    )

    # Recordatorio 2h: cada hora y media, de 8:30 a 19:30
    scheduler.add_job(
        job_reminder_2h,
        CronTrigger(hour="8-19", minute="30", timezone=MADRID_TZ),
        id="reminder_2h", name="Recordatorio 2h", replace_existing=True,
    )

    # Reporte semanal: lunes 08:00
    scheduler.add_job(
        job_weekly_report,
        CronTrigger(day_of_week="mon", hour="8", minute="0", timezone=MADRID_TZ),
        id="weekly_report", name="Reporte semanal", replace_existing=True,
    )

    return scheduler


# ── arranque standalone ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    scheduler = create_scheduler()
    scheduler.start()

    print("Scheduler activo:")
    for job in scheduler.get_jobs():
        print(f"  {job.name}: {job.trigger}")

    try:
        asyncio.get_event_loop().run_forever()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
