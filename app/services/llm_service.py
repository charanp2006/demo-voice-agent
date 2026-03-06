"""
LLM service – Streaming responses via Google Gemini with function-calling support.

Exposes an async generator that yields text chunks for real-time WebSocket streaming.
"""

import os
import asyncio
from typing import AsyncGenerator

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

gemini_client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

MODEL_ID = "gemini-2.5-flash"


# ── Tool / Function Declarations ─────────────────────────────

check_slots_fn = types.FunctionDeclaration(
    name="check_available_slots",
    description="Check available appointment time slots for a given date at the dental clinic.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "date": types.Schema(
                type=types.Type.STRING,
                description="The date to check in YYYY-MM-DD format.",
            ),
        },
        required=["date"],
    ),
)

book_appointment_fn = types.FunctionDeclaration(
    name="book_appointment",
    description="Book a dental appointment for a patient.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "patient_name": types.Schema(type=types.Type.STRING, description="Full name of the patient."),
            "patient_phone": types.Schema(type=types.Type.STRING, description="Phone number of the patient."),
            "date": types.Schema(type=types.Type.STRING, description="Appointment date YYYY-MM-DD."),
            "time": types.Schema(type=types.Type.STRING, description="Appointment time, e.g. '10:00 AM'."),
            "service": types.Schema(type=types.Type.STRING, description="Dental service requested (optional)."),
        },
        required=["patient_name", "patient_phone", "date", "time"],
    ),
)

cancel_appointment_fn = types.FunctionDeclaration(
    name="cancel_appointment",
    description="Cancel an existing dental appointment by date and time.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "date": types.Schema(type=types.Type.STRING, description="Appointment date YYYY-MM-DD."),
            "time": types.Schema(type=types.Type.STRING, description="Appointment time, e.g. '10:00 AM'."),
            "patient_phone": types.Schema(type=types.Type.STRING, description="Patient phone for verification."),
        },
        required=["date", "time"],
    ),
)

reschedule_appointment_fn = types.FunctionDeclaration(
    name="reschedule_appointment",
    description="Reschedule an existing dental appointment to a new date/time.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "old_date": types.Schema(type=types.Type.STRING, description="Current appointment date YYYY-MM-DD."),
            "old_time": types.Schema(type=types.Type.STRING, description="Current appointment time."),
            "new_date": types.Schema(type=types.Type.STRING, description="New appointment date YYYY-MM-DD."),
            "new_time": types.Schema(type=types.Type.STRING, description="New appointment time."),
            "patient_phone": types.Schema(type=types.Type.STRING, description="Patient phone for verification."),
        },
        required=["old_date", "old_time", "new_date", "new_time"],
    ),
)

get_dental_services_fn = types.FunctionDeclaration(
    name="get_dental_services",
    description="Retrieve the list of dental services offered by the clinic with prices, categories, and durations.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "category": types.Schema(
                type=types.Type.STRING,
                description="Optional category filter (Preventive, Restorative, Cosmetic, Surgical, etc.).",
            ),
        },
    ),
)

get_clinic_info_fn = types.FunctionDeclaration(
    name="get_clinic_info",
    description="Get dental clinic information including name, hours, location, and contact details.",
    parameters=types.Schema(type=types.Type.OBJECT, properties={}),
)

get_patient_appointments_fn = types.FunctionDeclaration(
    name="get_patient_appointments",
    description="Look up a patient's upcoming or past appointments by phone number.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "patient_phone": types.Schema(type=types.Type.STRING, description="Patient's phone number."),
        },
        required=["patient_phone"],
    ),
)

get_dentists_fn = types.FunctionDeclaration(
    name="get_dentists",
    description="Get information about dentists available at the clinic.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "specialization": types.Schema(
                type=types.Type.STRING,
                description="Optional specialization filter.",
            ),
        },
    ),
)

clinic_tools = types.Tool(
    function_declarations=[
        check_slots_fn,
        book_appointment_fn,
        cancel_appointment_fn,
        reschedule_appointment_fn,
        get_dental_services_fn,
        get_clinic_info_fn,
        get_patient_appointments_fn,
        get_dentists_fn,
    ]
)


# ── Sync helpers for Gemini ──────────────────────────────────

def _build_config(system_prompt: str) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=[clinic_tools],
        temperature=0.7,
    )


def generate_with_tools(
    system_prompt: str,
    contents: list,
    execute_tool_fn,
) -> str:
    """Non-streaming call with tool-calling loop (up to 3 rounds)."""
    config = _build_config(system_prompt)

    for _ in range(3):
        response = gemini_client.models.generate_content(
            model=MODEL_ID,
            contents=contents,
            config=config,
        )

        candidate = response.candidates[0]
        parts = candidate.content.parts

        # Check for function calls
        fn_calls = [p for p in parts if p.function_call]
        if not fn_calls:
            return candidate.content.parts[0].text or ""

        # Execute each function call and collect results
        contents.append(candidate.content)
        for part in fn_calls:
            fc = part.function_call
            result = execute_tool_fn(fc.name, dict(fc.args))
            contents.append(
                types.Content(
                    role="tool",
                    parts=[types.Part(function_response=types.FunctionResponse(
                        name=fc.name,
                        response={"result": result},
                    ))],
                )
            )

    # Fallback: return whatever text we got
    return response.candidates[0].content.parts[0].text or ""


def generate_stream_with_tools(
    system_prompt: str,
    contents: list,
    execute_tool_fn,
):
    """
    Generator that handles tool-calling first (non-streaming), then streams
    the final text response.  Yields text chunks.
    """
    config = _build_config(system_prompt)

    # Phase 1 – resolve any tool calls (non-streaming)
    for _ in range(3):
        response = gemini_client.models.generate_content(
            model=MODEL_ID,
            contents=contents,
            config=config,
        )

        candidate = response.candidates[0]
        parts = candidate.content.parts
        fn_calls = [p for p in parts if p.function_call]

        if not fn_calls:
            # No tool call – re-run as streaming
            break

        contents.append(candidate.content)
        for part in fn_calls:
            fc = part.function_call
            result = execute_tool_fn(fc.name, dict(fc.args))
            contents.append(
                types.Content(
                    role="tool",
                    parts=[types.Part(function_response=types.FunctionResponse(
                        name=fc.name,
                        response={"result": result},
                    ))],
                )
            )
    else:
        # After 3 rounds, just yield whatever we have
        text = response.candidates[0].content.parts[0].text or ""
        yield text
        return

    # Phase 2 – stream the final response
    stream = gemini_client.models.generate_content_stream(
        model=MODEL_ID,
        contents=contents,
        config=config,
    )
    for chunk in stream:
        if chunk.text:
            yield chunk.text


async def agenerate_stream_with_tools(
    system_prompt: str,
    contents: list,
    execute_tool_fn,
) -> AsyncGenerator[str, None]:
    """Async wrapper – runs the sync streaming generator in a thread-safe way."""

    # We collect from the sync generator in a thread
    def _run_sync():
        chunks = []
        for chunk in generate_stream_with_tools(system_prompt, contents, execute_tool_fn):
            chunks.append(chunk)
        return chunks

    all_chunks = await asyncio.to_thread(_run_sync)
    for chunk in all_chunks:
        yield chunk
