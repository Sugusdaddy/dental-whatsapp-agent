"""
Capa de datos — patrón Repository.

Implementaciones:
- MemoryDB: in-memory dict (para desarrollo y tests)
- PostgresDB: PostgreSQL real (para producción)

Si DATABASE_URL está configurado, usa PostgresDB automáticamente.
"""

from __future__ import annotations

import os
import logging
from datetime import datetime, timedelta
from typing import Optional, Protocol, Union
from zoneinfo import ZoneInfo

from dental.core.models import (
    Appointment, AppointmentStatus, ClinicHours, ClinicInfo,
    ClinicService, Patient, ReminderType, TimeSlot,
)

logger = logging.getLogger("dental.database")
MADRID_TZ = ZoneInfo("Europe/Madrid")


# ─────────────────────────────────────────────
# INTERFAZ (Protocol)
# ─────────────────────────────────────────────

class DatabaseProtocol(Protocol):
    """Interfaz que deben implementar MemoryDB y PostgresDB."""
    
    def get_clinic(self, clinic_id: str) -> Optional[ClinicInfo]: ...
    def update_clinic(self, clinic_id: str, fields: dict) -> Optional[ClinicInfo]: ...
    def get_patient(self, clinic_id: str, phone: str) -> Optional[Patient]: ...
    def upsert_patient(self, patient: Patient) -> Patient: ...
    def get_patient_appointments(self, clinic_id: str, patient_phone: str, only_upcoming: bool = True) -> list[Appointment]: ...
    def get_available_slots(self, clinic_id: str, date: str) -> list[TimeSlot]: ...
    def get_appointment(self, appointment_id: str) -> Optional[Appointment]: ...
    def save_appointment(self, apt: Appointment) -> Appointment: ...
    def confirm_appointment(self, appointment_id: str) -> Optional[Appointment]: ...
    def cancel_appointment(self, appointment_id: str, reason: str = "") -> Optional[Appointment]: ...
    def create_appointment(self, clinic_id: str, patient_phone: str, patient_name: str, slot_id: str, treatment: str) -> Appointment: ...
    def get_appointments_needing_reminder(self, clinic_id: str, reminder_type: ReminderType) -> list[Appointment]: ...
    # Human takeover (dentista pausa al agente para una conversación concreta)
    def set_human_takeover(self, clinic_id: str, phone: str, enabled: bool) -> None: ...
    def is_human_takeover(self, clinic_id: str, phone: str) -> bool: ...


# ─────────────────────────────────────────────
# BASE DE DATOS IN-MEMORY (desarrollo / tests)
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
        self._takeovers:    set[str]                 = set()  # keys "clinic_id:phone" con bot pausado
        self._seq_patient   = 1
        self._seq_apt       = 1
        self._seed()

    # ── seed con datos realistas ──────────────────

    def _seed(self):
        """Puebla la DB con datos de demo realistas para piloto y demos."""

        # ═══ CLÍNICA 1: Madrid ══════════════════
        clinic1 = ClinicInfo(
            clinic_id        = "clinic_001",
            name             = "Clínica Dental Sonríe",
            address          = "Calle Gran Vía 45, 28013 Madrid",
            phone            = "+34 91 234 56 78",
            whatsapp_number  = "+34 600 000 001",
            hours            = ClinicHours(),
            services         = [
                ClinicService(name="Revisión + limpieza",     price_from=60),
                ClinicService(name="Ortodoncia invisible",    price_from=2500),
                ClinicService(name="Implante dental",         price_from=900),
                ClinicService(name="Blanqueamiento",          price_from=250),
                ClinicService(name="Endodoncia",              price_from=180),
                ClinicService(name="Urgencia dental",         price_from=50),
            ],
            insurance_accepted = ["Adeslas", "Sanitas", "Asisa", "Mapfre"],
            parking            = "Parking público a 50m (C/ Montera)",
        )
        self._clinics["clinic_001"] = clinic1

        # ═══ CLÍNICA 2: Barcelona ═══════════════
        clinic2 = ClinicInfo(
            clinic_id        = "clinic_002",
            name             = "Centre Dental Barcelona",
            address          = "Passeig de Gràcia 92, 08008 Barcelona",
            phone            = "+34 93 215 00 00",
            whatsapp_number  = "+34 600 000 002",
            hours            = ClinicHours(),
            services         = [
                ClinicService(name="Revisión + limpieza",     price_from=70),
                ClinicService(name="Ortodoncia",              price_from=2200),
                ClinicService(name="Estética dental",         price_from=400),
                ClinicService(name="Implantología",           price_from=950),
            ],
            insurance_accepted = ["Adeslas", "DKV"],
            parking            = "Parking SABA Catalunya a 100m",
        )
        self._clinics["clinic_002"] = clinic2

        now = datetime.now(MADRID_TZ)

        # ═══ PACIENTES (12) ═════════════════════
        # Mezclamos clínicas y last_contact para que active_conversations sea > 0
        patients_seed = [
            # clinic_001
            ("clinic_001", "+34612345678", "María López",     "maria@email.com",   now - timedelta(minutes=15)),
            ("clinic_001", "+34611222333", "Carlos García",   "carlos@email.com",  now - timedelta(hours=2)),
            ("clinic_001", "+34622334455", "Ana Martínez",    "ana.m@email.com",   now - timedelta(hours=5)),
            ("clinic_001", "+34655667788", "Pedro Ruiz",      None,                 now - timedelta(hours=18)),
            ("clinic_001", "+34666778899", "Laura Sánchez",   "laura@email.com",   now - timedelta(days=2)),
            ("clinic_001", "+34677889900", "Javier Fernández", None,                None),
            ("clinic_001", "+34688990011", "Isabel Romero",   "isabel@email.com",  now - timedelta(hours=1)),
            ("clinic_001", "+34699001122", "Miguel Torres",   None,                 now - timedelta(hours=8)),
            # clinic_002
            ("clinic_002", "+34611112222", "Pol Vidal",       "pol@email.com",     now - timedelta(minutes=30)),
            ("clinic_002", "+34622223333", "Marta Puig",      "marta.p@email.com", now - timedelta(hours=3)),
            ("clinic_002", "+34633334444", "Jordi Soler",     None,                 now - timedelta(hours=20)),
            ("clinic_002", "+34644445555", "Núria Bosch",     "nuria@email.com",   None),
        ]
        for i, (cid, phone, name, email, last_contact) in enumerate(patients_seed, start=1):
            self.upsert_patient(Patient(
                patient_id   = i,
                clinic_id    = cid,
                phone        = phone,
                name         = name,
                email        = email,
                last_contact = last_contact,
            ))
        self._seq_patient = len(patients_seed) + 1

        # ═══ CITAS (18) ═════════════════════════
        # Mezcla de pasadas, hoy y futuras + variedad de estados
        def _at(days: int, hour: int, minute: int = 0) -> datetime:
            base = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return base + timedelta(days=days)

        apts_seed = [
            # ── clinic_001 ──
            # Pasadas (completadas, canceladas, no-shows)
            ("clinic_001", "+34612345678", "María López",     -7, 10, 30, "Revisión + limpieza", "Dra. García",   45, AppointmentStatus.COMPLETED),
            ("clinic_001", "+34611222333", "Carlos García",   -5, 17,  0, "Endodoncia",          "Dr. Martín",    60, AppointmentStatus.COMPLETED),
            ("clinic_001", "+34622334455", "Ana Martínez",    -4, 11, 30, "Limpieza",            "Dra. García",   30, AppointmentStatus.NO_SHOW),
            ("clinic_001", "+34666778899", "Laura Sánchez",   -3, 16,  0, "Blanqueamiento",      "Dra. Ruiz",     90, AppointmentStatus.CANCELLED),
            ("clinic_001", "+34655667788", "Pedro Ruiz",      -2,  9,  0, "Implante (revisión)", "Dr. Martín",    30, AppointmentStatus.COMPLETED),
            # Hoy
            ("clinic_001", "+34612345678", "María López",      0, 16,  0, "Limpieza",            "Dra. García",   30, AppointmentStatus.CONFIRMED),
            ("clinic_001", "+34688990011", "Isabel Romero",    0, 17, 30, "Urgencia: dolor",     "Dr. Martín",    30, AppointmentStatus.PENDING),
            ("clinic_001", "+34699001122", "Miguel Torres",    0, 18, 30, "Revisión",            "Dra. García",   30, AppointmentStatus.CONFIRMED),
            # Próximas
            ("clinic_001", "+34611222333", "Carlos García",    1, 10,  0, "Empaste",             "Dr. Martín",    45, AppointmentStatus.CONFIRMED),
            ("clinic_001", "+34622334455", "Ana Martínez",     2, 11, 30, "Revisión",            "Dra. García",   30, AppointmentStatus.CONFIRMED),
            ("clinic_001", "+34666778899", "Laura Sánchez",    3, 17,  0, "Ortodoncia",          "Dra. Ruiz",     45, AppointmentStatus.CONFIRMED),
            ("clinic_001", "+34655667788", "Pedro Ruiz",       5, 16, 30, "Limpieza",            "Dra. García",   30, AppointmentStatus.PENDING),
            ("clinic_001", "+34677889900", "Javier Fernández", 7, 12,  0, "Primera consulta",    "Dr. Martín",    45, AppointmentStatus.CONFIRMED),
            # ── clinic_002 ──
            ("clinic_002", "+34611112222", "Pol Vidal",       -3, 10,  0, "Revisió",             "Dr. Vila",      30, AppointmentStatus.COMPLETED),
            ("clinic_002", "+34622223333", "Marta Puig",      -1, 16,  0, "Ortodòncia",          "Dra. Roca",     45, AppointmentStatus.CANCELLED),
            ("clinic_002", "+34611112222", "Pol Vidal",        0, 17,  0, "Empastament",         "Dr. Vila",      45, AppointmentStatus.CONFIRMED),
            ("clinic_002", "+34633334444", "Jordi Soler",      2, 11,  0, "Implant",             "Dra. Roca",     60, AppointmentStatus.CONFIRMED),
            ("clinic_002", "+34644445555", "Núria Bosch",      4, 18,  0, "Estètica",            "Dr. Vila",      90, AppointmentStatus.PENDING),
        ]

        for i, (cid, phone, name, days, h, m, treatment, dentist, dur, status) in enumerate(apts_seed, start=1):
            self.save_appointment(Appointment(
                appointment_id       = f"apt_{i:03d}",
                clinic_id            = cid,
                patient_phone        = phone,
                patient_name         = name,
                appointment_datetime = _at(days, h, m),
                treatment            = treatment,
                dentist              = dentist,
                duration_min         = dur,
                status               = status,
                confirmation_received = (status == AppointmentStatus.CONFIRMED and days >= 0),
            ))
        self._seq_apt = len(apts_seed) + 1

    # ── clinics ───────────────────────────────────

    def get_clinic(self, clinic_id: str) -> Optional[ClinicInfo]:
        return self._clinics.get(clinic_id)

    def list_clinics(self) -> list[ClinicInfo]:
        """Lista todas las clínicas."""
        return list(self._clinics.values())

    def list_all_appointments(self) -> list[Appointment]:
        """Lista todas las citas de todas las clínicas."""
        return list(self._appointments.values())

    def count_patients_by_clinic(self, clinic_id: str) -> int:
        """Cuenta pacientes de una clínica."""
        return sum(1 for p in self._patients.values() if p.clinic_id == clinic_id)

    def update_clinic(self, clinic_id: str, fields: dict) -> Optional[ClinicInfo]:
        """Actualiza campos editables de la clínica. Devuelve la versión nueva."""
        clinic = self._clinics.get(clinic_id)
        if not clinic:
            return None
        # Solo permitimos editar campos seguros desde el dashboard
        EDITABLE = {"name", "address", "phone", "whatsapp_number"}
        data = clinic.model_dump()
        for k, v in fields.items():
            if k in EDITABLE and v is not None:
                data[k] = v
        updated = ClinicInfo(**data)
        self._clinics[clinic_id] = updated
        return updated

    # ── human takeover ────────────────────────────

    def set_human_takeover(self, clinic_id: str, phone: str, enabled: bool) -> None:
        key = f"{clinic_id}:{phone}"
        if enabled:
            self._takeovers.add(key)
        else:
            self._takeovers.discard(key)

    def is_human_takeover(self, clinic_id: str, phone: str) -> bool:
        return f"{clinic_id}:{phone}" in self._takeovers

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


# ─────────────────────────────────────────────
# BASE DE DATOS POSTGRESQL (producción)
# ─────────────────────────────────────────────

class PostgresDB:
    """
    Implementación PostgreSQL con la misma interfaz que MemoryDB.

    Usa psycopg (sync) con un pool de conexiones para soportar
    múltiples requests concurrentes en FastAPI sin abrir/cerrar
    socket en cada query.

    Nota: el spec original pedía asyncpg. Mantenemos psycopg sync
    porque el resto del código (agent, scheduler, tools) es sync;
    migrar a asyncpg requeriría refactor de toda la pila. Para el
    piloto y los primeros 100 clientes psycopg + pool es suficiente.
    """

    def __init__(self, database_url: str, *, pool_min: int = 2, pool_max: int = 10):
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        self.database_url = database_url
        self._pool = ConnectionPool(
            conninfo=database_url,
            min_size=pool_min,
            max_size=pool_max,
            kwargs={"row_factory": dict_row, "autocommit": True},
            open=True,
        )
        self._takeover_table_ready = False
        self._ensure_takeover_table()
        logger.info("PostgreSQL conectado (pool %d-%d)", pool_min, pool_max)

    def _ensure_takeover_table(self) -> None:
        """Crea la tabla human_takeovers si no existe (idempotente)."""
        try:
            self._execute("""
                CREATE TABLE IF NOT EXISTS human_takeovers (
                    clinic_id      VARCHAR(50)  NOT NULL,
                    patient_phone  VARCHAR(20)  NOT NULL,
                    enabled        BOOLEAN      NOT NULL DEFAULT true,
                    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (clinic_id, patient_phone)
                )
            """)
            self._takeover_table_ready = True
        except Exception as e:  # pragma: no cover
            logger.warning("No se pudo crear human_takeovers: %s", e)

    def _execute(self, query: str, params: tuple = ()) -> list[dict]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                if cur.description:
                    return cur.fetchall()
                return []

    def _execute_one(self, query: str, params: tuple = ()) -> Optional[dict]:
        rows = self._execute(query, params)
        return rows[0] if rows else None

    # ── clinics ───────────────────────────────────

    def get_clinic(self, clinic_id: str) -> Optional[ClinicInfo]:
        # En el schema la PK es `id`, no `clinic_id`
        row = self._execute_one(
            "SELECT * FROM clinics WHERE id = %s AND active = true",
            (clinic_id,)
        )
        if not row:
            return None
        
        # Obtener servicios
        services = self._execute(
            "SELECT name, price_from FROM clinic_services WHERE clinic_id = %s AND active = true",
            (clinic_id,)
        )
        
        return ClinicInfo(
            clinic_id=row["id"],
            name=row["name"],
            address=row["address"],
            phone=row["phone"],
            whatsapp_number=row["whatsapp_number"],
            hours=ClinicHours(
                monday_friday=row.get("hours_lv") or "09:00 - 20:00",
                saturday=row.get("hours_sat") or "09:00 - 14:00",
            ),
            services=[
                ClinicService(name=s["name"], price_from=s["price_from"])
                for s in services
            ],
            insurance_accepted=row.get("insurance") or [],
            parking=row.get("parking") or "",
        )

    def list_clinics(self) -> list[ClinicInfo]:
        """Lista todas las clínicas activas."""
        rows = self._execute("SELECT id FROM clinics WHERE active = true", ())
        return [self.get_clinic(row["id"]) for row in rows if row]

    def list_all_appointments(self) -> list[Appointment]:
        """Lista todas las citas de todas las clínicas."""
        rows = self._execute(
            """SELECT id, clinic_id, patient_phone, appointment_datetime, treatment,
                      dentist, duration_minutes, status, reminder_48h_sent, reminder_2h_sent,
                      confirmation_received, cancellation_reason
               FROM appointments ORDER BY appointment_datetime DESC""",
            ()
        )
        return [
            Appointment(
                appointment_id=row["id"],
                clinic_id=row["clinic_id"],
                patient_phone=row["patient_phone"],
                patient_name="",  # No guardamos nombre en appointments
                appointment_datetime=row["appointment_datetime"],
                treatment=row["treatment"],
                dentist=row.get("dentist") or "Sin asignar",
                duration_minutes=row.get("duration_minutes") or 30,
                status=AppointmentStatus(row["status"]),
                reminder_48h_sent=row.get("reminder_48h_sent") or False,
                reminder_2h_sent=row.get("reminder_2h_sent") or False,
                confirmation_received=row.get("confirmation_received") or False,
                cancellation_reason=row.get("cancellation_reason"),
            )
            for row in rows
        ]

    def count_patients_by_clinic(self, clinic_id: str) -> int:
        """Cuenta pacientes de una clínica."""
        row = self._execute_one(
            "SELECT COUNT(*) as cnt FROM patients WHERE clinic_id = %s",
            (clinic_id,)
        )
        return row["cnt"] if row else 0

    def update_clinic(self, clinic_id: str, fields: dict) -> Optional[ClinicInfo]:
        """Actualiza campos editables. Devuelve la versión nueva."""
        EDITABLE = {"name", "address", "phone", "whatsapp_number"}
        sets = []
        params: list = []
        for k, v in fields.items():
            if k in EDITABLE and v is not None:
                sets.append(f"{k} = %s")
                params.append(v)
        if not sets:
            return self.get_clinic(clinic_id)
        params.append(clinic_id)
        self._execute(
            f"UPDATE clinics SET {', '.join(sets)}, updated_at = NOW() WHERE id = %s",
            tuple(params),
        )
        return self.get_clinic(clinic_id)

    # ── human takeover ────────────────────────────

    def set_human_takeover(self, clinic_id: str, phone: str, enabled: bool) -> None:
        if enabled:
            self._execute("""
                INSERT INTO human_takeovers (clinic_id, patient_phone, enabled, updated_at)
                VALUES (%s, %s, true, NOW())
                ON CONFLICT (clinic_id, patient_phone) DO UPDATE
                  SET enabled = true, updated_at = NOW()
            """, (clinic_id, phone))
        else:
            self._execute(
                "DELETE FROM human_takeovers WHERE clinic_id = %s AND patient_phone = %s",
                (clinic_id, phone),
            )

    def is_human_takeover(self, clinic_id: str, phone: str) -> bool:
        row = self._execute_one(
            "SELECT enabled FROM human_takeovers WHERE clinic_id = %s AND patient_phone = %s",
            (clinic_id, phone),
        )
        return bool(row and row.get("enabled"))

    # ── patients ──────────────────────────────────

    def get_patient(self, clinic_id: str, phone: str) -> Optional[Patient]:
        row = self._execute_one(
            "SELECT * FROM patients WHERE clinic_id = %s AND phone = %s",
            (clinic_id, phone)
        )
        if not row:
            return None
        return Patient(
            patient_id=row["id"],
            clinic_id=row["clinic_id"],
            phone=row["phone"],
            name=row.get("name"),
            email=row.get("email"),
        )

    def upsert_patient(self, patient: Patient) -> Patient:
        row = self._execute_one("""
            INSERT INTO patients (clinic_id, phone, name, email)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (clinic_id, phone) DO UPDATE SET
                name = COALESCE(EXCLUDED.name, patients.name),
                email = COALESCE(EXCLUDED.email, patients.email),
                updated_at = NOW()
            RETURNING *
        """, (patient.clinic_id, patient.phone, patient.name, patient.email))
        
        patient.patient_id = row["id"]
        return patient

    # ── appointments ──────────────────────────────

    def save_appointment(self, apt: Appointment) -> Appointment:
        self._execute("""
            INSERT INTO appointments (
                appointment_id, clinic_id, patient_phone, patient_name,
                appointment_datetime, treatment, dentist, duration_min,
                status, confirmation_received, reminder_48h_sent, reminder_2h_sent
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (appointment_id) DO UPDATE SET
                status = EXCLUDED.status,
                confirmation_received = EXCLUDED.confirmation_received,
                reminder_48h_sent = EXCLUDED.reminder_48h_sent,
                reminder_2h_sent = EXCLUDED.reminder_2h_sent,
                updated_at = NOW()
        """, (
            apt.appointment_id, apt.clinic_id, apt.patient_phone, apt.patient_name,
            apt.appointment_datetime, apt.treatment, apt.dentist, apt.duration_min,
            apt.status.value, apt.confirmation_received, apt.reminder_48h_sent, apt.reminder_2h_sent
        ))
        return apt

    def get_appointment(self, appointment_id: str) -> Optional[Appointment]:
        row = self._execute_one(
            "SELECT * FROM appointments WHERE appointment_id = %s",
            (appointment_id,)
        )
        return self._row_to_appointment(row) if row else None

    def _row_to_appointment(self, row: dict) -> Appointment:
        return Appointment(
            appointment_id=row["appointment_id"],
            clinic_id=row["clinic_id"],
            patient_phone=row["patient_phone"],
            patient_name=row.get("patient_name"),
            appointment_datetime=row["appointment_datetime"].replace(tzinfo=MADRID_TZ),
            treatment=row["treatment"],
            dentist=row.get("dentist"),
            duration_min=row.get("duration_min", 30),
            status=AppointmentStatus(row["status"]),
            confirmation_received=row.get("confirmation_received", False),
            reminder_48h_sent=row.get("reminder_48h_sent", False),
            reminder_2h_sent=row.get("reminder_2h_sent", False),
        )

    def get_patient_appointments(
        self,
        clinic_id: str,
        patient_phone: str,
        only_upcoming: bool = True,
    ) -> list[Appointment]:
        if only_upcoming:
            rows = self._execute("""
                SELECT * FROM appointments
                WHERE clinic_id = %s AND patient_phone = %s
                AND status NOT IN ('cancelled', 'no_show')
                AND appointment_datetime > NOW()
                ORDER BY appointment_datetime
            """, (clinic_id, patient_phone))
        else:
            rows = self._execute("""
                SELECT * FROM appointments
                WHERE clinic_id = %s AND patient_phone = %s
                ORDER BY appointment_datetime DESC
            """, (clinic_id, patient_phone))
        
        return [self._row_to_appointment(r) for r in rows]

    def get_appointments_needing_reminder(
        self,
        clinic_id: str,
        reminder_type: ReminderType,
    ) -> list[Appointment]:
        hours = 48 if reminder_type == ReminderType.HOURS_48 else 2
        sent_column = "reminder_48h_sent" if reminder_type == ReminderType.HOURS_48 else "reminder_2h_sent"
        
        rows = self._execute(f"""
            SELECT * FROM appointments
            WHERE clinic_id = %s
            AND status = 'confirmed'
            AND {sent_column} = false
            AND appointment_datetime BETWEEN NOW() + INTERVAL '%s hours' - INTERVAL '1 hour'
                                         AND NOW() + INTERVAL '%s hours' + INTERVAL '1 hour'
        """, (clinic_id, hours, hours))
        
        return [self._row_to_appointment(r) for r in rows]

    def get_available_slots(self, clinic_id: str, date: str) -> list[TimeSlot]:
        # Obtener slots ocupados
        occupied = self._execute("""
            SELECT TO_CHAR(appointment_datetime, 'HH24:MI') as time
            FROM appointments
            WHERE clinic_id = %s
            AND DATE(appointment_datetime) = %s
            AND status = 'confirmed'
        """, (clinic_id, date))
        
        occupied_times = {r["time"] for r in occupied}
        
        # Slots base (en producción: tabla clinic_slots o Google Calendar)
        base_slots = [
            ("09:00", 30), ("09:30", 30), ("10:00", 45), ("10:30", 45),
            ("11:00", 30), ("11:30", 30), ("12:00", 30),
            ("16:00", 45), ("16:30", 45), ("17:00", 30),
            ("17:30", 30), ("18:00", 45), ("18:30", 30),
        ]
        
        return [
            TimeSlot(
                slot_id=f"slot_{clinic_id}_{date}_{t.replace(':','')}",
                time=t,
                duration_min=dur,
            )
            for t, dur in base_slots
            if t not in occupied_times
        ]

    def confirm_appointment(self, appointment_id: str) -> Optional[Appointment]:
        self._execute("""
            UPDATE appointments
            SET confirmation_received = true, reminder_48h_sent = true, updated_at = NOW()
            WHERE appointment_id = %s
        """, (appointment_id,))
        return self.get_appointment(appointment_id)

    def cancel_appointment(self, appointment_id: str, reason: str = "") -> Optional[Appointment]:
        self._execute("""
            UPDATE appointments
            SET status = 'cancelled', updated_at = NOW()
            WHERE appointment_id = %s
        """, (appointment_id,))
        return self.get_appointment(appointment_id)

    def create_appointment(
        self,
        clinic_id: str,
        patient_phone: str,
        patient_name: str,
        slot_id: str,
        treatment: str,
    ) -> Appointment:
        # Parsea slot_id: slot_clinic_001_2025-04-10_0930
        parts = slot_id.split("_")
        date_part = parts[-2]
        time_part = parts[-1]
        time_fmt = f"{time_part[:2]}:{time_part[2:]}"
        dt_str = f"{date_part} {time_fmt}"
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M").replace(tzinfo=MADRID_TZ)

        # Generar ID
        row = self._execute_one("SELECT COUNT(*) + 1 as seq FROM appointments WHERE clinic_id = %s", (clinic_id,))
        apt_id = f"apt_{row['seq']:04d}"

        apt = Appointment(
            appointment_id=apt_id,
            clinic_id=clinic_id,
            patient_phone=patient_phone,
            patient_name=patient_name,
            appointment_datetime=dt,
            treatment=treatment,
            dentist="Dra. García",
            duration_min=30,
            status=AppointmentStatus.CONFIRMED,
        )
        return self.save_appointment(apt)


# ─────────────────────────────────────────────
# FACTORY — elige DB según entorno
# ─────────────────────────────────────────────

_db: Optional[Union[MemoryDB, PostgresDB]] = None


def get_db() -> Union[MemoryDB, PostgresDB]:
    """
    Devuelve la instancia de DB apropiada.
    - Si DATABASE_URL está configurado → PostgresDB
    - Si no → MemoryDB (desarrollo/tests)
    """
    global _db
    if _db is None:
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            logger.info("Usando PostgreSQL")
            _db = PostgresDB(database_url)
        else:
            logger.info("Usando MemoryDB (desarrollo)")
            _db = MemoryDB()
    return _db


def reset_db() -> Union[MemoryDB, PostgresDB]:
    """Solo para tests — reinicia la DB limpia."""
    global _db
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        _db = PostgresDB(database_url)
    else:
        _db = MemoryDB()
    return _db
