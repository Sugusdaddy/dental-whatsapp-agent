"""
Sistema de seguimiento de presupuestos.

Funcionalidad:
- Crear presupuestos desde el agente (tool: create_quote)
- Job diario que envía follow-ups a los 3, 7 y 14 días
- Máximo 3 intentos de follow-up
- Si no responde → marca como expirado

Tablas:
- quotes (id, clinic_id, patient_phone, patient_name, treatment, amount, 
         status, followup_count, last_followup, created_at, updated_at)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

logger = logging.getLogger("dental.quotes")

MADRID_TZ = ZoneInfo("Europe/Madrid")


# ─────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────

class QuoteStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class Quote(BaseModel):
    """Modelo de presupuesto."""
    quote_id: str
    clinic_id: str
    patient_phone: str
    patient_name: Optional[str] = None
    treatment: str
    amount: float = Field(..., ge=0)
    status: QuoteStatus = QuoteStatus.PENDING
    followup_count: int = 0
    last_followup: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(MADRID_TZ))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(MADRID_TZ))


# ─────────────────────────────────────────────
# QUOTES REPOSITORY (in-memory, para PostgreSQL ver database.py)
# ─────────────────────────────────────────────

class QuotesRepository:
    """Repositorio de presupuestos."""
    
    def __init__(self):
        self._quotes: dict[str, Quote] = {}
        self._seq = 1
    
    def create_quote(
        self,
        clinic_id: str,
        patient_phone: str,
        patient_name: Optional[str],
        treatment: str,
        amount: float,
    ) -> Quote:
        """Crea un nuevo presupuesto."""
        quote_id = f"quote_{self._seq:04d}"
        self._seq += 1
        
        quote = Quote(
            quote_id=quote_id,
            clinic_id=clinic_id,
            patient_phone=patient_phone,
            patient_name=patient_name,
            treatment=treatment,
            amount=amount,
        )
        
        self._quotes[quote_id] = quote
        logger.info(f"Presupuesto creado: {quote_id} - {treatment} - €{amount}")
        
        return quote
    
    def get_quote(self, quote_id: str) -> Optional[Quote]:
        return self._quotes.get(quote_id)
    
    def get_patient_quotes(
        self,
        clinic_id: str,
        patient_phone: str,
    ) -> list[Quote]:
        """Obtiene presupuestos de un paciente."""
        return [
            q for q in self._quotes.values()
            if q.clinic_id == clinic_id and q.patient_phone == patient_phone
        ]
    
    def get_quotes_needing_followup(self, clinic_id: str) -> list[Quote]:
        """
        Obtiene presupuestos pendientes que necesitan follow-up.
        
        Criterios:
        - status = pending
        - followup_count < 3
        - Días desde creación o último follow-up: 3, 7, o 14 días
        """
        now = datetime.now(MADRID_TZ)
        quotes = []
        
        for quote in self._quotes.values():
            if quote.clinic_id != clinic_id:
                continue
            if quote.status != QuoteStatus.PENDING:
                continue
            if quote.followup_count >= 3:
                continue
            
            # Calcular días desde último contacto
            last_contact = quote.last_followup or quote.created_at
            days_since = (now - last_contact).days
            
            # Follow-up schedule: 3, 7, 14 días
            followup_days = [3, 7, 14]
            target_days = followup_days[quote.followup_count] if quote.followup_count < 3 else 999
            
            if days_since >= target_days:
                quotes.append(quote)
        
        return quotes
    
    def update_followup(self, quote_id: str) -> Optional[Quote]:
        """Registra que se envió un follow-up."""
        quote = self._quotes.get(quote_id)
        if not quote:
            return None
        
        quote.followup_count += 1
        quote.last_followup = datetime.now(MADRID_TZ)
        quote.updated_at = datetime.now(MADRID_TZ)
        
        # Si llegó a 3 intentos, marcar como expirado
        if quote.followup_count >= 3:
            quote.status = QuoteStatus.EXPIRED
            logger.info(f"Presupuesto {quote_id} expirado tras 3 follow-ups")
        
        return quote
    
    def accept_quote(self, quote_id: str) -> Optional[Quote]:
        """Marca un presupuesto como aceptado."""
        quote = self._quotes.get(quote_id)
        if not quote:
            return None
        
        quote.status = QuoteStatus.ACCEPTED
        quote.updated_at = datetime.now(MADRID_TZ)
        logger.info(f"Presupuesto {quote_id} aceptado")
        
        return quote
    
    def reject_quote(self, quote_id: str) -> Optional[Quote]:
        """Marca un presupuesto como rechazado."""
        quote = self._quotes.get(quote_id)
        if not quote:
            return None
        
        quote.status = QuoteStatus.REJECTED
        quote.updated_at = datetime.now(MADRID_TZ)
        logger.info(f"Presupuesto {quote_id} rechazado")
        
        return quote


# ─────────────────────────────────────────────
# FOLLOW-UP MESSAGES
# ─────────────────────────────────────────────

def build_followup_message(quote: Quote, attempt: int) -> str:
    """
    Construye el mensaje de follow-up según el intento.
    """
    name = quote.patient_name or "paciente"
    
    messages = [
        # Intento 1 (3 días)
        f"Hola {name}, soy el asistente de la clínica. "
        f"¿Has tenido oportunidad de revisar el presupuesto de {quote.treatment} "
        f"por €{quote.amount:.0f}? Estoy aquí para resolver cualquier duda.",
        
        # Intento 2 (7 días)
        f"Hola {name}, solo quería hacer seguimiento del presupuesto que te envié. "
        f"Si tienes alguna pregunta sobre el tratamiento de {quote.treatment}, "
        f"no dudes en escribirme.",
        
        # Intento 3 (14 días)
        f"Hola {name}, es mi último mensaje sobre el presupuesto de {quote.treatment}. "
        f"Si en algún momento decides seguir adelante, aquí estaré para ayudarte. "
        f"¡Que tengas un buen día!",
    ]
    
    return messages[min(attempt, len(messages) - 1)]


# ─────────────────────────────────────────────
# SINGLETON
# ─────────────────────────────────────────────

_quotes_repo: Optional[QuotesRepository] = None


def get_quotes_repository() -> QuotesRepository:
    """Devuelve el repositorio de presupuestos (singleton)."""
    global _quotes_repo
    if _quotes_repo is None:
        _quotes_repo = QuotesRepository()
    return _quotes_repo
