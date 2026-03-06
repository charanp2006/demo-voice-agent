"""
Pydantic schemas for the SmileCare Dental Clinic system.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── Patient ──────────────────────────────────────────────────
class EmergencyContact(BaseModel):
    name: str
    phone: str


class PatientCreate(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    medical_history: Optional[str] = None
    allergies: list[str] = Field(default_factory=list)
    emergency_contact: Optional[EmergencyContact] = None


class PatientOut(PatientCreate):
    id: str = Field(alias="_id")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── Dentist ──────────────────────────────────────────────────
class WorkingHours(BaseModel):
    start: str
    end: str


class DentistOut(BaseModel):
    id: str = Field(alias="_id")
    name: str
    specialization: str
    phone: Optional[str] = None
    email: Optional[str] = None
    available_days: list[str] = Field(default_factory=list)
    working_hours: Optional[WorkingHours] = None
    created_at: Optional[datetime] = None


# ── Dental Service ───────────────────────────────────────────
class DentalServiceOut(BaseModel):
    id: str = Field(alias="_id")
    name: str
    category: str
    description: str
    duration_minutes: int
    price: float
    is_active: bool = True
    created_at: Optional[datetime] = None


# ── Appointment ──────────────────────────────────────────────
class AppointmentCreate(BaseModel):
    patient_name: str
    patient_phone: str
    date: str  # YYYY-MM-DD
    time: str  # e.g. "10:00 AM"
    service: Optional[str] = None
    dentist_name: Optional[str] = None
    notes: Optional[str] = None


class AppointmentOut(BaseModel):
    id: str = Field(alias="_id")
    patient_name: str
    patient_phone: str
    date: str
    time: str
    service: Optional[str] = None
    dentist_name: Optional[str] = None
    status: str = "scheduled"
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── Treatment Record ────────────────────────────────────────
class TreatmentRecordCreate(BaseModel):
    patient_phone: str
    appointment_id: Optional[str] = None
    dentist_name: Optional[str] = None
    service_name: Optional[str] = None
    diagnosis: Optional[str] = None
    treatment_notes: Optional[str] = None
    prescription: Optional[str] = None
    follow_up_date: Optional[str] = None


class TreatmentRecordOut(TreatmentRecordCreate):
    id: str = Field(alias="_id")
    created_at: Optional[datetime] = None


# ── Conversation / Chat ─────────────────────────────────────
class ConversationOut(BaseModel):
    id: str = Field(alias="_id")
    session_id: str
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    status: str = "active"


class ChatMessageOut(BaseModel):
    id: str = Field(alias="_id")
    session_id: str
    role: str
    content: str
    message_type: str = "text"
    created_at: Optional[datetime] = None


# ── WebSocket Protocol Messages ──────────────────────────────
class WSClientMessage(BaseModel):
    """Messages sent from client → server."""
    type: str  # start_conversation | end_of_speech | stop_conversation


class WSServerMessage(BaseModel):
    """Messages sent from server → client."""
    type: str  # partial_transcript | final_transcript | assistant_stream | assistant_done | error
    text: Optional[str] = None
    session_id: Optional[str] = None


# ── Misc ─────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str


class ClinicInfoOut(BaseModel):
    name: str
    timings: str
    location: str
    phone: str
    email: str
    services_count: int
    dentists_count: int
