from fastapi import APIRouter
from datetime import datetime

router = APIRouter(prefix="/clinic")

appointments = []

@router.get("/slots")
def check_slots(date: str):
    return {
        "available_slots": ["5 PM", "6 PM", "7 PM"]
    }

@router.post("/book")
def book_appointment(data: dict):
    appointment = {
        "id" : len(appointments) + 1,
        **data
    }
    appointments.append(appointment)
    return {"message": "Appointment booked successfully", "appointment": appointment}

@router.post("/cancel")
def cancel_appointment(data: dict):
    return {"message": "Appointment cancelled successfully"}

@router.get("/info")
def clinic_info():
    return {
        "name": "Simple Clinic",
        "timings": "9 AM - 6 PM",
        "location": "Mysore"
    }