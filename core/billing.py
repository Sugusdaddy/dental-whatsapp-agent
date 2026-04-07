"""
Sistema de facturación con Stripe.

Planes:
- Starter: €99/mes — hasta 100 citas/mes
- Pro: €249/mes — hasta 500 citas/mes, dashboard
- Complete: €399/mes — ilimitado, Google Calendar, prioridad

Funcionalidad:
- Crear checkout session para suscripción
- Webhook para eventos de Stripe (payment_succeeded, payment_failed, etc.)
- Desactivar clínica si falla el pago
- Portal de cliente para gestionar suscripción
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from enum import Enum
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("dental.billing")
router = APIRouter(prefix="/api/billing", tags=["billing"])

MADRID_TZ = ZoneInfo("Europe/Madrid")


# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

class PlanType(str, Enum):
    STARTER = "starter"
    PRO = "pro"
    COMPLETE = "complete"


PLANS = {
    PlanType.STARTER: {
        "name": "Starter",
        "price_monthly": 99,
        "appointments_limit": 100,
        "features": [
            "Agente WhatsApp 24/7",
            "Confirmación de citas",
            "Recordatorios automáticos",
            "Soporte por email",
        ],
    },
    PlanType.PRO: {
        "name": "Pro",
        "price_monthly": 249,
        "appointments_limit": 500,
        "features": [
            "Todo de Starter",
            "Dashboard en tiempo real",
            "Seguimiento de presupuestos",
            "Reactivación de pacientes",
            "Soporte prioritario",
        ],
    },
    PlanType.COMPLETE: {
        "name": "Complete",
        "price_monthly": 399,
        "appointments_limit": -1,  # Ilimitado
        "features": [
            "Todo de Pro",
            "Citas ilimitadas",
            "Integración Google Calendar",
            "Onboarding personalizado",
            "Soporte telefónico",
        ],
    },
}

# Stripe Price IDs (configurar en Stripe Dashboard)
STRIPE_PRICE_IDS = {
    PlanType.STARTER: os.getenv("STRIPE_PRICE_STARTER", "price_starter"),
    PlanType.PRO: os.getenv("STRIPE_PRICE_PRO", "price_pro"),
    PlanType.COMPLETE: os.getenv("STRIPE_PRICE_COMPLETE", "price_complete"),
}


# ─────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────

class Subscription(BaseModel):
    """Modelo de suscripción."""
    subscription_id: str
    clinic_id: str
    plan: PlanType
    status: str  # active, past_due, canceled, unpaid
    stripe_customer_id: str
    stripe_subscription_id: str
    current_period_start: datetime
    current_period_end: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.now(MADRID_TZ))


class CreateCheckoutRequest(BaseModel):
    clinic_id: str
    plan: PlanType
    success_url: str
    cancel_url: str


class CreatePortalRequest(BaseModel):
    clinic_id: str
    return_url: str


# ─────────────────────────────────────────────
# STRIPE CLIENT
# ─────────────────────────────────────────────

class StripeClient:
    """Cliente para Stripe API."""
    
    def __init__(self):
        self.api_key = os.getenv("STRIPE_SECRET_KEY")
        self.webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    
    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)
    
    def _get_stripe(self):
        """Importa stripe solo cuando se necesita."""
        if not self.is_configured:
            raise ValueError("Stripe no configurado")
        
        import stripe
        stripe.api_key = self.api_key
        return stripe
    
    def create_checkout_session(
        self,
        clinic_id: str,
        plan: PlanType,
        success_url: str,
        cancel_url: str,
        customer_email: Optional[str] = None,
    ) -> str:
        """
        Crea una sesión de checkout de Stripe.
        
        Returns:
            URL del checkout
        """
        stripe = self._get_stripe()
        
        price_id = STRIPE_PRICE_IDS.get(plan)
        if not price_id:
            raise ValueError(f"Plan {plan} no configurado")
        
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{
                "price": price_id,
                "quantity": 1,
            }],
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=customer_email,
            metadata={
                "clinic_id": clinic_id,
                "plan": plan.value,
            },
        )
        
        logger.info(f"Checkout session creada para {clinic_id}: {session.id}")
        return session.url
    
    def create_portal_session(
        self,
        customer_id: str,
        return_url: str,
    ) -> str:
        """
        Crea una sesión del portal de cliente de Stripe.
        
        Returns:
            URL del portal
        """
        stripe = self._get_stripe()
        
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
        
        return session.url
    
    def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str,
    ) -> dict:
        """
        Verifica la firma del webhook de Stripe.
        
        Returns:
            Evento de Stripe
        """
        if not self.webhook_secret:
            raise ValueError("Webhook secret no configurado")
        
        stripe = self._get_stripe()
        
        try:
            event = stripe.Webhook.construct_event(
                payload, signature, self.webhook_secret
            )
            return event
        except Exception as e:
            logger.error(f"Error verificando webhook: {e}")
            raise


# ─────────────────────────────────────────────
# SUBSCRIPTION REPOSITORY
# ─────────────────────────────────────────────

class SubscriptionRepository:
    """Repositorio de suscripciones."""
    
    def __init__(self):
        self._subscriptions: dict[str, Subscription] = {}  # clinic_id → Subscription
        self._customer_map: dict[str, str] = {}  # stripe_customer_id → clinic_id
    
    def save(self, subscription: Subscription):
        self._subscriptions[subscription.clinic_id] = subscription
        self._customer_map[subscription.stripe_customer_id] = subscription.clinic_id
        logger.info(f"Suscripción guardada: {subscription.clinic_id} - {subscription.plan}")
    
    def get_by_clinic(self, clinic_id: str) -> Optional[Subscription]:
        return self._subscriptions.get(clinic_id)
    
    def get_by_customer(self, customer_id: str) -> Optional[Subscription]:
        clinic_id = self._customer_map.get(customer_id)
        if clinic_id:
            return self._subscriptions.get(clinic_id)
        return None
    
    def update_status(self, clinic_id: str, status: str):
        sub = self._subscriptions.get(clinic_id)
        if sub:
            sub.status = status
            logger.info(f"Suscripción actualizada: {clinic_id} → {status}")


# ─────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────

@router.get("/plans")
async def get_plans():
    """Devuelve los planes disponibles."""
    return {
        "plans": [
            {
                "id": plan.value,
                **PLANS[plan],
            }
            for plan in PlanType
        ]
    }


@router.post("/checkout")
async def create_checkout(data: CreateCheckoutRequest):
    """Crea una sesión de checkout de Stripe."""
    client = get_stripe_client()
    
    if not client.is_configured:
        raise HTTPException(
            status_code=501,
            detail="Stripe no configurado. Contacta con soporte.",
        )
    
    try:
        checkout_url = client.create_checkout_session(
            clinic_id=data.clinic_id,
            plan=data.plan,
            success_url=data.success_url,
            cancel_url=data.cancel_url,
        )
        
        return {"checkout_url": checkout_url}
    
    except Exception as e:
        logger.error(f"Error creando checkout: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/portal")
async def create_portal(data: CreatePortalRequest):
    """Crea una sesión del portal de cliente."""
    client = get_stripe_client()
    repo = get_subscription_repository()
    
    subscription = repo.get_by_clinic(data.clinic_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="No hay suscripción activa")
    
    try:
        portal_url = client.create_portal_session(
            customer_id=subscription.stripe_customer_id,
            return_url=data.return_url,
        )
        
        return {"portal_url": portal_url}
    
    except Exception as e:
        logger.error(f"Error creando portal: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """
    Webhook de Stripe para eventos de suscripción.
    
    Eventos manejados:
    - checkout.session.completed → Nueva suscripción
    - invoice.payment_succeeded → Pago exitoso
    - invoice.payment_failed → Pago fallido
    - customer.subscription.deleted → Suscripción cancelada
    """
    client = get_stripe_client()
    repo = get_subscription_repository()
    
    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    
    if not signature:
        raise HTTPException(status_code=400, detail="Missing signature")
    
    try:
        event = client.verify_webhook_signature(payload, signature)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid signature: {e}")
    
    event_type = event["type"]
    data = event["data"]["object"]
    
    logger.info(f"Stripe webhook: {event_type}")
    
    if event_type == "checkout.session.completed":
        # Nueva suscripción
        clinic_id = data["metadata"]["clinic_id"]
        plan = PlanType(data["metadata"]["plan"])
        customer_id = data["customer"]
        subscription_id = data["subscription"]
        
        subscription = Subscription(
            subscription_id=subscription_id,
            clinic_id=clinic_id,
            plan=plan,
            status="active",
            stripe_customer_id=customer_id,
            stripe_subscription_id=subscription_id,
            current_period_start=datetime.now(MADRID_TZ),
            current_period_end=datetime.now(MADRID_TZ),
        )
        repo.save(subscription)
        
        logger.info(f"Nueva suscripción: {clinic_id} → {plan}")
    
    elif event_type == "invoice.payment_succeeded":
        customer_id = data["customer"]
        subscription = repo.get_by_customer(customer_id)
        if subscription:
            repo.update_status(subscription.clinic_id, "active")
    
    elif event_type == "invoice.payment_failed":
        customer_id = data["customer"]
        subscription = repo.get_by_customer(customer_id)
        if subscription:
            repo.update_status(subscription.clinic_id, "past_due")
            # TODO: Notificar al dentista
    
    elif event_type == "customer.subscription.deleted":
        customer_id = data["customer"]
        subscription = repo.get_by_customer(customer_id)
        if subscription:
            repo.update_status(subscription.clinic_id, "canceled")
            # TODO: Desactivar clínica
    
    return {"status": "ok"}


@router.get("/status/{clinic_id}")
async def get_subscription_status(clinic_id: str):
    """Devuelve el estado de la suscripción de una clínica."""
    repo = get_subscription_repository()
    subscription = repo.get_by_clinic(clinic_id)
    
    if not subscription:
        return {
            "has_subscription": False,
            "status": "none",
            "message": "Sin suscripción activa",
        }
    
    plan_info = PLANS.get(subscription.plan, {})
    
    return {
        "has_subscription": True,
        "status": subscription.status,
        "plan": subscription.plan.value,
        "plan_name": plan_info.get("name"),
        "price_monthly": plan_info.get("price_monthly"),
        "features": plan_info.get("features", []),
    }


# ─────────────────────────────────────────────
# SINGLETONS
# ─────────────────────────────────────────────

_stripe_client: Optional[StripeClient] = None
_subscription_repo: Optional[SubscriptionRepository] = None


def get_stripe_client() -> StripeClient:
    global _stripe_client
    if _stripe_client is None:
        _stripe_client = StripeClient()
    return _stripe_client


def get_subscription_repository() -> SubscriptionRepository:
    global _subscription_repo
    if _subscription_repo is None:
        _subscription_repo = SubscriptionRepository()
    return _subscription_repo
