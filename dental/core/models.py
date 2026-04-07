"""
Modelos de datos del sistema dental.
Tipado estricto con Pydantic — fuente de verdad para toda la app.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, field_validator

MADRID_TZ = ZoneInfo("Europe/Madrid")


# ─────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────

class AppointmentStatus(str, Enum):
    CONFIRMED   = "confirmed"
    CANCELLED   = "cancelled"
    COMPLETED   = "completed"
    NO_SHOW     = "no_show"
    PENDING     = "pending"


class ConversationStage(str, Enum):
    GREETING     = "greeting"
    BOOKING      = "booking"
    CONFIRMING   = "confirming"
    RESCHEDULING = "rescheduling"
    FAQ          = "faq"
    ESCALATED    = "escalated"
    DONE         = "done"


class ReminderType(str, Enum):
    HOURS_48 = "48h"
    HOURS_2  = "2h"


# ─────────────────────────────────────────────
# CLÍNICA
# ─────────────────────────────────────────────

class ClinicHours(BaseModel):
    monday_friday: str = "09:00 - 20:00"
    saturday: str      = "09:00 - 14:00"
    sunday: str        = "Cerrado"


class ClinicService(BaseModel):
    name:       str
    price_from: int  # euros


class ClinicInfo(BaseModel):
    clinic_id:           str
    name:                str
    address:             str
    phone:               str
    whatsapp_number:     str
    hours:               ClinicHours
    services:            list[ClinicService]
    insurance_accepted:  list[str]
    parking:             str = ""
    active:              bool = True


# ─────────────────────────────────────────────
# PACIENTE
# ─────────────────────────────────────────────

class Patient(BaseModel):
    patient_id:   int
    clinic_id:    str
    phone:        str   # formato: +34612345678
    name:         Optional[str] = None
    email:        Optional[str] = None
    last_visit:   Optional[datetime] = None
    last_contact: Optional[datetime] = None  # último mensaje recibido vía WhatsApp

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("+"):
            raise ValueError("El teléfono debe incluir prefijo internacional (+34...)")
        digits = v[1:].replace(" ", "").replace("-", "")
        if not digits.isdigit():
            raise ValueError("El teléfono solo debe contener dígitos tras el '+'")
        if len(digits) < 8 or len(digits) > 15:
            raise ValueError("Longitud de teléfono inválida")
        return v


# ─────────────────────────────────────────────
# CITA
# ─────────────────────────────────────────────

class TimeSlot(BaseModel):
    slot_id:      str
    time:         str   # "09:00"
    duration_min: int   # minutos


class Appointment(BaseModel):
    appointment_id:       str
    clinic_id:            str
    patient_phone:        str
    patient_name:         Optional[str] = None
    appointment_datetime: datetime
    treatment:            str
    dentist:              str
    duration_min:         int = 30
    status:               AppointmentStatus = AppointmentStatus.CONFIRMED
    reminder_48h_sent:    bool = False
    reminder_2h_sent:     bool = False
    confirmation_received: bool = False

    def datetime_es(self) -> str:
        """Fecha formateada para español: 'martes 15 de abril a las 10:30'"""
        dt = self.appointment_datetime
        days   = ["lunes","martes","miércoles","jueves","viernes","sábado","domingo"]
        months = ["enero","febrero","marzo","abril","mayo","junio",
                  "julio","agosto","septiembre","octubre","noviembre","diciembre"]
        return f"{days[dt.weekday()]} {dt.day} de {months[dt.month-1]} a las {dt.strftime('%H:%M')}"


# ─────────────────────────────────────────────
# RESULTADOS DE TOOLS
# ─────────────────────────────────────────────

class SlotsResult(BaseModel):
    date:             str
    clinic_id:        str
    available_slots:  list[TimeSlot]
    total_available:  int

    @classmethod
    def from_slots(cls, date: str, clinic_id: str, slots: list[TimeSlot]) -> "SlotsResult":
        return cls(date=date, clinic_id=clinic_id,
                   available_slots=slots, total_available=len(slots))


class BookingResult(BaseModel):
    success:           bool
    appointment_id:    Optional[str] = None
    datetime_str:      Optional[str] = None
    treatment:         Optional[str] = None
    confirmation_code: Optional[str] = None
    error:             Optional[str] = None


class ConfirmResult(BaseModel):
    success:           bool
    appointment_id:    str
    confirmation_code: Optional[str] = None
    error:             Optional[str] = None


class CancelResult(BaseModel):
    success:         bool
    appointment_id:  str
    offer_reschedule: bool = True
    error:           Optional[str] = None


class EscalationResult(BaseModel):
    escalated:          bool
    notified_staff:     bool
    estimated_response: str
    error:              Optional[str] = None


# ─────────────────────────────────────────────
# MENSAJES WHATSAPP
# ─────────────────────────────────────────────

class IncomingMessage(BaseModel):
    patient_phone: str
    text:          str
    message_id:    str
    clinic_id:     str
    patient_name:  Optional[str] = None
    timestamp:     Optional[int] = None


class OutgoingMessage(BaseModel):
    to:      str   # teléfono destino
    text:    str
    clinic_id: str
