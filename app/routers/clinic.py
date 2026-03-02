from fastapi import APIRouter
from datetime import datetime, timezone
from app.database import appointments_collection

router = APIRouter(prefix="/clinic")

appointments = []

@router.get("/slots")
def check_slots(date: str):
    # Query database for appointments on the specified date
    booked = appointments_collection.find({"date": date})
    # Extract times from booked appointments
    booked_times = [b["time"] for b in booked]
    # Define all available time slots
    all_slots = ["5 PM", "6 PM", "7 PM"]
    # Filter out booked slots
    available = [slot for slot in all_slots if slot not in booked_times]
    return {"available_slots": available}

@router.post("/book")
def book_appointment(data: dict):
    # Check for required fields in request
    required_fields = ["name", "phone", "date", "time"]
    for field in required_fields:
        if field not in data or not data[field]:
            return {"error": f"Missing required field: {field}"}

    # Create appointment object with provided data
    appointment = {
        "name": data["name"],
        "phone": data["phone"],
        "date": data["date"],
        "time": data["time"]
    }

    # Check if slot is already booked
    existing = appointments_collection.find_one({
        "date": data["date"],
        "time": data["time"]
    })

    if existing:
        return {"error": "Slot already booked"}

    # Insert appointment into database
    result = appointments_collection.insert_one(appointment)
    # Add MongoDB generated ID to response
    appointment["_id"] = str(result.inserted_id)
    # Add creation timestamp
    appointment["created_at"] = datetime.now(timezone.utc)
    
    return {"message": "Appointment booked", "appointment": appointment}

@router.post("/cancel")
def cancel_appointment(data: dict):

    if "date" not in data or "time" not in data:
        return {"error": "Date and time required to cancel"}

    result = appointments_collection.delete_one({
        "date": data["date"],
        "time": data["time"]
    })

    if result.deleted_count == 0:
        return {"error": "No matching appointment found"}

    return {"message": "Appointment cancelled successfully"}

@router.get("/info")
def clinic_info():
    # Return clinic details
    return {
        "name": "Simple Clinic",
        "timings": "9 AM - 6 PM",
        "location": "Mysore"
    }

@router.get("/dashboard")
def dashboard():
    # Fetch all appointments and convert IDs to strings for JSON serialization
    appointments = list(appointments_collection.find())
    for appt in appointments:
        appt["_id"] = str(appt["_id"])
    return appointments
