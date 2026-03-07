"""
LLM service – Dual-backend: Groq (Llama 3) and Google Gemini with function-calling.

Active backend: **Groq Llama 3** (fastest inference).
Gemini is kept but commented out — uncomment to switch / benchmark.

Exposes an async generator that yields text chunks for real-time WebSocket streaming.
"""

import json
import os
import asyncio
from typing import AsyncGenerator

from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# ── Active LLM: Groq (Llama 3) ──────────────────────────────

groq_llm_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
GROQ_MODEL_ID = "llama-3.3-70b-versatile"

# ── Tool definitions (JSON Schema for Groq function-calling) ─

GROQ_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_available_slots",
            "description": "Check available appointment time slots for a given date at the dental clinic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "The date to check in YYYY-MM-DD format."},
                },
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Book a dental appointment for a patient.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string", "description": "Full name of the patient."},
                    "patient_phone": {"type": "string", "description": "Phone number of the patient."},
                    "date": {"type": "string", "description": "Appointment date YYYY-MM-DD."},
                    "time": {"type": "string", "description": "Appointment time, e.g. '10:00 AM'."},
                    "service": {"type": "string", "description": "Dental service requested (optional)."},
                },
                "required": ["patient_name", "patient_phone", "date", "time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_appointment",
            "description": "Cancel an existing dental appointment by date and time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Appointment date YYYY-MM-DD."},
                    "time": {"type": "string", "description": "Appointment time, e.g. '10:00 AM'."},
                    "patient_phone": {"type": "string", "description": "Patient phone for verification."},
                },
                "required": ["date", "time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reschedule_appointment",
            "description": "Reschedule an existing dental appointment to a new date/time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "old_date": {"type": "string", "description": "Current appointment date YYYY-MM-DD."},
                    "old_time": {"type": "string", "description": "Current appointment time."},
                    "new_date": {"type": "string", "description": "New appointment date YYYY-MM-DD."},
                    "new_time": {"type": "string", "description": "New appointment time."},
                    "patient_phone": {"type": "string", "description": "Patient phone for verification."},
                },
                "required": ["old_date", "old_time", "new_date", "new_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dental_services",
            "description": "Retrieve the list of dental services offered by the clinic with prices, categories, and durations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Optional category filter."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_clinic_info",
            "description": "Get dental clinic information including name, hours, location, and contact details.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_patient_appointments",
            "description": "Look up a patient's upcoming or past appointments by phone number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_phone": {"type": "string", "description": "Patient's phone number."},
                },
                "required": ["patient_phone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dentists",
            "description": "Get information about dentists available at the clinic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "specialization": {"type": "string", "description": "Optional specialization filter."},
                },
            },
        },
    },
]


# ── Groq: Non-streaming with tool loop ───────────────────────

def generate_with_tools(
    system_prompt: str,
    contents: list,
    execute_tool_fn,
) -> str:
    """Non-streaming Groq call with tool-calling loop (up to 3 rounds)."""
    messages = [{"role": "system", "content": system_prompt}]
    # Convert contents to Groq message format
    for c in contents:
        if isinstance(c, dict):
            messages.append(c)
        else:
            # Gemini Content object — extract role + text
            role = "user" if getattr(c, "role", "user") == "user" else "assistant"
            text = ""
            for p in getattr(c, "parts", []):
                if hasattr(p, "text") and p.text:
                    text += p.text
            if text:
                messages.append({"role": role, "content": text})

    for _ in range(3):
        response = groq_llm_client.chat.completions.create(
            model=GROQ_MODEL_ID,
            messages=messages,
            tools=GROQ_TOOLS,
            tool_choice="auto",
            temperature=0.7,
        )
        choice = response.choices[0]

        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            messages.append(choice.message)
            for tc in choice.message.tool_calls:
                fn_name = tc.function.name
                fn_args = json.loads(tc.function.arguments)
                result = execute_tool_fn(fn_name, fn_args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result),
                })
            continue

        return choice.message.content or ""

    return response.choices[0].message.content or ""


# ── Groq: Streaming with tool loop ───────────────────────────

def generate_stream_with_tools(
    system_prompt: str,
    contents: list,
    execute_tool_fn,
):
    """Generator: resolve tool calls first, then stream final text via Groq."""
    messages = [{"role": "system", "content": system_prompt}]
    for c in contents:
        if isinstance(c, dict):
            messages.append(c)
        else:
            role = "user" if getattr(c, "role", "user") == "user" else "assistant"
            text = ""
            for p in getattr(c, "parts", []):
                if hasattr(p, "text") and p.text:
                    text += p.text
            if text:
                messages.append({"role": role, "content": text})

    # Phase 1: resolve tool calls (non-streaming)
    for _ in range(3):
        response = groq_llm_client.chat.completions.create(
            model=GROQ_MODEL_ID,
            messages=messages,
            tools=GROQ_TOOLS,
            tool_choice="auto",
            temperature=0.7,
        )
        choice = response.choices[0]

        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            messages.append(choice.message)
            for tc in choice.message.tool_calls:
                fn_name = tc.function.name
                fn_args = json.loads(tc.function.arguments)
                result = execute_tool_fn(fn_name, fn_args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result),
                })
            continue
        break

    # Phase 2: stream final response
    stream = groq_llm_client.chat.completions.create(
        model=GROQ_MODEL_ID,
        messages=messages,
        tools=GROQ_TOOLS,
        tool_choice="none",
        temperature=0.7,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content


async def agenerate_stream_with_tools(
    system_prompt: str,
    contents: list,
    execute_tool_fn,
) -> AsyncGenerator[str, None]:
    """Async wrapper – runs the sync streaming generator in a thread-safe way."""
    def _run_sync():
        chunks = []
        for chunk in generate_stream_with_tools(system_prompt, contents, execute_tool_fn):
            chunks.append(chunk)
        return chunks

    all_chunks = await asyncio.to_thread(_run_sync)
    for chunk in all_chunks:
        yield chunk


# ═══════════════════════════════════════════════════════════════
# ── COMMENTED OUT: Google Gemini backend ──────────────────────
# Uncomment this section and comment out the Groq section above
# to switch to Gemini for benchmarking.
# ═══════════════════════════════════════════════════════════════
#
# from google import genai
# from google.genai import types
#
# gemini_client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
# MODEL_ID = "gemini-2.5-flash"
#
# check_slots_fn = types.FunctionDeclaration(
#     name="check_available_slots",
#     description="Check available appointment time slots for a given date at the dental clinic.",
#     parameters=types.Schema(
#         type=types.Type.OBJECT,
#         properties={
#             "date": types.Schema(type=types.Type.STRING, description="The date to check in YYYY-MM-DD format."),
#         },
#         required=["date"],
#     ),
# )
# book_appointment_fn = types.FunctionDeclaration(
#     name="book_appointment",
#     description="Book a dental appointment for a patient.",
#     parameters=types.Schema(
#         type=types.Type.OBJECT,
#         properties={
#             "patient_name": types.Schema(type=types.Type.STRING, description="Full name of the patient."),
#             "patient_phone": types.Schema(type=types.Type.STRING, description="Phone number of the patient."),
#             "date": types.Schema(type=types.Type.STRING, description="Appointment date YYYY-MM-DD."),
#             "time": types.Schema(type=types.Type.STRING, description="Appointment time, e.g. '10:00 AM'."),
#             "service": types.Schema(type=types.Type.STRING, description="Dental service requested (optional)."),
#         },
#         required=["patient_name", "patient_phone", "date", "time"],
#     ),
# )
# cancel_appointment_fn = types.FunctionDeclaration(
#     name="cancel_appointment",
#     description="Cancel an existing dental appointment by date and time.",
#     parameters=types.Schema(
#         type=types.Type.OBJECT,
#         properties={
#             "date": types.Schema(type=types.Type.STRING, description="Appointment date YYYY-MM-DD."),
#             "time": types.Schema(type=types.Type.STRING, description="Appointment time, e.g. '10:00 AM'."),
#             "patient_phone": types.Schema(type=types.Type.STRING, description="Patient phone for verification."),
#         },
#         required=["date", "time"],
#     ),
# )
# reschedule_appointment_fn = types.FunctionDeclaration(
#     name="reschedule_appointment",
#     description="Reschedule an existing dental appointment to a new date/time.",
#     parameters=types.Schema(
#         type=types.Type.OBJECT,
#         properties={
#             "old_date": types.Schema(type=types.Type.STRING, description="Current appointment date YYYY-MM-DD."),
#             "old_time": types.Schema(type=types.Type.STRING, description="Current appointment time."),
#             "new_date": types.Schema(type=types.Type.STRING, description="New appointment date YYYY-MM-DD."),
#             "new_time": types.Schema(type=types.Type.STRING, description="New appointment time."),
#             "patient_phone": types.Schema(type=types.Type.STRING, description="Patient phone for verification."),
#         },
#         required=["old_date", "old_time", "new_date", "new_time"],
#     ),
# )
# get_dental_services_fn = types.FunctionDeclaration(
#     name="get_dental_services",
#     description="Retrieve the list of dental services offered by the clinic.",
#     parameters=types.Schema(
#         type=types.Type.OBJECT,
#         properties={
#             "category": types.Schema(type=types.Type.STRING, description="Optional category filter."),
#         },
#     ),
# )
# get_clinic_info_fn = types.FunctionDeclaration(
#     name="get_clinic_info",
#     description="Get dental clinic information.",
#     parameters=types.Schema(type=types.Type.OBJECT, properties={}),
# )
# get_patient_appointments_fn = types.FunctionDeclaration(
#     name="get_patient_appointments",
#     description="Look up a patient's upcoming or past appointments by phone number.",
#     parameters=types.Schema(
#         type=types.Type.OBJECT,
#         properties={
#             "patient_phone": types.Schema(type=types.Type.STRING, description="Patient's phone number."),
#         },
#         required=["patient_phone"],
#     ),
# )
# get_dentists_fn = types.FunctionDeclaration(
#     name="get_dentists",
#     description="Get information about dentists available at the clinic.",
#     parameters=types.Schema(
#         type=types.Type.OBJECT,
#         properties={
#             "specialization": types.Schema(type=types.Type.STRING, description="Optional specialization filter."),
#         },
#     ),
# )
# clinic_tools = types.Tool(function_declarations=[
#     check_slots_fn, book_appointment_fn, cancel_appointment_fn,
#     reschedule_appointment_fn, get_dental_services_fn, get_clinic_info_fn,
#     get_patient_appointments_fn, get_dentists_fn,
# ])
#
# def _build_config(system_prompt):
#     return types.GenerateContentConfig(
#         system_instruction=system_prompt, tools=[clinic_tools], temperature=0.7)
#
# def generate_with_tools(system_prompt, contents, execute_tool_fn):
#     config = _build_config(system_prompt)
#     for _ in range(3):
#         response = gemini_client.models.generate_content(
#             model=MODEL_ID, contents=contents, config=config)
#         candidate = response.candidates[0]
#         parts = candidate.content.parts
#         fn_calls = [p for p in parts if p.function_call]
#         if not fn_calls:
#             return candidate.content.parts[0].text or ""
#         contents.append(candidate.content)
#         for part in fn_calls:
#             fc = part.function_call
#             result = execute_tool_fn(fc.name, dict(fc.args))
#             contents.append(types.Content(role="tool", parts=[types.Part(
#                 function_response=types.FunctionResponse(
#                     name=fc.name, response={"result": result}))]))
#     return response.candidates[0].content.parts[0].text or ""
#
# def generate_stream_with_tools(system_prompt, contents, execute_tool_fn):
#     config = _build_config(system_prompt)
#     for _ in range(3):
#         response = gemini_client.models.generate_content(
#             model=MODEL_ID, contents=contents, config=config)
#         candidate = response.candidates[0]
#         parts = candidate.content.parts
#         fn_calls = [p for p in parts if p.function_call]
#         if not fn_calls:
#             break
#         contents.append(candidate.content)
#         for part in fn_calls:
#             fc = part.function_call
#             result = execute_tool_fn(fc.name, dict(fc.args))
#             contents.append(types.Content(role="tool", parts=[types.Part(
#                 function_response=types.FunctionResponse(
#                     name=fc.name, response={"result": result}))]))
#     else:
#         text = response.candidates[0].content.parts[0].text or ""
#         yield text
#         return
#     stream = gemini_client.models.generate_content_stream(
#         model=MODEL_ID, contents=contents, config=config)
#     for chunk in stream:
#         if chunk.text:
#             yield chunk.text
#
# async def agenerate_stream_with_tools(system_prompt, contents, execute_tool_fn):
#     def _run_sync():
#         return list(generate_stream_with_tools(system_prompt, contents, execute_tool_fn))
#     all_chunks = await asyncio.to_thread(_run_sync)
#     for chunk in all_chunks:
#         yield chunk
