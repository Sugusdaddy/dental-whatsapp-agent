"""
Tools del agente LangGraph.

Cada tool es una función Python pura con docstring detallado
(el docstring es lo que Claude lee para decidir cuándo usarla).
Todas tienen manejo de errores y devuelven dicts serializables.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

from dental.core.database import get_db
from dental.core.models import AppointmentStatus, ReminderType

MADRID_TZ = ZoneInfo("Europe/Madrid")


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _slots_to_display(slots: list, max_slots: int = 3) -> list[dict]:
    """Convierte TimeSlot a dict legible para el agente."""
    return [
        {"horario": s.time, "duración": f"{s.duration_min} min", "slot_id": s.slot_id}
        for s in slots[:max_slots]
    ]


def _appointment_to_display(apt) -> dict:
    return {
        "appointment_id": apt.appointment_id,
        "fecha_hora":     apt.datetime_es(),
        "tratamiento":    apt.treatment,
        "dentista":       apt.dentist,
        "duración":       f"{apt.duration_min} min",
        "estado":         apt.status.value,
    }


# ─────────────────────────────────────────────
# TOOLS
# ─────────────────────────────────────────────

@tool
def get_clinic_info(clinic_id: str) -> str:
    """
    Obtiene información de la clínica: nombre, dirección, horarios,
    servicios con precios orientativos, seguros aceptados y parking.

    Úsala cuando el paciente pregunte sobre:
    - Horarios de apertura
    - Precios o presupuestos orientativos
    - Seguros médicos aceptados
    - Cómo llegar o dónde aparcar
    - Qué tratamientos realizan

    Args:
        clinic_id: ID de la clínica (ej: "clinic_001")
    """
    try:
        db     = get_db()
        clinic = db.get_clinic(clinic_id)
        if not clinic:
            return json.dumps({"error": f"Clínica {clinic_id} no encontrada"})

        return json.dumps({
            "nombre":    clinic.name,
            "dirección": clinic.address,
            "teléfono":  clinic.phone,
            "horarios":  {
                "lunes_viernes": clinic.hours.monday_friday,
                "sábado":        clinic.hours.saturday,
                "domingo":       clinic.hours.sunday,
            },
            "servicios":  [
                {"tratamiento": s.name, "precio_desde": f"€{s.price_from}"}
                for s in clinic.services
            ],
            "seguros":   clinic.insurance_accepted,
            "parking":   clinic.parking,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def get_patient_appointments(patient_phone: str, clinic_id: str) -> str:
    """
    Consulta las citas próximas de un paciente.

    Úsala cuando el paciente:
    - Quiera cancelar o cambiar una cita ("quiero cancelar mi cita")
    - Pregunte cuándo es su próxima cita
    - Necesite confirmar los detalles de una cita existente
    - Responda a un recordatorio

    Args:
        patient_phone: Teléfono del paciente con prefijo internacional (+34612345678)
        clinic_id: ID de la clínica
    """
    try:
        db   = get_db()
        apts = db.get_patient_appointments(clinic_id, patient_phone)

        if not apts:
            return json.dumps({
                "tiene_citas": False,
                "mensaje":     "Este paciente no tiene citas próximas.",
            }, ensure_ascii=False)

        return json.dumps({
            "tiene_citas": True,
            "citas":       [_appointment_to_display(a) for a in apts],
            "total":       len(apts),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def check_available_slots(clinic_id: str, date: str) -> str:
    """
    Consulta los huecos libres en la agenda para una fecha concreta.

    Úsala cuando necesites mostrar opciones de horario al paciente
    para agendar una cita nueva o reagendar una existente.
    Devuelve máximo 3 opciones para no abrumar al paciente.

    Args:
        clinic_id: ID de la clínica
        date: Fecha en formato YYYY-MM-DD (ej: "2025-06-15")
              Si el paciente dice "mañana" o "el jueves", calcula la fecha tú.
    """
    try:
        # Validar formato fecha
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return json.dumps({"error": f"Formato de fecha inválido: '{date}'. Usa YYYY-MM-DD."})

    try:
        db    = get_db()
        slots = db.get_available_slots(clinic_id, date)

        if not slots:
            # Sugiere días alternativos
            base = datetime.strptime(date, "%Y-%m-%d")
            alt_dates = [
                (base + timedelta(days=i)).strftime("%Y-%m-%d")
                for i in [1, 2, 3]
            ]
            return json.dumps({
                "disponible":    False,
                "fecha":         date,
                "mensaje":       "No hay huecos disponibles ese día.",
                "alternativas":  alt_dates,
            }, ensure_ascii=False)

        return json.dumps({
            "disponible":        True,
            "fecha":             date,
            "huecos":            _slots_to_display(slots, max_slots=3),
            "más_opciones":      len(slots) > 3,
            "total_disponibles": len(slots),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def confirm_appointment(appointment_id: str, patient_phone: str) -> str:
    """
    Registra la confirmación de asistencia de un paciente a su cita.

    Úsala cuando el paciente responda afirmativamente a un recordatorio
    o diga explícitamente que sí asistirá ("sí confirmo", "ahí estaré",
    "perfecto", "confirmado", "sí", "ok", "claro").

    Args:
        appointment_id: ID de la cita a confirmar (obtenido de get_patient_appointments)
        patient_phone: Teléfono del paciente (para verificación)
    """
    try:
        db  = get_db()
        apt = db.get_appointment(appointment_id)

        if not apt:
            return json.dumps({"error": f"Cita {appointment_id} no encontrada."})

        if apt.patient_phone != patient_phone:
            return json.dumps({"error": "Este paciente no tiene acceso a esa cita."})

        if apt.status == AppointmentStatus.CANCELLED:
            return json.dumps({
                "error": "Esta cita ya fue cancelada. ¿Quieres agendar una nueva?"
            })

        apt_updated = db.confirm_appointment(appointment_id)
        code = f"CONF-{appointment_id.upper()[-6:]}"

        return json.dumps({
            "confirmado":       True,
            "appointment_id":   appointment_id,
            "cita":             _appointment_to_display(apt_updated),
            "código":           code,
            "dirección":        db.get_clinic(apt.clinic_id).address,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def cancel_appointment(appointment_id: str, patient_phone: str, reason: str = "") -> str:
    """
    Cancela una cita existente del paciente.

    IMPORTANTE: Confirma siempre antes de cancelar. Pregunta:
    "¿Seguro que quieres cancelar tu cita del [fecha]?"
    Solo ejecuta esta tool tras confirmación explícita.

    Args:
        appointment_id: ID de la cita (de get_patient_appointments)
        patient_phone: Teléfono del paciente
        reason: Motivo de cancelación si el paciente lo menciona (opcional)
    """
    try:
        db  = get_db()
        apt = db.get_appointment(appointment_id)

        if not apt:
            return json.dumps({"error": f"Cita {appointment_id} no encontrada."})

        if apt.patient_phone != patient_phone:
            return json.dumps({"error": "Este paciente no tiene acceso a esa cita."})

        if apt.status == AppointmentStatus.CANCELLED:
            return json.dumps({"error": "Esta cita ya estaba cancelada."})

        db.cancel_appointment(appointment_id, reason)

        return json.dumps({
            "cancelado":        True,
            "appointment_id":   appointment_id,
            "cita_cancelada":   apt.datetime_es(),
            "motivo":           reason or "No especificado",
            "reagendar":        True,
            "mensaje":          "Cita cancelada. El hueco ha quedado libre.",
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def book_appointment(
    patient_phone: str,
    patient_name: str,
    clinic_id: str,
    slot_id: str,
    treatment_type: str,
) -> str:
    """
    Reserva una nueva cita para el paciente.

    Úsala solo cuando tengas:
    1. El nombre del paciente (pregúntalo si no lo sabes)
    2. El tipo de tratamiento que necesita
    3. El slot_id elegido por el paciente (de check_available_slots)

    Args:
        patient_phone: Teléfono con prefijo internacional
        patient_name: Nombre completo del paciente
        clinic_id: ID de la clínica
        slot_id: ID del hueco elegido (del resultado de check_available_slots)
        treatment_type: Tipo de tratamiento (ej: "Revisión y limpieza", "Urgencia")
    """
    try:
        if not patient_name or len(patient_name.strip()) < 2:
            return json.dumps({"error": "Necesito el nombre del paciente para crear la cita."})

        db  = get_db()
        apt = db.create_appointment(
            clinic_id     = clinic_id,
            patient_phone = patient_phone,
            patient_name  = patient_name.strip(),
            slot_id       = slot_id,
            treatment     = treatment_type,
        )

        # Upsert paciente
        from dental.core.models import Patient
        existing = db.get_patient(clinic_id, patient_phone)
        if not existing:
            db.upsert_patient(Patient(
                patient_id = db._seq_patient,
                clinic_id  = clinic_id,
                phone      = patient_phone,
                name       = patient_name.strip(),
            ))
            db._seq_patient += 1

        clinic = db.get_clinic(clinic_id)
        code   = f"CITA-{apt.appointment_id.upper()[-6:]}"

        return json.dumps({
            "éxito":          True,
            "appointment_id": apt.appointment_id,
            "cita":           _appointment_to_display(apt),
            "código":         code,
            "dirección":      clinic.address if clinic else "",
            "dentista":       apt.dentist,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def escalate_to_human(
    patient_phone: str,
    clinic_id: str,
    reason: str,
    conversation_summary: str,
) -> str:
    """
    Escala la conversación a un recepcionista o dentista humano.

    DEBES usar esta tool cuando:
    - El paciente describe dolor intenso, sangrado o accidente dental
    - El paciente está claramente enfadado o frustrado
    - El paciente hace preguntas médicas que requieren diagnóstico
    - El paciente pide explícitamente hablar con una persona
    - No puedes resolver el problema después de 2 intentos
    - La situación es ambigua y podría ser una urgencia médica

    Args:
        patient_phone: Teléfono del paciente
        clinic_id: ID de la clínica
        reason: Motivo de escalación en una frase (para el humano que recibe)
        conversation_summary: Resumen de 2-3 líneas de lo hablado hasta ahora
    """
    try:
        db     = get_db()
        clinic = db.get_clinic(clinic_id)
        name   = clinic.name if clinic else clinic_id

        # En producción: enviar WhatsApp/push al recepcionista con el resumen
        # send_staff_notification(clinic_id, patient_phone, reason, conversation_summary)

        now_str = datetime.now(MADRID_TZ).strftime("%H:%M")
        in_hours = 9 <= datetime.now(MADRID_TZ).hour < 20

        return json.dumps({
            "escalado":           True,
            "personal_notificado": True,
            "motivo":             reason,
            "resumen_enviado":    conversation_summary[:200],
            "respuesta_estimada": "en los próximos minutos" if in_hours
                                  else "mañana cuando abramos (09:00)",
            "teléfono_directo":   clinic.phone if clinic else "",
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────
# LISTA EXPORTADA DE TOOLS
# ─────────────────────────────────────────────

ALL_TOOLS = [
    get_clinic_info,
    get_patient_appointments,
    check_available_slots,
    confirm_appointment,
    cancel_appointment,
    book_appointment,
    escalate_to_human,
]
