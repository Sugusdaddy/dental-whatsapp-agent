"""
Capa de datos — patrón Repository.

En MVP: in-memory dict (suficiente para piloto con 1-3 clínicas).
En producción: sustituye MemoryDB por PostgresDB sin tocar el agente.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from dental.core.models import (
    Appointment, AppointmentStatus, ClinicHours, ClinicInfo,
    ClinicService, Patient, ReminderType, TimeSlot,
)

MADRID_TZ = ZoneInfo("Europe/Madrid")


# ─────────────────────────────────────────────
# BASE DE DATOS IN-MEMORY (MVP / tests)
# ─────────────────────────────────────────────

class MemoryDB:
    """
    Almacén in-memory con la misma interfaz que usaría PostgresDB.
    thread-safe para uso en FastAPI (single-process dev).
    """

    def __init__(self):
        self._clinics:      dict[str, ClinicInfo]   = {}
        self._patients:     dict[str, Patient]       = {}   # key: "clinic_id:phone"
        self._appointments: dict[str, Appointment]   = {}   # key: appointment_id
        self._seq_patient   = 1
        self._seq_apt       = 1
        self._seed()

    # ── seed con datos realistas ──────────────────

    def _seed(self):
        """Puebla la DB con datos de demo para tests y piloto."""

        clinic = ClinicInfo(
            clinic_id        = "clinic_001",
            name             = "Clínica Dental Sonríe",
            address          = "Calle Gran Vía 45, 28013 Madrid",
            phone            = "+34 91 234 56 78",
            whatsapp_number  = "+34 600 000 001",
            hours            = ClinicHours(),
            services         = [
                ClinicService(name="Revisión + limpieza",     price_from=60),
                ClinicService(name="Ortodoncia invisible",     price_from=2500),
                ClinicService(name="Implante dental",          price_from=900),
                ClinicService(name="Blanqueamiento",           price_from=250),
                ClinicService(name="Endodoncia",               price_from=180),
                ClinicService(name="Urgencia dental",          price_from=50),
            ],
            insurance_accepted = ["Adeslas", "Sanitas", "Asisa", "Mapfre"],
            parking            = "Parking público a 50m (C/ Montera)",
        )
        self._clinics["clinic_001"] = clinic

        # Paciente de demo
        self.upsert_patient(Patient(
            patient_id = 1,
            clinic_id  = "clinic_001",
            phone      = "+34612345678",
            name       = "María López",
            email      = "maria@email.com",
        ))

        # Cita de demo (pasado mañana a las 10:30)
        appt_dt = datetime.now(MADRID_TZ).replace(
            hour=10, minute=30, second=0, microsecond=0
        ) + timedelta(days=2)

        self.save_appointment(Appointment(
            appointment_id       = "apt_001",
            clinic_id            = "clinic_001",
            patient_phone        = "+34612345678",
            patient_name         = "María López",
            appointment_datetime = appt_dt,
            treatment            = "Revisión y limpieza",
            dentist              = "Dra. García",
            duration_min         = 45,
            status               = AppointmentStatus.CONFIRMED,
        ))

    # ── clinics ───────────────────────────────────

    def get_clinic(self, clinic_id: str) -> Optional[ClinicInfo]:
        return self._clinics.get(clinic_id)

    # ── patients ──────────────────────────────────

    def upsert_patient(self, patient: Patient) -> Patient:
        key = f"{patient.clinic_id}:{patient.phone}"
        self._patients[key] = patient
        return patient

    def get_patient(self, clinic_id: str, phone: str) -> Optional[Patient]:
        return self._patients.get(f"{clinic_id}:{phone}")

    # ── appointments ──────────────────────────────

    def save_appointment(self, apt: Appointment) -> Appointment:
        self._appointments[apt.appointment_id] = apt
        return apt

    def get_appointment(self, appointment_id: str) -> Optional[Appointment]:
        return self._appointments.get(appointment_id)

    def get_patient_appointments(
        self,
        clinic_id: str,
        patient_phone: str,
        only_upcoming: bool = True,
    ) -> list[Appointment]:
        now = datetime.now(MADRID_TZ)
        return [
            a for a in self._appointments.values()
            if a.clinic_id == clinic_id
            and a.patient_phone == patient_phone
            and a.status not in (AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW)
            and (not only_upcoming or a.appointment_datetime > now)
        ]

    def get_appointments_needing_reminder(
        self,
        clinic_id: str,
        reminder_type: ReminderType,
    ) -> list[Appointment]:
        """Citas que necesitan recordatorio en la ventana de tiempo correcta."""
        now = datetime.now(MADRID_TZ)
        hours = 48 if reminder_type == ReminderType.HOURS_48 else 2
        window_start = now + timedelta(hours=hours - 1)
        window_end   = now + timedelta(hours=hours + 1)

        sent_attr = "reminder_48h_sent" if reminder_type == ReminderType.HOURS_48 \
                    else "reminder_2h_sent"

        return [
            a for a in self._appointments.values()
            if a.clinic_id == clinic_id
            and a.status == AppointmentStatus.CONFIRMED
            and not getattr(a, sent_attr)
            and window_start <= a.appointment_datetime <= window_end
        ]

    def get_available_slots(self, clinic_id: str, date: str) -> list[TimeSlot]:
        """
        Devuelve huecos libres para una fecha.
        En producción: consulta Doctoralia API o Google Calendar.
        Aquí generamos slots realistas excluyendo los ya ocupados.
        """
        # Slots base de la clínica
        base_slots = [
            ("09:00", 30), ("09:30", 30), ("10:00", 45), ("10:30", 45),
            ("11:00", 30), ("11:30", 30), ("12:00", 30),
            ("16:00", 45), ("16:30", 45), ("17:00", 30),
            ("17:30", 30), ("18:00", 45), ("18:30", 30),
        ]

        # Excluir huecos ya ocupados ese día
        occupied_times = set()
        for apt in self._appointments.values():
            if (apt.clinic_id == clinic_id
                    and apt.appointment_datetime.strftime("%Y-%m-%d") == date
                    and apt.status == AppointmentStatus.CONFIRMED):
                occupied_times.add(apt.appointment_datetime.strftime("%H:%M"))

        return [
            TimeSlot(
                slot_id      = f"slot_{clinic_id}_{date}_{t.replace(':','')}",
                time         = t,
                duration_min = dur,
            )
            for t, dur in base_slots
            if t not in occupied_times
        ]

    def confirm_appointment(self, appointment_id: str) -> Optional[Appointment]:
        apt = self._appointments.get(appointment_id)
        if not apt:
            return None
        apt.confirmation_received = True
        apt.reminder_48h_sent     = True
        return apt

    def cancel_appointment(
        self,
        appointment_id: str,
        reason: str = "",
    ) -> Optional[Appointment]:
        apt = self._appointments.get(appointment_id)
        if not apt:
            return None
        apt.status = AppointmentStatus.CANCELLED
        return apt

    def create_appointment(
        self,
        clinic_id:    str,
        patient_phone: str,
        patient_name:  str,
        slot_id:       str,
        treatment:     str,
    ) -> Appointment:
        # Parsea slot_id: slot_clinic_001_2025-04-10_0930
        parts     = slot_id.split("_")
        date_part = parts[-2]   # "2025-04-10"
        time_part = parts[-1]   # "0930"
        time_fmt  = f"{time_part[:2]}:{time_part[2:]}"
        dt_str    = f"{date_part} {time_fmt}"
        dt        = datetime.strptime(dt_str, "%Y-%m-%d %H:%M").replace(tzinfo=MADRID_TZ)

        apt_id = f"apt_{self._seq_apt:04d}"
        self._seq_apt += 1

        apt = Appointment(
            appointment_id       = apt_id,
            clinic_id            = clinic_id,
            patient_phone        = patient_phone,
            patient_name         = patient_name,
            appointment_datetime = dt,
            treatment            = treatment,
            dentist              = "Dra. García",   # en prod: asignación dinámica
            duration_min         = 30,
            status               = AppointmentStatus.CONFIRMED,
        )
        return self.save_appointment(apt)


# ── singleton global ──────────────────────────────────────────────────────────
_db: Optional[MemoryDB] = None

def get_db() -> MemoryDB:
    global _db
    if _db is None:
        _db = MemoryDB()
    return _db


def reset_db() -> MemoryDB:
    """Solo para tests — reinicia la DB limpia."""
    global _db
    _db = MemoryDB()
    return _db
