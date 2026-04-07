"""
Dental Agent Core Module

Exports:
- Models (Pydantic types)
- Database (MemoryDB / PostgresDB)
- Agent (LangGraph + Claude)
- Tools (7 agent tools)
- Scheduler (reminders)
- WhatsApp Client (360dialog)
"""

from dental.core.models import (
    Appointment,
    AppointmentStatus,
    ClinicHours,
    ClinicInfo,
    ClinicService,
    Patient,
    ReminderType,
    TimeSlot,
)
from dental.core.database import get_db, reset_db, MemoryDB, PostgresDB
from dental.core.agent import process_message
from dental.core.whatsapp_client import (
    WhatsAppClient,
    get_whatsapp_client,
    send_whatsapp,
)

__all__ = [
    # Models
    "Appointment",
    "AppointmentStatus",
    "ClinicHours",
    "ClinicInfo",
    "ClinicService",
    "Patient",
    "ReminderType",
    "TimeSlot",
    # Database
    "get_db",
    "reset_db",
    "MemoryDB",
    "PostgresDB",
    # Agent
    "process_message",
    # WhatsApp
    "WhatsAppClient",
    "get_whatsapp_client",
    "send_whatsapp",
]
