"""Tests del scheduler — lógica de recordatorios y reportes."""

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

MADRID_TZ = ZoneInfo("Europe/Madrid")


@pytest.fixture(autouse=True)
def reset():
    from dental.core.database import reset_db
    reset_db()


class TestReminderMessages:
    def test_reminder_48h_contains_key_info(self):
        from dental.core.models import Appointment, AppointmentStatus
        from dental.core.scheduler import build_reminder_48h

        dt = datetime(2025, 6, 10, 10, 30, tzinfo=MADRID_TZ)
        apt = Appointment(
            appointment_id="apt_t",
            clinic_id="clinic_001",
            patient_phone="+34612345678",
            patient_name="Ana García",
            appointment_datetime=dt,
            treatment="Ortodoncia",
            dentist="Dr. Pérez",
        )
        msg = build_reminder_48h(apt, "Clínica Test")
        assert "Ana" in msg
        assert "Ortodoncia" in msg
        assert "Dr. Pérez" in msg
        assert "SÍ" in msg or "NO" in msg

    def test_reminder_48h_unknown_patient(self):
        from dental.core.models import Appointment
        from dental.core.scheduler import build_reminder_48h

        dt = datetime(2025, 6, 10, 10, 30, tzinfo=MADRID_TZ)
        apt = Appointment(
            appointment_id="apt_t2",
            clinic_id="clinic_001",
            patient_phone="+34699999999",
            patient_name=None,
            appointment_datetime=dt,
            treatment="Limpieza",
            dentist="Dra. López",
        )
        msg = build_reminder_48h(apt, "Clínica Test")
        assert "paciente" in msg.lower() or len(msg) > 20

    def test_reminder_2h_contains_time(self):
        from dental.core.models import Appointment
        from dental.core.scheduler import build_reminder_2h

        dt = datetime(2025, 6, 10, 17, 30, tzinfo=MADRID_TZ)
        apt = Appointment(
            appointment_id="apt_t3",
            clinic_id="clinic_001",
            patient_phone="+34612345678",
            patient_name="Carlos",
            appointment_datetime=dt,
            treatment="Revisión",
            dentist="Dra. García",
        )
        msg = build_reminder_2h(apt, "Calle Gran Vía 45, Madrid")
        assert "17:30" in msg
        assert "Gran Vía" in msg

    def test_weekly_report_format(self):
        from dental.core.scheduler import build_weekly_report
        msg = build_weekly_report("Clínica Sonríe", 42, 3, 5, 28)
        assert "42" in msg
        assert "3" in msg
        assert "7%" in msg   # 3/42 ≈ 7%
        assert "28" in msg

    def test_weekly_report_zero_total(self):
        from dental.core.scheduler import build_weekly_report
        msg = build_weekly_report("Clínica Sonríe", 0, 0, 0, 10)
        assert "0%" in msg   # no divide por cero


class TestSchedulerJobs:
    def test_reminder_window_48h(self):
        """Citas en ventana ±1h de 48h deben aparecer."""
        from dental.core.database import get_db
        from dental.core.models import Appointment, AppointmentStatus, ReminderType

        db     = get_db()
        future = datetime.now(MADRID_TZ) + timedelta(hours=48, minutes=15)

        apt = Appointment(
            appointment_id="apt_sched",
            clinic_id="clinic_001",
            patient_phone="+34699000001",
            appointment_datetime=future,
            treatment="Test",
            dentist="Dr. Test",
            status=AppointmentStatus.CONFIRMED,
            reminder_48h_sent=False,
        )
        db.save_appointment(apt)

        pending = db.get_appointments_needing_reminder("clinic_001", ReminderType.HOURS_48)
        assert any(a.appointment_id == "apt_sched" for a in pending)

    def test_already_sent_not_duplicated(self):
        """Citas con recordatorio ya enviado no deben volver a aparecer."""
        from dental.core.database import get_db
        from dental.core.models import Appointment, AppointmentStatus, ReminderType

        db     = get_db()
        future = datetime.now(MADRID_TZ) + timedelta(hours=48, minutes=15)

        apt = Appointment(
            appointment_id="apt_sent",
            clinic_id="clinic_001",
            patient_phone="+34699000002",
            appointment_datetime=future,
            treatment="Test",
            dentist="Dr. Test",
            status=AppointmentStatus.CONFIRMED,
            reminder_48h_sent=True,   # YA ENVIADO
        )
        db.save_appointment(apt)

        pending = db.get_appointments_needing_reminder("clinic_001", ReminderType.HOURS_48)
        assert not any(a.appointment_id == "apt_sent" for a in pending)

    def test_cancelled_not_reminded(self):
        """Citas canceladas no reciben recordatorio."""
        from dental.core.database import get_db
        from dental.core.models import Appointment, AppointmentStatus, ReminderType

        db     = get_db()
        future = datetime.now(MADRID_TZ) + timedelta(hours=48, minutes=15)

        apt = Appointment(
            appointment_id="apt_canc",
            clinic_id="clinic_001",
            patient_phone="+34699000003",
            appointment_datetime=future,
            treatment="Test",
            dentist="Dr. Test",
            status=AppointmentStatus.CANCELLED,
            reminder_48h_sent=False,
        )
        db.save_appointment(apt)

        pending = db.get_appointments_needing_reminder("clinic_001", ReminderType.HOURS_48)
        assert not any(a.appointment_id == "apt_canc" for a in pending)

    def test_send_whatsapp_dev_mode(self):
        """En dev (sin API key) send_whatsapp devuelve True y no lanza excepción."""
        from dental.core.scheduler import send_whatsapp
        result = asyncio.run(send_whatsapp("+34612345678", "Hola test", "clinic_001"))
        assert result is True

    def test_scheduler_creates_3_jobs(self):
        from dental.core.scheduler import create_scheduler
        scheduler = create_scheduler()
        jobs = scheduler.get_jobs()
        job_ids = [j.id for j in jobs]
        assert "reminder_48h" in job_ids
        assert "reminder_2h"  in job_ids
        assert "weekly_report" in job_ids
        assert len(jobs) == 3

    def test_job_reminder_48h_runs(self):
        """job_reminder_48h ejecuta sin excepciones aunque no haya citas."""
        from dental.core.scheduler import job_reminder_48h
        asyncio.run(job_reminder_48h())

    def test_job_reminder_2h_runs(self):
        from dental.core.scheduler import job_reminder_2h
        asyncio.run(job_reminder_2h())

    def test_job_weekly_report_runs(self):
        from dental.core.scheduler import job_weekly_report
        asyncio.run(job_weekly_report())
