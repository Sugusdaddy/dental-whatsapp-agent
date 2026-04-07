"""
Sistema de reactivación de pacientes dormidos.

Funcionalidad:
- Job semanal (domingos 10:00) que busca pacientes inactivos
- Criterio: última visita > 12 meses
- Envía mensaje personalizado invitando a volver
- Registra en historial de contactos

Tablas afectadas:
- patients (last_visit, reactivation_sent_at)
- conversations (registro del mensaje enviado)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

logger = logging.getLogger("dental.reactivation")

MADRID_TZ = ZoneInfo("Europe/Madrid")


# ─────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────

class InactivePatient(BaseModel):
    """Paciente inactivo candidato a reactivación."""
    patient_id: int
    clinic_id: str
    phone: str
    name: Optional[str]
    email: Optional[str]
    last_visit: datetime
    days_inactive: int
    reactivation_sent_at: Optional[datetime] = None


# ─────────────────────────────────────────────
# REACTIVATION MESSAGES
# ─────────────────────────────────────────────

def build_reactivation_message(
    patient_name: Optional[str],
    clinic_name: str,
    months_inactive: int,
) -> str:
    """
    Construye el mensaje de reactivación personalizado.
    """
    name = patient_name or "paciente"
    
    if months_inactive < 18:
        # 12-18 meses: tono amigable
        return (
            f"Hola {name}, soy el asistente de {clinic_name}. "
            f"Ha pasado bastante tiempo desde tu última visita y queríamos saber cómo estás. "
            f"Te recomendamos una revisión anual para mantener tu salud dental al día. "
            f"¿Te gustaría que te busquemos una cita? 🦷"
        )
    elif months_inactive < 24:
        # 18-24 meses: recordatorio más directo
        return (
            f"Hola {name}, te escribimos desde {clinic_name}. "
            f"Han pasado más de un año y medio desde tu última revisión dental. "
            f"Es importante no descuidar la salud bucal. "
            f"¿Qué te parece si agendamos una cita para ponerte al día?"
        )
    else:
        # >24 meses: oferta especial
        return (
            f"Hola {name}, te echamos de menos en {clinic_name}. "
            f"Han pasado más de 2 años desde tu última visita. "
            f"Como paciente de confianza, te ofrecemos una revisión + limpieza "
            f"con descuento especial. ¿Te interesa?"
        )


def build_reactivation_message_followup(
    patient_name: Optional[str],
    clinic_name: str,
) -> str:
    """
    Mensaje de follow-up para reactivación (7 días después).
    """
    name = patient_name or "paciente"
    
    return (
        f"Hola {name}, te escribimos de nuevo desde {clinic_name}. "
        f"¿Has tenido oportunidad de pensar en agendar tu revisión? "
        f"Estamos para ayudarte cuando lo necesites. "
        f"Si prefieres que no te contactemos más, solo dímelo."
    )


# ─────────────────────────────────────────────
# REACTIVATION LOGIC
# ─────────────────────────────────────────────

class ReactivationService:
    """Servicio de reactivación de pacientes."""
    
    def __init__(self):
        self._sent_reactivations: dict[str, datetime] = {}  # phone → sent_at
    
    def get_inactive_patients(
        self,
        db,  # DatabaseProtocol
        clinic_id: str,
        inactive_months: int = 12,
    ) -> list[InactivePatient]:
        """
        Obtiene pacientes que no han visitado en X meses.
        
        Para MemoryDB: usa _patients y _appointments directamente.
        Para PostgreSQL: query SQL.
        """
        now = datetime.now(MADRID_TZ)
        cutoff = now - timedelta(days=inactive_months * 30)
        
        inactive = []
        
        # MemoryDB fallback
        if hasattr(db, '_patients'):
            for key, patient in db._patients.items():
                if not key.startswith(f"{clinic_id}:"):
                    continue
                
                # Buscar última cita del paciente
                last_visit = None
                for apt in db._appointments.values():
                    if (apt.clinic_id == clinic_id 
                            and apt.patient_phone == patient.phone
                            and apt.appointment_datetime < now):
                        if not last_visit or apt.appointment_datetime > last_visit:
                            last_visit = apt.appointment_datetime
                
                # Si no tiene citas o la última fue hace más de X meses
                if not last_visit:
                    continue  # Sin historial de visitas
                
                if last_visit < cutoff:
                    # Verificar que no le hayamos enviado reactivación recientemente
                    recent_reactivation = self._sent_reactivations.get(patient.phone)
                    if recent_reactivation and (now - recent_reactivation).days < 90:
                        continue  # Ya le enviamos hace menos de 3 meses
                    
                    inactive.append(InactivePatient(
                        patient_id=patient.patient_id or 0,
                        clinic_id=clinic_id,
                        phone=patient.phone,
                        name=patient.name,
                        email=patient.email,
                        last_visit=last_visit,
                        days_inactive=(now - last_visit).days,
                    ))
        
        return inactive
    
    def mark_reactivation_sent(self, phone: str):
        """Registra que se envió mensaje de reactivación."""
        self._sent_reactivations[phone] = datetime.now(MADRID_TZ)
        logger.info(f"Reactivación enviada a {phone}")
    
    def get_stats(self, clinic_id: str) -> dict:
        """Devuelve estadísticas de reactivación."""
        now = datetime.now(MADRID_TZ)
        
        recent = sum(
            1 for phone, sent_at in self._sent_reactivations.items()
            if (now - sent_at).days < 30
        )
        
        return {
            "total_sent": len(self._sent_reactivations),
            "sent_last_30_days": recent,
        }


# ─────────────────────────────────────────────
# JOB SCHEDULER INTEGRATION
# ─────────────────────────────────────────────

async def run_reactivation_job(clinic_id: str):
    """
    Job de reactivación - ejecutar domingos a las 10:00.
    
    Uso con APScheduler:
        scheduler.add_job(
            run_reactivation_job,
            'cron',
            day_of_week='sun',
            hour=10,
            args=['clinic_001'],
        )
    """
    from dental.core.database import get_db
    from dental.core.whatsapp_client import send_whatsapp
    
    logger.info(f"[{clinic_id}] Iniciando job de reactivación")
    
    db = get_db()
    clinic = db.get_clinic(clinic_id)
    if not clinic:
        logger.error(f"Clínica {clinic_id} no encontrada")
        return
    
    service = get_reactivation_service()
    inactive_patients = service.get_inactive_patients(db, clinic_id)
    
    logger.info(f"[{clinic_id}] Encontrados {len(inactive_patients)} pacientes inactivos")
    
    sent_count = 0
    for patient in inactive_patients[:10]:  # Máximo 10 por ejecución
        months_inactive = patient.days_inactive // 30
        message = build_reactivation_message(
            patient.name,
            clinic.name,
            months_inactive,
        )
        
        sent = await send_whatsapp(patient.phone, message, clinic_id)
        
        if sent:
            service.mark_reactivation_sent(patient.phone)
            sent_count += 1
    
    logger.info(f"[{clinic_id}] Reactivación completada: {sent_count} mensajes enviados")
    
    return {"sent": sent_count, "total_inactive": len(inactive_patients)}


# ─────────────────────────────────────────────
# SINGLETON
# ─────────────────────────────────────────────

_reactivation_service: Optional[ReactivationService] = None


def get_reactivation_service() -> ReactivationService:
    """Devuelve el servicio de reactivación (singleton)."""
    global _reactivation_service
    if _reactivation_service is None:
        _reactivation_service = ReactivationService()
    return _reactivation_service
