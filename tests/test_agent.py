"""
Tests del agente dental.

Nivel 1 — Tests unitarios: modelos, DB, tools (sin LLM)
Nivel 2 — Tests de integración: agente real con Claude API
Nivel 3 — Tests e2e: conversaciones completas multi-turno
"""

import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

MADRID_TZ = ZoneInfo("Europe/Madrid")

# ─────────────────────────────────────────────
# NIVEL 1 — TESTS UNITARIOS (no requieren API)
# ─────────────────────────────────────────────

class TestModels:
    def test_patient_phone_valid(self):
        from dental.core.models import Patient
        p = Patient(patient_id=1, clinic_id="c1", phone="+34612345678")
        assert p.phone == "+34612345678"

    def test_patient_phone_no_prefix_raises(self):
        from dental.core.models import Patient
        with pytest.raises(ValueError, match="prefijo internacional"):
            Patient(patient_id=1, clinic_id="c1", phone="612345678")

    def test_patient_phone_letters_raises(self):
        from dental.core.models import Patient
        with pytest.raises(ValueError):
            Patient(patient_id=1, clinic_id="c1", phone="+34abc1234")

    def test_appointment_datetime_es(self):
        from dental.core.models import Appointment, AppointmentStatus
        dt = datetime(2025, 6, 9, 10, 30, tzinfo=MADRID_TZ)  # lunes
        apt = Appointment(
            appointment_id="apt_test",
            clinic_id="c1",
            patient_phone="+34612345678",
            appointment_datetime=dt,
            treatment="Revisión",
            dentist="Dr. Test",
        )
        result = apt.datetime_es()
        assert "lunes" in result
        assert "9" in result
        assert "junio" in result
        assert "10:30" in result

    def test_clinic_service_model(self):
        from dental.core.models import ClinicService
        s = ClinicService(name="Implante", price_from=900)
        assert s.price_from == 900


class TestDatabase:
    def setup_method(self):
        from dental.core.database import reset_db
        self.db = reset_db()

    def test_seed_data_exists(self):
        clinic = self.db.get_clinic("clinic_001")
        assert clinic is not None
        assert "Sonríe" in clinic.name

    def test_get_nonexistent_clinic(self):
        assert self.db.get_clinic("no_existe") is None

    def test_patient_upsert_and_get(self):
        from dental.core.models import Patient
        p = Patient(patient_id=99, clinic_id="clinic_001", phone="+34699999999", name="Test User")
        self.db.upsert_patient(p)
        fetched = self.db.get_patient("clinic_001", "+34699999999")
        assert fetched is not None
        assert fetched.name == "Test User"

    def test_get_patient_wrong_clinic(self):
        assert self.db.get_patient("clinic_999", "+34612345678") is None

    def test_available_slots_returns_list(self):
        slots = self.db.get_available_slots("clinic_001", "2025-06-20")
        assert len(slots) > 0
        assert all(hasattr(s, "slot_id") for s in slots)
        assert all(hasattr(s, "time") for s in slots)

    def test_slots_exclude_occupied(self):
        """Una cita confirmada a las 10:30 no debe aparecer en los slots."""
        from dental.core.models import Appointment, AppointmentStatus
        dt = datetime(2025, 6, 20, 10, 30, tzinfo=MADRID_TZ)
        apt = Appointment(
            appointment_id="apt_occ",
            clinic_id="clinic_001",
            patient_phone="+34600000000",
            appointment_datetime=dt,
            treatment="Test",
            dentist="Dr. Test",
            status=AppointmentStatus.CONFIRMED,
        )
        self.db.save_appointment(apt)
        slots = self.db.get_available_slots("clinic_001", "2025-06-20")
        times = [s.time for s in slots]
        assert "10:30" not in times

    def test_confirm_appointment(self):
        apt = self.db.confirm_appointment("apt_001")
        assert apt is not None
        assert apt.confirmation_received is True

    def test_confirm_nonexistent(self):
        assert self.db.confirm_appointment("no_existe") is None

    def test_cancel_appointment(self):
        from dental.core.models import AppointmentStatus
        apt = self.db.cancel_appointment("apt_001", "Trabajo")
        assert apt is not None
        assert apt.status == AppointmentStatus.CANCELLED

    def test_patient_appointments_after_cancel(self):
        """Citas canceladas no deben aparecer en upcoming."""
        # Cuántas citas activas tiene María antes de cancelar una
        before = self.db.get_patient_appointments("clinic_001", "+34612345678")
        target_id = before[0].appointment_id
        self.db.cancel_appointment(target_id)
        after = self.db.get_patient_appointments("clinic_001", "+34612345678")
        assert len(after) == len(before) - 1
        assert all(a.appointment_id != target_id for a in after)

    def test_create_appointment_parses_slot(self):
        apt = self.db.create_appointment(
            clinic_id     = "clinic_001",
            patient_phone = "+34612345678",
            patient_name  = "Test Paciente",
            slot_id       = "slot_clinic_001_2025-06-20_0930",
            treatment     = "Limpieza",
        )
        assert apt.appointment_datetime.hour == 9
        assert apt.appointment_datetime.minute == 30
        assert apt.appointment_datetime.year == 2025

    def test_reminder_window(self):
        """Citas en ventana de 48h deben aparecer para recordatorio."""
        from dental.core.models import Appointment, AppointmentStatus, ReminderType
        future = datetime.now(MADRID_TZ) + timedelta(hours=48, minutes=30)
        apt = Appointment(
            appointment_id="apt_reminder",
            clinic_id="clinic_001",
            patient_phone="+34600111222",
            appointment_datetime=future,
            treatment="Test",
            dentist="Dr. Test",
            status=AppointmentStatus.CONFIRMED,
            reminder_48h_sent=False,
        )
        self.db.save_appointment(apt)
        pending = self.db.get_appointments_needing_reminder("clinic_001", ReminderType.HOURS_48)
        ids = [a.appointment_id for a in pending]
        assert "apt_reminder" in ids


class TestTools:
    def setup_method(self):
        from dental.core.database import reset_db
        reset_db()

    def test_get_clinic_info_ok(self):
        from dental.core.tools import get_clinic_info
        r = json.loads(get_clinic_info.invoke({"clinic_id": "clinic_001"}))
        assert "error" not in r
        assert "nombre" in r
        assert r["nombre"] == "Clínica Dental Sonríe"
        assert "servicios" in r
        assert len(r["servicios"]) > 0

    def test_get_clinic_info_not_found(self):
        from dental.core.tools import get_clinic_info
        r = json.loads(get_clinic_info.invoke({"clinic_id": "no_existe"}))
        assert "error" in r

    def test_get_patient_appointments_has_cita(self):
        from dental.core.tools import get_patient_appointments
        r = json.loads(get_patient_appointments.invoke({
            "patient_phone": "+34612345678",
            "clinic_id":     "clinic_001",
        }))
        assert r["tiene_citas"] is True
        assert r["total"] >= 1
        cita = r["citas"][0]
        assert "appointment_id" in cita
        assert "fecha_hora" in cita

    def test_get_patient_appointments_none(self):
        from dental.core.tools import get_patient_appointments
        r = json.loads(get_patient_appointments.invoke({
            "patient_phone": "+34699999999",
            "clinic_id":     "clinic_001",
        }))
        assert r["tiene_citas"] is False

    def test_check_slots_valid_date(self):
        from dental.core.tools import check_available_slots
        r = json.loads(check_available_slots.invoke({
            "clinic_id": "clinic_001",
            "date":      "2025-08-15",
        }))
        assert r["disponible"] is True
        assert len(r["huecos"]) <= 3
        assert r["total_disponibles"] >= 3

    def test_check_slots_invalid_date(self):
        from dental.core.tools import check_available_slots
        r = json.loads(check_available_slots.invoke({
            "clinic_id": "clinic_001",
            "date":      "not-a-date",
        }))
        assert "error" in r

    def test_confirm_appointment_ok(self):
        from dental.core.tools import confirm_appointment
        r = json.loads(confirm_appointment.invoke({
            "appointment_id": "apt_001",
            "patient_phone":  "+34612345678",
        }))
        assert r["confirmado"] is True
        assert "código" in r
        assert "dirección" in r

    def test_confirm_wrong_patient(self):
        from dental.core.tools import confirm_appointment
        r = json.loads(confirm_appointment.invoke({
            "appointment_id": "apt_001",
            "patient_phone":  "+34699999999",  # paciente equivocado
        }))
        assert "error" in r

    def test_cancel_appointment_ok(self):
        from dental.core.tools import cancel_appointment
        r = json.loads(cancel_appointment.invoke({
            "appointment_id": "apt_001",
            "patient_phone":  "+34612345678",
            "reason":         "No puedo ese día",
        }))
        assert r["cancelado"] is True
        assert r["motivo"] == "No puedo ese día"
        assert r["reagendar"] is True

    def test_cancel_already_cancelled(self):
        from dental.core.tools import cancel_appointment
        cancel_appointment.invoke({
            "appointment_id": "apt_001",
            "patient_phone":  "+34612345678",
        })
        r = json.loads(cancel_appointment.invoke({
            "appointment_id": "apt_001",
            "patient_phone":  "+34612345678",
        }))
        assert "error" in r

    def test_book_appointment_ok(self):
        from dental.core.tools import book_appointment
        r = json.loads(book_appointment.invoke({
            "patient_phone":  "+34612345678",
            "patient_name":   "María López",
            "clinic_id":      "clinic_001",
            "slot_id":        "slot_clinic_001_2025-08-15_1000",
            "treatment_type": "Limpieza dental",
        }))
        assert r["éxito"] is True
        assert "appointment_id" in r
        assert "código" in r

    def test_book_appointment_no_name(self):
        from dental.core.tools import book_appointment
        r = json.loads(book_appointment.invoke({
            "patient_phone":  "+34612345678",
            "patient_name":   "",
            "clinic_id":      "clinic_001",
            "slot_id":        "slot_clinic_001_2025-08-15_1000",
            "treatment_type": "Limpieza",
        }))
        assert "error" in r

    def test_escalate_to_human_ok(self):
        from dental.core.tools import escalate_to_human
        r = json.loads(escalate_to_human.invoke({
            "patient_phone":         "+34612345678",
            "clinic_id":             "clinic_001",
            "reason":                "Dolor intenso muela",
            "conversation_summary":  "Paciente dice que tiene dolor desde ayer",
        }))
        assert r["escalado"] is True
        assert r["personal_notificado"] is True
        assert "respuesta_estimada" in r


# ─────────────────────────────────────────────
# NIVEL 2 — INTEGRACIÓN CON CLAUDE API
# (solo si hay ANTHROPIC_API_KEY)
# ─────────────────────────────────────────────

HAS_API_KEY = bool(os.getenv("ANTHROPIC_API_KEY"))

@pytest.mark.skipif(not HAS_API_KEY, reason="ANTHROPIC_API_KEY no configurada")
class TestAgentIntegration:
    def setup_method(self):
        from dental.core.database import reset_db
        reset_db()

    def _chat(self, phone, text, clinic="clinic_001", name=None):
        from dental.core.agent import process_message
        return process_message(
            patient_phone=phone,
            message_text=text,
            clinic_id=clinic,
            patient_name=name,
        )

    def test_agent_responds_to_greeting(self):
        r = self._chat("+34611000001", "Hola, ¿están abiertos hoy?")
        assert isinstance(r, str)
        assert len(r) > 10
        print(f"\n[greeting] → {r[:100]}")

    def test_agent_gives_hours(self):
        r = self._chat("+34611000002", "¿A qué hora abrís?")
        assert any(kw in r.lower() for kw in ["09", "9:00", "horario", "lunes"])
        print(f"\n[hours] → {r[:100]}")

    def test_agent_gives_prices(self):
        r = self._chat("+34611000003", "¿Cuánto cuesta una limpieza?")
        assert any(kw in r for kw in ["€", "euro", "60", "precio", "desde"])
        print(f"\n[prices] → {r[:100]}")

    def test_agent_confirmation_flow(self):
        phone = "+34612345678"  # tiene cita en seed data
        # Simula recordatorio — paciente responde
        r = self._chat(phone, "Sí, confirmo mi cita", name="María López")
        assert any(kw in r.lower() for kw in ["confirm", "perfecto", "esperamos", "✅"])
        print(f"\n[confirm] → {r[:120]}")

    def test_agent_cancel_asks_first(self):
        phone = "+34612345678"
        r = self._chat(phone, "Quiero cancelar mi cita", name="María López")
        # Debe preguntar antes de cancelar, no cancelar directamente
        assert any(kw in r.lower() for kw in ["confirmas", "seguro", "¿", "cancelar"])
        print(f"\n[cancel-ask] → {r[:120]}")

    def test_agent_booking_flow(self):
        phone = "+34699888777"
        # Paso 1 — pedir cita
        r1 = self._chat(phone, "Hola, quiero pedir una cita para una limpieza")
        assert isinstance(r1, str) and len(r1) > 10
        print(f"\n[book-1] → {r1[:120]}")

        # Paso 2 — dar nombre y fecha
        r2 = self._chat(phone, "Me llamo Carlos García, ¿tenéis para el próximo martes?")
        assert isinstance(r2, str) and len(r2) > 10
        print(f"\n[book-2] → {r2[:120]}")

    def test_agent_escalates_urgency(self):
        phone = "+34699777666"
        r = self._chat(phone, "Tengo un dolor muy fuerte en la muela del juicio, no puedo ni comer")
        # Debe escalar o ofrecer urgencia
        assert any(kw in r.lower() for kw in ["urgencia", "urgente", "contactar", "llamar", "equipo", "enseguida"])
        print(f"\n[escalate] → {r[:120]}")

    def test_agent_memory_across_turns(self):
        """El agente debe recordar el nombre entre mensajes."""
        phone = "+34699555444"
        self._chat(phone, "Hola, me llamo Pedro Martínez")
        r2 = self._chat(phone, "¿Cuáles son vuestros horarios?")
        # No debe volver a preguntar el nombre
        assert "nombre" not in r2.lower() or "pedro" in r2.lower()
        print(f"\n[memory] → {r2[:120]}")

    def test_agent_faq_insurance(self):
        phone = "+34699444333"
        r = self._chat(phone, "¿Trabajáis con Sanitas?")
        assert "sanitas" in r.lower()
        print(f"\n[insurance] → {r[:100]}")


# ─────────────────────────────────────────────
# NIVEL 3 — E2E: CONVERSACIÓN COMPLETA
# ─────────────────────────────────────────────

@pytest.mark.skipif(not HAS_API_KEY, reason="ANTHROPIC_API_KEY no configurada")
class TestE2EConversations:
    def setup_method(self):
        from dental.core.database import reset_db
        reset_db()

    def _chat(self, phone, text, name=None):
        from dental.core.agent import process_message
        return process_message("+34" + phone, text, "clinic_001", name)

    def test_full_booking_conversation(self):
        """Conversación completa: paciente nuevo reserva una cita."""
        p = "699000001"
        print("\n=== CONVERSACIÓN: NUEVO PACIENTE RESERVA CITA ===")

        r1 = self._chat(p, "Hola buenas, quiero pedir cita")
        print(f"P: Hola buenas, quiero pedir cita")
        print(f"A: {r1}")
        assert len(r1) > 5

        r2 = self._chat(p, "Me llamo Ana Fernández, necesito una limpieza")
        print(f"\nP: Me llamo Ana Fernández, necesito una limpieza")
        print(f"A: {r2}")
        assert len(r2) > 5

        r3 = self._chat(p, "Para la semana que viene si es posible")
        print(f"\nP: Para la semana que viene si es posible")
        print(f"A: {r3}")
        assert len(r3) > 5

        r4 = self._chat(p, "La primera opción me va bien")
        print(f"\nP: La primera opción me va bien")
        print(f"A: {r4}")
        # Debe mencionar confirmación o código
        assert any(kw in r4.lower() for kw in ["cita", "reservad", "confirmad", "código", "✅"])

    def test_full_reminder_confirm_conversation(self):
        """Paciente existente responde a recordatorio y confirma."""
        p = "612345678"
        print("\n=== CONVERSACIÓN: RECORDATORIO → CONFIRMACIÓN ===")

        # El agente envió recordatorio, el paciente responde
        r1 = self._chat(p, "Sí, ahí estaré", name="María López")
        print(f"P: Sí, ahí estaré")
        print(f"A: {r1}")
        assert any(kw in r1.lower() for kw in ["perfecto", "esperamos", "✅", "confirmad"])

    def test_full_cancel_and_reschedule(self):
        """Paciente cancela y pide nueva cita."""
        p = "612345678"
        print("\n=== CONVERSACIÓN: CANCELAR Y REAGENDAR ===")

        r1 = self._chat(p, "Hola, necesito cancelar mi cita de esta semana", name="María López")
        print(f"P: Necesito cancelar mi cita")
        print(f"A: {r1}")

        r2 = self._chat(p, "Sí, por favor, es que me ha surgido algo de trabajo")
        print(f"\nP: Sí, por favor, trabajo")
        print(f"A: {r2}")

        r3 = self._chat(p, "¿Podríais ponerme el jueves a última hora?")
        print(f"\nP: ¿Podríais el jueves a última hora?")
        print(f"A: {r3}")
        assert len(r3) > 5


# ─────────────────────────────────────────────
# RUNNER
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"],
        capture_output=False,
    )
    sys.exit(result.returncode)
