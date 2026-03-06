"""
REST API routes for the SmileCare Dental Clinic.

These endpoints are also called internally by the agent's tool functions,
and are exposed for dashboard / admin use.
"""

from datetime import datetime, timezone
from fastapi import APIRouter
from app.database import (
    appointments_collection,
    dental_services_collection,
    dentists_collection,
    patients_collection,
    treatment_records_collection,
)

router = APIRouter(prefix="/clinic")


# ── Slots ────────────────────────────────────────────────────

@router.get("/slots")
def check_slots(date: str):
    booked = appointments_collection.find({"date": date, "status": "scheduled"})
    booked_times = [b["time"] for b in booked]
    all_slots = [
        "09:00 AM", "09:30 AM", "10:00 AM", "10:30 AM",
        "11:00 AM", "11:30 AM", "12:00 PM",
        "02:00 PM", "02:30 PM", "03:00 PM", "03:30 PM",
        "04:00 PM", "04:30 PM", "05:00 PM",
    ]
    available = [s for s in all_slots if s not in booked_times]
    return {"date": date, "available_slots": available, "total_available": len(available)}


# ── Appointments ─────────────────────────────────────────────

@router.post("/book")
def book_appointment(data: dict):
    required = ["patient_name", "patient_phone", "date", "time"]
    for field in required:
        if field not in data or not data[field]:
            return {"error": f"Missing required field: {field}"}

    existing = appointments_collection.find_one(
        {"date": data["date"], "time": data["time"], "status": "scheduled"}
    )
    if existing:
        return {"error": "That time slot is already booked"}

    now = datetime.now(timezone.utc)
    appointment = {
        "patient_name": data["patient_name"],
        "patient_phone": data["patient_phone"],
        "date": data["date"],
        "time": data["time"],
        "service": data.get("service", "General Checkup"),
        "dentist_name": data.get("dentist_name"),
        "status": "scheduled",
        "notes": data.get("notes", ""),
        "created_at": now,
        "updated_at": now,
    }
    result = appointments_collection.insert_one(appointment)
    appointment["_id"] = str(result.inserted_id)

    # Upsert patient
    patients_collection.update_one(
        {"phone": data["patient_phone"]},
        {
            "$set": {"name": data["patient_name"], "phone": data["patient_phone"], "updated_at": now},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )

    return {"message": "Appointment booked", "appointment": appointment}


@router.post("/cancel")
def cancel_appointment(data: dict):
    if "date" not in data or "time" not in data:
        return {"error": "Date and time required to cancel"}

    result = appointments_collection.update_one(
        {"date": data["date"], "time": data["time"], "status": "scheduled"},
        {"$set": {"status": "cancelled", "updated_at": datetime.now(timezone.utc)}},
    )
    if result.modified_count == 0:
        return {"error": "No matching appointment found"}
    return {"message": "Appointment cancelled successfully"}


# ── Services ─────────────────────────────────────────────────

@router.get("/services")
def list_services(category: str = None):
    query = {"is_active": True}
    if category:
        query["category"] = {"$regex": category, "$options": "i"}
    services = list(dental_services_collection.find(query))
    for s in services:
        s["_id"] = str(s["_id"])
    return {"services": services, "total": len(services)}


# ── Dentists ─────────────────────────────────────────────────

@router.get("/dentists")
def list_dentists(specialization: str = None):
    query = {}
    if specialization:
        query["specialization"] = {"$regex": specialization, "$options": "i"}
    dentists = list(dentists_collection.find(query))
    for d in dentists:
        d["_id"] = str(d["_id"])
    return {"dentists": dentists, "total": len(dentists)}


# ── Patients ─────────────────────────────────────────────────

@router.get("/patients")
def list_patients():
    patients = list(patients_collection.find().limit(100))
    for p in patients:
        p["_id"] = str(p["_id"])
    return {"patients": patients}


# ── Clinic Info ──────────────────────────────────────────────

@router.get("/info")
def clinic_info():
    return {
        "name": "SmileCare Dental Clinic",
        "timings": "Monday–Friday 9:00 AM – 5:00 PM, Saturday 9:00 AM – 3:00 PM",
        "location": "123 Dental Avenue, Suite 200, Mysore, KA 570001",
        "phone": "+1-555-0100",
        "email": "hello@smilecare.com",
        "services_count": dental_services_collection.count_documents({"is_active": True}),
        "dentists_count": dentists_collection.count_documents({}),
    }


# ── Dashboard ────────────────────────────────────────────────

@router.get("/dashboard")
def dashboard():
    appointments = list(
        appointments_collection.find().sort("created_at", -1).limit(50)
    )
    for a in appointments:
        a["_id"] = str(a["_id"])
    return {"appointments": appointments}


@router.get("/dashboard/stats")
def dashboard_stats():
    total = appointments_collection.count_documents({})
    scheduled = appointments_collection.count_documents({"status": "scheduled"})
    cancelled = appointments_collection.count_documents({"status": "cancelled"})
    completed = appointments_collection.count_documents({"status": "completed"})
    patients = patients_collection.count_documents({})
    return {
        "total_appointments": total,
        "scheduled": scheduled,
        "cancelled": cancelled,
        "completed": completed,
        "total_patients": patients,
    }
