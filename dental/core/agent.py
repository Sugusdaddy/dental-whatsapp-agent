"""
Agente LangGraph para clínica dental.

Arquitectura: ReAct loop con ToolNode
  START → agent → (si hay tool_calls) → tools → agent → ... → END

Memoria por thread_id = "{clinic_id}_{patient_phone}"
Cada paciente de cada clínica tiene su propia conversación.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Annotated, Literal, Optional
from zoneinfo import ZoneInfo

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from dental.core.database import get_db
from dental.core.models import ConversationStage
from dental.core.tools import ALL_TOOLS

MADRID_TZ = ZoneInfo("Europe/Madrid")


# ─────────────────────────────────────────────
# ESTADO
# ─────────────────────────────────────────────

class DentalAgentState(TypedDict):
    messages:             Annotated[list, add_messages]
    patient_phone:        str
    patient_name:         Optional[str]
    clinic_id:            str
    conversation_stage:   str


# ─────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """Eres el asistente virtual de WhatsApp de {clinic_name}, una clínica dental ubicada en {clinic_address}.

Te llamas "Sonríe" y eres amable, profesional y muy conciso — estás en WhatsApp, no en un email.

{patient_context}

## TU OBJETIVO
Ayudar al paciente a gestionar sus citas y resolver dudas con el mínimo de mensajes posibles.

## REGLAS ESTRICTAS

**Concisión**: Máximo 3-4 líneas por mensaje. En WhatsApp la gente no lee párrafos largos.

**Opciones de agenda**: Muestra siempre máximo 3 opciones. Nunca más.
Formato:
  1️⃣ Lunes 15 de enero a las 09:00 (30 min)
  2️⃣ Lunes 15 de enero a las 10:30 (45 min)
  3️⃣ Martes 16 de enero a las 17:00 (30 min)

**Confirmación antes de cancelar**: NUNCA canceles una cita sin confirmar primero.
Pregunta: "¿Confirmas que quieres cancelar tu cita del [fecha]?"

**Cero diagnósticos médicos**: Si el paciente describe síntomas o pide opinión médica,
empatiza y ofrece cita urgente o escala a un humano. Nunca des tu opinión médica.

**Escalación inmediata** si detectas:
- Dolor intenso, sangrado, accidente o trauma dental
- El paciente lleva más de 3 mensajes sin resolver su problema
- El paciente pide explícitamente hablar con alguien
- Situación que no sabes cómo gestionar

**Información de clínica**: Usa siempre get_clinic_info para precios y horarios.
NUNCA inventes datos.

**Fechas relativas**: Cuando el paciente diga "mañana", "el jueves", "la semana que viene",
calcula la fecha exacta tú mismo (hoy es {today}).

## FLUJOS

### Recordatorio (tú has iniciado el contacto)
El paciente recibió: "¿Confirmas tu cita del [fecha]?"
→ Respuesta positiva (sí, confirmo, perfecto, ok, claro, ahí estaré):
   → confirm_appointment → "¡Perfecto! Te esperamos el [fecha] en [dirección] 😊"
→ Respuesta negativa (no, no puedo, cancela):
   → Confirma antes de cancelar → cancel_appointment → ofrece reagendar
→ Quiere cambiar horario:
   → check_available_slots → muestra 3 opciones → book_appointment

### Paciente nuevo
1. Saluda con el nombre de la clínica
2. Pregunta en qué puedes ayudar
3. Si quiere cita: pide nombre (si no lo sabes) y tipo de tratamiento
4. check_available_slots para una fecha que le venga bien
5. book_appointment cuando elija
6. Confirma con código: "✅ Cita reservada: [detalles] | Código: CITA-XXXX"

### Preguntas frecuentes
Usa get_clinic_info. Responde directo, sin preámbulos.

## EMOJIS
Usa con moderación: 😊 ✅ ❌ 📅 — máximo 1-2 por mensaje.

Fecha y hora actual en Madrid: {today}
"""

def build_system_prompt(clinic_id: str, patient_name: Optional[str]) -> str:
    db     = get_db()
    clinic = db.get_clinic(clinic_id)

    clinic_name    = clinic.name    if clinic else clinic_id
    clinic_address = clinic.address if clinic else "dirección no disponible"

    patient_context = (
        f"Ya conoces al paciente: se llama {patient_name}."
        if patient_name
        else "No conoces aún el nombre del paciente."
    )

    today = datetime.now(MADRID_TZ).strftime("%A %d de %B de %Y, %H:%M")

    return SYSTEM_PROMPT_TEMPLATE.format(
        clinic_name     = clinic_name,
        clinic_address  = clinic_address,
        patient_context = patient_context,
        today           = today,
    )


# ─────────────────────────────────────────────
# NODOS DEL GRAFO
# ─────────────────────────────────────────────

def _get_model():
    return ChatAnthropic(
        model       = "claude-sonnet-4-20250514",
        max_tokens  = 1024,
        temperature = 0.2,   # bajo para consistencia — respuestas predecibles
    ).bind_tools(ALL_TOOLS)


def agent_node(state: DentalAgentState) -> dict:
    """Nodo principal: construye el prompt y llama al LLM."""
    system_prompt = build_system_prompt(
        state["clinic_id"],
        state.get("patient_name"),
    )

    messages = [SystemMessage(content=system_prompt)] + state["messages"]
    model    = _get_model()
    response = model.invoke(messages)

    return {"messages": [response]}


def should_continue(state: DentalAgentState) -> Literal["tools", "end"]:
    """Router: ¿el agente quiere usar una tool o ha terminado?"""
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "end"


# ─────────────────────────────────────────────
# COMPILACIÓN DEL GRAFO
# ─────────────────────────────────────────────

def build_graph() -> object:
    graph = StateGraph(DentalAgentState)

    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(ALL_TOOLS))

    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", "end": END},
    )
    graph.add_edge("tools", "agent")

    return graph.compile(checkpointer=MemorySaver())


# Instancia global — se crea una vez al importar el módulo
_graph = None

def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


# ─────────────────────────────────────────────
# FUNCIÓN PÚBLICA — punto de entrada
# ─────────────────────────────────────────────

def process_message(
    patient_phone: str,
    message_text:  str,
    clinic_id:     str,
    patient_name:  Optional[str] = None,
) -> str:
    """
    Procesa un mensaje de WhatsApp y devuelve la respuesta del agente.

    Args:
        patient_phone: +34612345678
        message_text:  Texto recibido
        clinic_id:     ID de la clínica (multi-tenant)
        patient_name:  Nombre si ya está en DB (opcional)

    Returns:
        Texto para enviar de vuelta por WhatsApp
    """
    # Enriquecer con nombre de DB si no viene en el parámetro
    if not patient_name:
        db      = get_db()
        patient = db.get_patient(clinic_id, patient_phone)
        if patient:
            patient_name = patient.name

    thread_id = f"{clinic_id}_{patient_phone}"
    config    = {"configurable": {"thread_id": thread_id}}

    state = {
        "messages":           [HumanMessage(content=message_text)],
        "patient_phone":      patient_phone,
        "patient_name":       patient_name,
        "clinic_id":          clinic_id,
        "conversation_stage": ConversationStage.GREETING.value,
    }

    result   = get_graph().invoke(state, config=config)
    last_msg = result["messages"][-1]

    # Extraer texto — AIMessage puede tener content como str o list
    if isinstance(last_msg.content, str):
        return last_msg.content
    if isinstance(last_msg.content, list):
        texts = [b["text"] for b in last_msg.content if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(texts)
    return str(last_msg.content)
