"""
Sistema de onboarding de clínicas.

Endpoints:
- POST /api/onboarding/register — registro inicial de clínica
- GET /api/onboarding/connect-whatsapp — redirect a 360dialog
- GET /api/onboarding/connect-calendar — redirect a Google OAuth
- POST /api/onboarding/complete — finalizar onboarding

El flujo:
1. Dentista rellena formulario (nombre, dirección, horarios, servicios)
2. Conecta su WhatsApp Business via 360dialog
3. (Opcional) Conecta su Google Calendar
4. Recibe email de bienvenida con instrucciones
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from dental.core.database import get_db
from dental.core.models import ClinicHours, ClinicInfo, ClinicService

logger = logging.getLogger("dental.onboarding")
router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

MADRID_TZ = ZoneInfo("Europe/Madrid")


# ─────────────────────────────────────────────
# SCHEMAS
# ─────────────────────────────────────────────

class ServiceInput(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    price_from: float = Field(..., ge=0)
    duration_min: int = Field(default=30, ge=15, le=180)


class ClinicRegistration(BaseModel):
    """Datos para registrar una nueva clínica."""
    name: str = Field(..., min_length=3, max_length=200)
    address: str = Field(..., min_length=10, max_length=500)
    phone: str = Field(..., pattern=r"^\+?[0-9\s]{9,20}$")
    email: EmailStr
    
    # Horarios
    weekday_open: str = Field(default="09:00", pattern=r"^\d{2}:\d{2}$")
    weekday_close: str = Field(default="20:00", pattern=r"^\d{2}:\d{2}$")
    saturday_open: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    saturday_close: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    
    # Servicios
    services: list[ServiceInput] = Field(default_factory=list)
    
    # Seguros aceptados
    insurance_accepted: list[str] = Field(default_factory=list)
    
    # Parking
    parking: Optional[str] = None


class ClinicRegistrationResponse(BaseModel):
    clinic_id: str
    webhook_secret: str
    webhook_url: str
    status: str
    message: str


class WhatsAppConnectionRequest(BaseModel):
    clinic_id: str
    whatsapp_number: str = Field(..., pattern=r"^\+?[0-9]{10,15}$")


class CalendarConnectionRequest(BaseModel):
    clinic_id: str


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def generate_clinic_id() -> str:
    """Genera un ID único para la clínica."""
    return f"clinic_{secrets.token_hex(8)}"


def generate_webhook_secret() -> str:
    """Genera un secret único para el webhook."""
    return secrets.token_hex(32)


async def send_welcome_email(email: str, clinic_name: str, clinic_id: str, webhook_url: str):
    """
    Envía email de bienvenida con instrucciones.
    En producción: usar SendGrid, Resend, etc.
    """
    logger.info(f"Enviando email de bienvenida a {email} para {clinic_name}")
    
    # TODO: Integrar con servicio de email
    # Por ahora solo log
    logger.info(f"""
    === EMAIL DE BIENVENIDA ===
    Para: {email}
    Asunto: Bienvenido a Dental Agent
    
    Hola,
    
    Tu clínica "{clinic_name}" está casi lista.
    
    Siguiente paso: conecta tu número de WhatsApp Business.
    
    Tu webhook URL es: {webhook_url}
    
    Saludos,
    Dental Agent
    ===========================
    """)


# ─────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────

@router.post("/register", response_model=ClinicRegistrationResponse)
async def register_clinic(data: ClinicRegistration):
    """
    Registra una nueva clínica y genera sus credenciales.
    """
    db = get_db()
    
    # Generar IDs únicos
    clinic_id = generate_clinic_id()
    webhook_secret = generate_webhook_secret()
    
    # Crear objeto ClinicInfo
    clinic = ClinicInfo(
        clinic_id=clinic_id,
        name=data.name,
        address=data.address,
        phone=data.phone,
        whatsapp_number="",  # Se configura después
        hours=ClinicHours(
            weekday_open=data.weekday_open,
            weekday_close=data.weekday_close,
            saturday_open=data.saturday_open,
            saturday_close=data.saturday_close,
        ),
        services=[
            ClinicService(
                name=s.name,
                price_from=s.price_from,
                duration_min=s.duration_min,
            )
            for s in data.services
        ],
        insurance_accepted=data.insurance_accepted,
        parking=data.parking,
    )
    
    # Guardar en DB (usando _clinics directamente para MemoryDB)
    # En PostgresDB habría un método save_clinic()
    if hasattr(db, '_clinics'):
        db._clinics[clinic_id] = clinic
    else:
        # PostgresDB
        # TODO: Implementar db.save_clinic(clinic)
        pass
    
    # Generar URL del webhook
    base_url = os.getenv("BASE_URL", "http://localhost:8001")
    webhook_url = f"{base_url}/webhook/{clinic_id}"
    
    # Enviar email de bienvenida
    await send_welcome_email(data.email, data.name, clinic_id, webhook_url)
    
    logger.info(f"Nueva clínica registrada: {clinic_id} - {data.name}")
    
    return ClinicRegistrationResponse(
        clinic_id=clinic_id,
        webhook_secret=webhook_secret,
        webhook_url=webhook_url,
        status="pending_whatsapp",
        message="Clínica registrada. Siguiente paso: conectar WhatsApp Business.",
    )


@router.post("/connect-whatsapp")
async def connect_whatsapp(data: WhatsAppConnectionRequest):
    """
    Asocia un número de WhatsApp Business a la clínica.
    """
    db = get_db()
    clinic = db.get_clinic(data.clinic_id)
    
    if not clinic:
        raise HTTPException(status_code=404, detail="Clínica no encontrada")
    
    # Actualizar número de WhatsApp
    clinic.whatsapp_number = data.whatsapp_number
    
    # Guardar cambios
    if hasattr(db, '_clinics'):
        db._clinics[data.clinic_id] = clinic
    
    logger.info(f"WhatsApp conectado para {data.clinic_id}: {data.whatsapp_number}")
    
    return {
        "status": "connected",
        "clinic_id": data.clinic_id,
        "whatsapp_number": data.whatsapp_number,
        "message": "WhatsApp conectado correctamente. Tu agente está listo.",
    }


@router.get("/connect-calendar/{clinic_id}")
async def connect_calendar(clinic_id: str):
    """
    Redirige al flujo OAuth de Google Calendar.
    """
    from dental.core.calendar import get_calendar_client
    
    db = get_db()
    clinic = db.get_clinic(clinic_id)
    
    if not clinic:
        raise HTTPException(status_code=404, detail="Clínica no encontrada")
    
    calendar = get_calendar_client()
    
    if not calendar.is_configured:
        raise HTTPException(
            status_code=501,
            detail="Integración con Google Calendar no configurada",
        )
    
    base_url = os.getenv("BASE_URL", "http://localhost:8001")
    redirect_uri = f"{base_url}/api/onboarding/calendar-callback"
    
    oauth_url = calendar.get_oauth_url(clinic_id, redirect_uri)
    
    return {
        "status": "redirect",
        "oauth_url": oauth_url,
        "message": "Redirige al usuario a oauth_url para conectar su calendario.",
    }


@router.get("/calendar-callback")
async def calendar_callback(code: str, state: str):
    """
    Callback de OAuth de Google Calendar.
    El parámetro 'state' contiene el clinic_id.
    """
    from dental.core.calendar import get_calendar_client
    
    clinic_id = state
    db = get_db()
    clinic = db.get_clinic(clinic_id)
    
    if not clinic:
        raise HTTPException(status_code=404, detail="Clínica no encontrada")
    
    calendar = get_calendar_client()
    base_url = os.getenv("BASE_URL", "http://localhost:8001")
    redirect_uri = f"{base_url}/api/onboarding/calendar-callback"
    
    try:
        tokens = await calendar.exchange_code(code, redirect_uri)
        calendar.set_credentials(clinic_id, tokens)
        
        logger.info(f"Google Calendar conectado para {clinic_id}")
        
        return {
            "status": "connected",
            "clinic_id": clinic_id,
            "message": "Google Calendar conectado correctamente.",
        }
    except Exception as e:
        logger.error(f"Error conectando Google Calendar: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/status/{clinic_id}")
async def get_onboarding_status(clinic_id: str):
    """
    Devuelve el estado del onboarding de una clínica.
    """
    db = get_db()
    clinic = db.get_clinic(clinic_id)
    
    if not clinic:
        raise HTTPException(status_code=404, detail="Clínica no encontrada")
    
    # Determinar estado
    has_whatsapp = bool(clinic.whatsapp_number)
    has_calendar = False  # TODO: Verificar en DB
    
    if has_whatsapp:
        status = "active"
        message = "Tu agente está activo y listo para recibir mensajes."
    else:
        status = "pending_whatsapp"
        message = "Conecta tu número de WhatsApp Business para activar el agente."
    
    return {
        "clinic_id": clinic_id,
        "clinic_name": clinic.name,
        "status": status,
        "message": message,
        "whatsapp_connected": has_whatsapp,
        "calendar_connected": has_calendar,
    }
