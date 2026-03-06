"""
Dental Clinic AI Agent – validates queries are dental-related, executes
tool calls (appointments, services, etc.), and streams responses via Gemini.

Exposes:
  process_message(text)                → str   (sync, non-streaming)
  process_message_stream(text, history) → async generator[str]  (streaming)
"""

import json
import os
from datetime import datetime, timezone
from typing import AsyncGenerator

from google import genai
from google.genai import types
from dotenv import load_dotenv

from app.database import (
    appointments_collection,
    dental_services_collection,
    dentists_collection,
    patients_collection,
    treatment_records_collection,
)
from app.services.llm_service import (
    agenerate_stream_with_tools,
    generate_with_tools,
)

load_dotenv()

today = datetime.now().strftime("%Y-%m-%d")
day_name = datetime.now().strftime("%A")

# ── System prompt ────────────────────────────────────────────

SYSTEM_PROMPT = f"""
You are **SmileCare AI** – a friendly, professional dental clinic receptionist.
Today's date is {today} ({day_name}).

═══ SCOPE ═══
You ONLY handle topics related to dentistry and this dental clinic:
  • Appointment booking / cancellation / rescheduling
  • Dental services, prices, and procedures
  • Clinic hours, location, contact info
  • Dentist information and specializations
  • General dental health advice and oral hygiene tips
  • Patient appointment look-ups

If a user asks about ANYTHING unrelated to dentistry or this clinic, politely
decline and redirect them:
  "I'm SmileCare AI, your dental clinic assistant. I can only help with
   dental care and clinic-related questions. How can I help with your
   dental needs today?"

═══ TOOL CALLING ═══
When the user's request maps to a concrete action, call the appropriate tool.
Always confirm details with the user BEFORE booking or cancelling:
  • For booking: confirm name, phone, date, time, and service.
  • For cancellation: confirm date, time, and phone.
  • If any required field is missing, ask the user for it — do NOT guess.

After receiving tool results, present them in a clear, human-friendly way.
Never show raw JSON to the user.

═══ CONVERSATION STYLE ═══
• Be warm, concise, and helpful.
• Use short sentences suitable for voice conversation.
• Offer next steps (e.g., "Would you like to book an appointment?").
• When listing services or slots, format them clearly.
• Keep responses under 3-4 sentences for voice readability.
"""


# ── Tool execution registry ──────────────────────────────────

def _execute_tool(name: str, args: dict) -> dict:
    """Execute a tool call and return the result dict."""
    try:
        handler = _TOOL_HANDLERS.get(name)
        if not handler:
            return {"error": f"Unknown tool: {name}"}
        return handler(**args)
    except Exception as exc:
        return {"error": str(exc)}


def _check_available_slots(date: str) -> dict:
    booked = list(appointments_collection.find({"date": date, "status": "scheduled"}))
    booked_times = [b["time"] for b in booked]
    all_slots = [
        "09:00 AM", "09:30 AM", "10:00 AM", "10:30 AM",
        "11:00 AM", "11:30 AM", "12:00 PM",
        "02:00 PM", "02:30 PM", "03:00 PM", "03:30 PM",
        "04:00 PM", "04:30 PM", "05:00 PM",
    ]
    available = [s for s in all_slots if s not in booked_times]
    return {"date": date, "available_slots": available, "total_available": len(available)}


def _book_appointment(
    patient_name: str,
    patient_phone: str,
    date: str,
    time: str,
    service: str = None,
) -> dict:
    # Check slot availability
    existing = appointments_collection.find_one(
        {"date": date, "time": time, "status": "scheduled"}
    )
    if existing:
        return {"error": f"The {time} slot on {date} is already booked. Please choose another time."}

    now = datetime.now(timezone.utc)
    appt = {
        "patient_name": patient_name,
        "patient_phone": patient_phone,
        "date": date,
        "time": time,
        "service": service or "General Checkup",
        "status": "scheduled",
        "notes": "",
        "created_at": now,
        "updated_at": now,
    }
    result = appointments_collection.insert_one(appt)

    # Upsert patient record
    patients_collection.update_one(
        {"phone": patient_phone},
        {"$set": {"name": patient_name, "phone": patient_phone, "updated_at": now},
         "$setOnInsert": {"created_at": now}},
        upsert=True,
    )

    return {
        "message": "Appointment booked successfully",
        "appointment_id": str(result.inserted_id),
        "patient_name": patient_name,
        "date": date,
        "time": time,
        "service": appt["service"],
    }


def _cancel_appointment(date: str, time: str, patient_phone: str = None) -> dict:
    query = {"date": date, "time": time, "status": "scheduled"}
    if patient_phone:
        query["patient_phone"] = patient_phone

    result = appointments_collection.update_one(
        query, {"$set": {"status": "cancelled", "updated_at": datetime.now(timezone.utc)}}
    )
    if result.modified_count == 0:
        return {"error": "No matching scheduled appointment found for that date and time."}
    return {"message": f"Appointment on {date} at {time} has been cancelled."}


def _reschedule_appointment(
    old_date: str, old_time: str, new_date: str, new_time: str,
    patient_phone: str = None,
) -> dict:
    # Check new slot
    conflict = appointments_collection.find_one(
        {"date": new_date, "time": new_time, "status": "scheduled"}
    )
    if conflict:
        return {"error": f"The {new_time} slot on {new_date} is not available."}

    query = {"date": old_date, "time": old_time, "status": "scheduled"}
    if patient_phone:
        query["patient_phone"] = patient_phone

    result = appointments_collection.update_one(
        query,
        {"$set": {
            "date": new_date, "time": new_time,
            "updated_at": datetime.now(timezone.utc),
        }},
    )
    if result.modified_count == 0:
        return {"error": "No matching appointment found to reschedule."}
    return {"message": f"Appointment rescheduled to {new_date} at {new_time}."}


def _get_dental_services(category: str = None) -> dict:
    query = {"is_active": True}
    if category:
        query["category"] = {"$regex": category, "$options": "i"}
    services = list(dental_services_collection.find(query))
    result = []
    for s in services:
        result.append({
            "name": s["name"],
            "category": s["category"],
            "description": s["description"],
            "duration_minutes": s["duration_minutes"],
            "price": f"${s['price']:.2f}",
        })
    return {"services": result, "total": len(result)}


def _get_clinic_info() -> dict:
    return {
        "name": "SmileCare Dental Clinic",
        "timings": "Monday–Friday 9:00 AM – 5:00 PM, Saturday 9:00 AM – 3:00 PM",
        "location": "123 Dental Avenue, Suite 200, Mysore, KA 570001",
        "phone": "+1-555-0100",
        "email": "hello@smilecare.com",
        "emergency": "For dental emergencies, call +1-555-0199 (24/7)",
    }


def _get_patient_appointments(patient_phone: str) -> dict:
    appts = list(
        appointments_collection.find({"patient_phone": patient_phone})
        .sort("date", -1).limit(10)
    )
    results = []
    for a in appts:
        results.append({
            "date": a["date"],
            "time": a["time"],
            "service": a.get("service", "N/A"),
            "status": a.get("status", "scheduled"),
        })
    return {"appointments": results, "total": len(results)}


def _get_dentists(specialization: str = None) -> dict:
    query = {}
    if specialization:
        query["specialization"] = {"$regex": specialization, "$options": "i"}
    dentists = list(dentists_collection.find(query))
    results = []
    for d in dentists:
        results.append({
            "name": d["name"],
            "specialization": d["specialization"],
            "available_days": d.get("available_days", []),
            "working_hours": d.get("working_hours", {}),
        })
    return {"dentists": results, "total": len(results)}


_TOOL_HANDLERS = {
    "check_available_slots": _check_available_slots,
    "book_appointment": _book_appointment,
    "cancel_appointment": _cancel_appointment,
    "reschedule_appointment": _reschedule_appointment,
    "get_dental_services": _get_dental_services,
    "get_clinic_info": _get_clinic_info,
    "get_patient_appointments": _get_patient_appointments,
    "get_dentists": _get_dentists,
}


# ── Public API ───────────────────────────────────────────────

def _build_contents(user_message: str, history: list | None = None) -> list:
    """Build Gemini contents list from conversation history + new message."""
    contents = []
    if history:
        for msg in history:
            contents.append(
                types.Content(
                    role="user" if msg["role"] == "user" else "model",
                    parts=[types.Part(text=msg["content"])],
                )
            )
    contents.append(
        types.Content(role="user", parts=[types.Part(text=user_message)])
    )
    return contents


def process_message(user_message: str, history: list | None = None) -> str:
    """Synchronous, non-streaming agent call (for REST endpoints)."""
    contents = _build_contents(user_message, history)
    return generate_with_tools(SYSTEM_PROMPT, contents, _execute_tool)


async def process_message_stream(
    user_message: str, history: list | None = None
) -> AsyncGenerator[str, None]:
    """
    Async generator that yields text chunks for WebSocket streaming.
    Handles tool-calling internally before streaming the final answer.
    """
    contents = _build_contents(user_message, history)
    full_text = ""
    async for chunk in agenerate_stream_with_tools(SYSTEM_PROMPT, contents, _execute_tool):
        full_text += chunk
        yield chunk
