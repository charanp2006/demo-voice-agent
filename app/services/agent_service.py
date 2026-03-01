import json
import os
# from openai import OpenAI
from google import genai
from dotenv import load_dotenv
from app.routers.clinic import check_slots, book_appointment

# load .env variables
load_dotenv()

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

SYSTEM_PROMPT = """
You are a dental clinic receptionist.

If user asks wants to:
- Check appointment slots → respond ONLY in JSON:
  { "action": "check_slots", "date": "YYYY-MM-DD" }

- Book appointment → respond ONLY in JSON:
  { "action": "book", "name": "...", "phone": "...", "date": "YYYY-MM-DD", "time": "..." }

If it is general information, respond normally in plain text.

Return raw JSON only when action is required.
Do not wrap JSON in markdown.
"""

def process_message(user_message: str):

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=SYSTEM_PROMPT + "\nUser: " + user_message
    )
    
    reply = response.text.strip()

    try:
        data = json.loads(reply)

        if data["action"] == "check_slots":
            result = check_slots(data["date"])
            return f"Available slots: {result['available_slots']}"

        elif data["action"] == "book":
            result = book_appointment(data)
            return f"Appointment booked successfully for date {data['date']} at {data['time']}."

    except Exception:
        # If JSON parsing fails, it means it's a general response, so we return it as is.
        return reply
    
    return reply



# ==========================================================

# --- OPENAI CLIENT SETUP --- # (not working because of openai api key restrictions, but the code is correct according to the documentation)

# client = OpenAI(api_key=os.getenv("OPEN_API_KEY"))

# # --- Tool definitions --- #

# tools = [
#     {
#         "type":"function",
#         "function":{
#             "name":"check_slots",
#             "description":"Check the availability of slots for a given date.",
#             "parameters":{
#                 "type":"object",
#                 "properties":{
#                     "date":{
#                         "type":"string",
#                         "description":"The date to check for available slots in YYYY-MM-DD format."
#                     }
#                 },
#                 "required":["date"]
#             }
#         }
#     },
#     {
#         "type":"function",
#         "function":{
#             "name":"check_slots",
#             "description":"Check the availability of slots for a given date.",
#             "parameters":{
#                 "type":"object",
#                 "properties":{
#                     "date":{
#                         "type":"string",
#                         "description":"The date to check for available slots in YYYY-MM-DD format."
#                     }
#                 },
#                 "required":["date"]
#             }
#         }
#     },
#     {
#         "type":"function",
#         "function":{
#             "name":"book_appointments",
#             "description":"Book ans Appointment.",
#             "parameters":{
#                 "type":"object",
#                 "properties":{
#                     "name":{"type":"string"},
#                     "phone":{"type":"string"},
#                     "date":{"type":"string"},
#                     "time":{"type":"string"},
#                 },
#                 "required":["name","phone","date","time"]
#             }
#         }
#     }
# ]

# # --- Agent logic --- #

# from app.routers.clinic import check_slots, book_appointment

# def procces_message(user_message: str):

#     response = client.chat.completions.create(
#         model="gpt-4o",
#         messages=[
#             {"role":"system", "content":"You are a dental clinic assistant."},
#             {"role":"user","content":user_message}
#         ],
#         tools=tools,
#         tool_choice="auto"
#     )

#     message = response.choices[0].message
    
#     if message.tool_calls:

#         tool_call = message.tool_calls[0]
#         function_name = tool_call.function.name
#         arguments = json.loads(tool_call.function.arguments)

#         if function_name == "check_slots":
#             result = check_slots(arguments["date"])

#         elif function_name == "book_appointments":
#             result = book_appointment(arguments)

#         else:
#             result = {"error":"Unknown function"}
        
#         second_response = client.chat.completions.create(
#             model="gpt-5.1",
#             messages=[
#                 {"role":"system", "content":"You are a dental clinic assistant."},
#                 {"role":"user","content":user_message},
#                 message,
#                 {
#                     "role":"tool",
#                     "tool_call_id":tool_call.id,
#                     "content":json.dumps(result)
#                 }
#             ]
#         )

#         return second_response.choices[0].message.content
    
#     return message.content