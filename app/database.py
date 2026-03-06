from pymongo import MongoClient, ASCENDING
import os
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI"))

db = client["dental_clinic_db"]

# ── Collections ──────────────────────────────────────────────
patients_collection = db["patients"]
dentists_collection = db["dentists"]
dental_services_collection = db["dental_services"]
appointments_collection = db["appointments"]
treatment_records_collection = db["treatment_records"]
conversations_collection = db["conversations"]
chat_messages_collection = db["chat_messages"]

# ── Indexes ──────────────────────────────────────────────────
patients_collection.create_index("phone", unique=True, sparse=True)
appointments_collection.create_index([("date", ASCENDING), ("time", ASCENDING)])
appointments_collection.create_index("patient_phone")
appointments_collection.create_index("status")
chat_messages_collection.create_index("session_id")
conversations_collection.create_index("session_id", unique=True)
dentists_collection.create_index("name")
dental_services_collection.create_index("name")
treatment_records_collection.create_index("patient_phone")


# ── Seed Data ────────────────────────────────────────────────
def seed_initial_data():
    """Populate the database with starter dental-clinic data (idempotent)."""

    now = datetime.now(timezone.utc)

    # --- Dentists ---
    if dentists_collection.count_documents({}) == 0:
        dentists_collection.insert_many([
            {
                "name": "Dr. Sarah Johnson",
                "specialization": "General Dentistry",
                "phone": "+1-555-0101",
                "email": "sarah.johnson@smilecare.com",
                "available_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
                "working_hours": {"start": "09:00", "end": "17:00"},
                "created_at": now,
            },
            {
                "name": "Dr. Michael Chen",
                "specialization": "Orthodontics",
                "phone": "+1-555-0102",
                "email": "michael.chen@smilecare.com",
                "available_days": ["Monday", "Wednesday", "Friday"],
                "working_hours": {"start": "10:00", "end": "18:00"},
                "created_at": now,
            },
            {
                "name": "Dr. Emily Rodriguez",
                "specialization": "Endodontics",
                "phone": "+1-555-0103",
                "email": "emily.rodriguez@smilecare.com",
                "available_days": ["Tuesday", "Thursday", "Saturday"],
                "working_hours": {"start": "09:00", "end": "15:00"},
                "created_at": now,
            },
        ])

    # --- Dental Services ---
    if dental_services_collection.count_documents({}) == 0:
        services = [
            ("Dental Checkup",        "Preventive",   "Comprehensive oral examination",                       30,   75.00),
            ("Teeth Cleaning",         "Preventive",   "Professional cleaning & polishing",                    45,  120.00),
            ("Dental X-Ray",           "Diagnostic",   "Full-mouth or targeted X-ray imaging",                 15,   50.00),
            ("Tooth Filling",          "Restorative",  "Composite or amalgam cavity filling",                  45,  150.00),
            ("Root Canal Treatment",   "Endodontic",   "Root canal therapy for infected tooth",                90,  800.00),
            ("Tooth Extraction",       "Surgical",     "Simple or surgical extraction",                        30,  200.00),
            ("Teeth Whitening",        "Cosmetic",     "Professional whitening treatment",                     60,  350.00),
            ("Dental Crown",           "Restorative",  "Porcelain / ceramic crown placement",                  60, 1000.00),
            ("Dental Bridge",          "Restorative",  "Fixed bridge for missing teeth",                       90, 2500.00),
            ("Braces Consultation",    "Orthodontic",  "Orthodontic assessment & treatment plan",              45,  100.00),
            ("Dental Implant",         "Surgical",     "Titanium implant placement",                          120, 3500.00),
            ("Gum Treatment",          "Periodontic",  "Scaling & root planing for gum disease",               60,  250.00),
            ("Dental Veneer",          "Cosmetic",     "Porcelain veneer for smile enhancement",               60, 1200.00),
            ("Wisdom Tooth Extraction","Surgical",     "Extraction of impacted wisdom teeth",                  60,  400.00),
            ("Emergency Dental Care",  "Emergency",    "Urgent treatment for pain or trauma",                  30,  200.00),
        ]
        dental_services_collection.insert_many([
            {
                "name": name,
                "category": cat,
                "description": desc,
                "duration_minutes": dur,
                "price": price,
                "is_active": True,
                "created_at": now,
            }
            for name, cat, desc, dur, price in services
        ])