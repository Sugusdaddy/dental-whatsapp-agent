"""
Integración con Google Calendar para obtener disponibilidad real.

Uso:
1. El dentista conecta su Google Calendar via OAuth2
2. El sistema lee eventos existentes para saber qué está ocupado
3. Los slots disponibles = horarios base - eventos existentes

Configuración:
- GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET en .env
- Credenciales OAuth2 se guardan en tabla clinic_google_auth
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from dental.core.models import TimeSlot

logger = logging.getLogger("dental.calendar")

MADRID_TZ = ZoneInfo("Europe/Madrid")


class GoogleCalendarClient:
    """Cliente para Google Calendar API."""
    
    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ):
        self.client_id = client_id or os.getenv("GOOGLE_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("GOOGLE_CLIENT_SECRET")
        self._credentials: dict[str, dict] = {}  # clinic_id → credentials
    
    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)
    
    def get_oauth_url(self, clinic_id: str, redirect_uri: str) -> str:
        """
        Genera URL de OAuth2 para que el dentista conecte su calendario.
        """
        if not self.is_configured:
            raise ValueError("Google OAuth no configurado")
        
        from urllib.parse import urlencode
        
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/calendar.readonly",
            "access_type": "offline",
            "prompt": "consent",
            "state": clinic_id,
        }
        
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    
    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
    ) -> dict:
        """
        Intercambia el código OAuth por tokens.
        """
        import httpx
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
            )
            response.raise_for_status()
            return response.json()
    
    async def refresh_token(self, refresh_token: str) -> dict:
        """
        Renueva el access_token usando el refresh_token.
        """
        import httpx
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            response.raise_for_status()
            return response.json()
    
    def set_credentials(self, clinic_id: str, credentials: dict):
        """Guarda credenciales para una clínica."""
        self._credentials[clinic_id] = credentials
    
    async def get_busy_times(
        self,
        clinic_id: str,
        date: str,
        access_token: str,
    ) -> list[tuple[str, str]]:
        """
        Obtiene los horarios ocupados del calendario para una fecha.
        
        Returns:
            Lista de tuplas (hora_inicio, hora_fin) en formato "HH:MM"
        """
        import httpx
        
        # Construir rango de tiempo (todo el día)
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        time_min = date_obj.replace(hour=0, minute=0, tzinfo=MADRID_TZ).isoformat()
        time_max = date_obj.replace(hour=23, minute=59, tzinfo=MADRID_TZ).isoformat()
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={
                        "timeMin": time_min,
                        "timeMax": time_max,
                        "singleEvents": "true",
                        "orderBy": "startTime",
                    },
                )
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            logger.error(f"Error obteniendo eventos de Google Calendar: {e}")
            return []
        
        busy_times = []
        for event in data.get("items", []):
            start = event.get("start", {})
            end = event.get("end", {})
            
            # Extraer hora de inicio y fin
            start_time = start.get("dateTime")
            end_time = end.get("dateTime")
            
            if start_time and end_time:
                start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                
                busy_times.append((
                    start_dt.astimezone(MADRID_TZ).strftime("%H:%M"),
                    end_dt.astimezone(MADRID_TZ).strftime("%H:%M"),
                ))
        
        return busy_times
    
    def filter_available_slots(
        self,
        base_slots: list[TimeSlot],
        busy_times: list[tuple[str, str]],
    ) -> list[TimeSlot]:
        """
        Filtra los slots base eliminando los que coinciden con horarios ocupados.
        """
        available = []
        
        for slot in base_slots:
            slot_start = slot.time
            # Calcular hora de fin del slot
            start_h, start_m = map(int, slot_start.split(":"))
            end_minutes = start_h * 60 + start_m + slot.duration_min
            slot_end = f"{end_minutes // 60:02d}:{end_minutes % 60:02d}"
            
            # Verificar si el slot colisiona con algún horario ocupado
            is_busy = False
            for busy_start, busy_end in busy_times:
                # Hay colisión si los rangos se solapan
                if not (slot_end <= busy_start or slot_start >= busy_end):
                    is_busy = True
                    break
            
            if not is_busy:
                available.append(slot)
        
        return available


# ─────────────────────────────────────────────
# SINGLETON
# ─────────────────────────────────────────────

_calendar_client: Optional[GoogleCalendarClient] = None


def get_calendar_client() -> GoogleCalendarClient:
    """Devuelve el cliente de Google Calendar (singleton)."""
    global _calendar_client
    if _calendar_client is None:
        _calendar_client = GoogleCalendarClient()
    return _calendar_client
