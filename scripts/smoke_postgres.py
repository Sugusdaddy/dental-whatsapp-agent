#!/usr/bin/env python3
"""
Smoke test de PostgresDB contra una Postgres real.

USO
───
1. Levantar Postgres local con Docker:

       docker run --rm -d --name dental-pg \
         -e POSTGRES_PASSWORD=test \
         -e POSTGRES_DB=dental_agent \
         -p 5433:5432 postgres:16-alpine

   …o usar tu Supabase / Neon / Railway directamente.

2. Cargar el schema:

       psql "postgresql://postgres:test@localhost:5433/dental_agent" \
            -f schema.sql

3. Ejecutar este smoke test:

       DATABASE_URL="postgresql://postgres:test@localhost:5433/dental_agent" \
         python scripts/smoke_postgres.py

4. (Opcional) Limpiar:

       docker rm -f dental-pg

QUÉ COMPRUEBA
─────────────
Cada uno de los métodos públicos de PostgresDB:

  ✓ get_clinic            ✓ confirm_appointment
  ✓ update_clinic         ✓ cancel_appointment
  ✓ upsert_patient        ✓ get_appointments_needing_reminder
  ✓ get_patient           ✓ get_available_slots
  ✓ save_appointment      ✓ set_human_takeover
  ✓ get_appointment       ✓ is_human_takeover
  ✓ get_patient_appointments

Imprime un check verde por cada método que pasa, una cruz roja por cada
fallo. Sale con código 0 si todo pasa, 1 si algún método falla.

NOTA
────
Este script NO se ejecuta en pytest porque requiere Postgres real. Se
corre manualmente desde la línea de comandos antes de hacer deploy.
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


# ─────────────────────────────────────────────
# Output helpers
# ─────────────────────────────────────────────

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
DIM = "\033[2m"
RESET = "\033[0m"


class Results:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.errors: list[tuple[str, str]] = []

    def ok(self, label: str, detail: str = "") -> None:
        self.passed += 1
        suffix = f" {DIM}{detail}{RESET}" if detail else ""
        print(f"  {GREEN}✓{RESET} {label}{suffix}")

    def fail(self, label: str, error: str) -> None:
        self.failed += 1
        self.errors.append((label, error))
        print(f"  {RED}✗{RESET} {label}")
        for line in error.splitlines():
            print(f"    {RED}{line}{RESET}")

    def section(self, title: str) -> None:
        print(f"\n{YELLOW}━━ {title} ━━{RESET}")

    def summary(self) -> int:
        total = self.passed + self.failed
        print()
        if self.failed == 0:
            print(f"{GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
            print(f"{GREEN}  ✓ Todo OK — {self.passed}/{total} comprobaciones{RESET}")
            print(f"{GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
            return 0
        print(f"{RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
        print(f"{RED}  ✗ {self.failed}/{total} fallos{RESET}")
        print(f"{RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
        return 1


def run(label: str, results: Results, fn) -> object:
    """Ejecuta `fn`, registra OK / FAIL y devuelve el resultado (o None)."""
    try:
        out = fn()
        detail = ""
        if isinstance(out, (str, int, float, bool)):
            detail = f"→ {out!r}"
        elif out is None:
            detail = "→ None"
        elif isinstance(out, list):
            detail = f"→ {len(out)} item(s)"
        results.ok(label, detail)
        return out
    except Exception as e:
        tb = traceback.format_exc(limit=3)
        results.fail(label, f"{type(e).__name__}: {e}\n{tb}")
        return None


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main() -> int:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print(f"{RED}DATABASE_URL no está configurado.{RESET}")
        print()
        print("Ejemplo:")
        print('  export DATABASE_URL="postgresql://postgres:test@localhost:5433/dental_agent"')
        print("  python scripts/smoke_postgres.py")
        return 1

    print(f"{DIM}DATABASE_URL: {database_url}{RESET}")

    # Importar después de validar el entorno
    try:
        from dental.core.database import PostgresDB
        from dental.core.models import (
            Appointment, AppointmentStatus, Patient, ReminderType,
        )
    except ImportError as e:
        print(f"{RED}No se pudo importar dental.core: {e}{RESET}")
        print(f"{DIM}Asegúrate de ejecutar desde la raíz del proyecto.{RESET}")
        return 1

    results = Results()
    MADRID = ZoneInfo("Europe/Madrid")

    # ── 1. Conexión + pool ────────────────────────
    results.section("Conexión")
    db = run("Instanciar PostgresDB con pool", results, lambda: PostgresDB(database_url))
    if db is None:
        return results.summary()

    # ── 2. Clinic CRUD ────────────────────────────
    results.section("Clinic")
    clinic = run(
        "get_clinic('clinic_001') — debe existir tras schema.sql",
        results,
        lambda: db.get_clinic("clinic_001"),
    )
    if clinic is None:
        print(f"  {YELLOW}⚠ ¿Cargaste schema.sql? psql ... -f schema.sql{RESET}")
        return results.summary()

    run(
        "update_clinic — cambia name + phone",
        results,
        lambda: db.update_clinic("clinic_001", {
            "name": "Smoke Test Clinic",
            "phone": "+34999000000",
        }),
    )
    after = run(
        "get_clinic — verifica que el cambio persistió",
        results,
        lambda: db.get_clinic("clinic_001"),
    )
    if after and after.name != "Smoke Test Clinic":
        results.fail(
            "update_clinic persistencia",
            f"name='{after.name}' (esperado 'Smoke Test Clinic')",
        )
    # Restaurar para no dejar la DB sucia
    db.update_clinic("clinic_001", {
        "name": "Clínica Dental Sonríe",
        "phone": "+34 91 234 56 78",
    })

    # ── 3. Patient CRUD ───────────────────────────
    results.section("Patient")
    test_phone = "+34600999888"

    run(
        "upsert_patient — crear nuevo",
        results,
        lambda: db.upsert_patient(Patient(
            patient_id=0,
            clinic_id="clinic_001",
            phone=test_phone,
            name="Smoke Test",
            email="smoke@test.com",
        )),
    )
    fetched = run(
        "get_patient — recuperar creado",
        results,
        lambda: db.get_patient("clinic_001", test_phone),
    )
    if fetched and fetched.name != "Smoke Test":
        results.fail("get_patient name", f"esperado 'Smoke Test', obtenido '{fetched.name}'")

    run(
        "upsert_patient — update (mismo phone)",
        results,
        lambda: db.upsert_patient(Patient(
            patient_id=0,
            clinic_id="clinic_001",
            phone=test_phone,
            name="Smoke Test Updated",
        )),
    )

    # ── 4. Appointment CRUD ───────────────────────
    results.section("Appointment")
    apt_dt = datetime.now(MADRID) + timedelta(days=2, hours=1)
    apt_id = f"smoke_apt_{int(datetime.now().timestamp())}"

    apt = Appointment(
        appointment_id=apt_id,
        clinic_id="clinic_001",
        patient_phone=test_phone,
        patient_name="Smoke Test",
        appointment_datetime=apt_dt,
        treatment="Smoke test",
        dentist="Dr. Smoke",
        duration_min=30,
        status=AppointmentStatus.CONFIRMED,
    )
    run("save_appointment", results, lambda: db.save_appointment(apt))
    run("get_appointment", results, lambda: db.get_appointment(apt_id))

    run(
        "get_patient_appointments (only_upcoming=True)",
        results,
        lambda: db.get_patient_appointments("clinic_001", test_phone, only_upcoming=True),
    )

    run(
        "confirm_appointment",
        results,
        lambda: db.confirm_appointment(apt_id),
    )

    # ── 5. Reminders ──────────────────────────────
    results.section("Reminders")
    run(
        "get_appointments_needing_reminder (48h)",
        results,
        lambda: db.get_appointments_needing_reminder("clinic_001", ReminderType.HOURS_48),
    )

    # ── 6. Slots ──────────────────────────────────
    results.section("Slots")
    today = datetime.now(MADRID).strftime("%Y-%m-%d")
    run(
        f"get_available_slots ({today})",
        results,
        lambda: db.get_available_slots("clinic_001", today),
    )

    # ── 7. Human Takeover ─────────────────────────
    results.section("Human Takeover")
    run(
        "is_human_takeover — false por defecto",
        results,
        lambda: _expect_false(db.is_human_takeover("clinic_001", test_phone)),
    )
    run(
        "set_human_takeover(True)",
        results,
        lambda: db.set_human_takeover("clinic_001", test_phone, True),
    )
    run(
        "is_human_takeover — true tras enable",
        results,
        lambda: _expect_true(db.is_human_takeover("clinic_001", test_phone)),
    )
    run(
        "set_human_takeover(False)",
        results,
        lambda: db.set_human_takeover("clinic_001", test_phone, False),
    )
    run(
        "is_human_takeover — false tras disable",
        results,
        lambda: _expect_false(db.is_human_takeover("clinic_001", test_phone)),
    )

    # ── 8. Cancel ─────────────────────────────────
    results.section("Cleanup")
    run(
        "cancel_appointment (smoke apt)",
        results,
        lambda: db.cancel_appointment(apt_id, "smoke test cleanup"),
    )

    return results.summary()


def _expect_true(v):
    assert v is True, f"esperado True, obtenido {v!r}"
    return v


def _expect_false(v):
    assert v is False, f"esperado False, obtenido {v!r}"
    return v


if __name__ == "__main__":
    sys.exit(main())
