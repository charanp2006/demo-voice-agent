## Architecture Flow

```
User Voice
   ↓
voice_service (speech-to-text)
   ↓
agent_service (decision making)
   ↓
llm_service (intent extraction)
   ↓
clinic router/service
   ↓
Response
   ↓
voice_service (text-to-speech)
```
---
---

```
User → agent_service → LLM (with tools)
                    ↓
              tool call returned
                    ↓
         call real Python function
                    ↓
              return result to user
```
---
---
```
User (frontend/voice)
       ↓
POST /chat → {"message": "..."}
       ↓
FastAPI /chat endpoint
       ↓
agent_service.process_message
       ↓
LLM + tools (check_slots/book_appointment)
       ↓
Return structured response
       ↓
User sees AI response
```
---
---

```
Client (e.g., browser, Postman, mobile app)
          |
          | POST /chat
          | JSON: {"message": "Book me an appointment for tomorrow at 3pm"}
          v
-------------------------
FastAPI App (main.py)
-------------------------
1️⃣ Endpoint `/chat` receives request
2️⃣ Pydantic `ChatRequest` validates & parses JSON
          |
          v
-------------------------
process_message(user_message)
-------------------------
3️⃣ Sends user message to OpenAI model
   - System prompt: "You are a dental clinic receptionist"
   - Tools available: check_slots, book_appointment
          |
          v
4️⃣ AI decides:
   a) Respond directly → skip tools
   b) Call a tool → generates tool_call
          |
          v
-------------------------
Tool Execution
-------------------------
5️⃣ If AI called a tool:
   - Extract function name & arguments
   - Call the corresponding Python backend function:
       • check_slots(date)
       • book_appointment({name, phone, date, time})
   - Receive result (Python dict)
          |
          v
6️⃣ Send a second request to AI:
   - Include original user message
   - Include AI tool call
   - Include tool result as a "tool" message
          |
          v
7️⃣ AI generates final natural-language reply
          |
          v
-------------------------
FastAPI App
-------------------------
8️⃣ Return JSON response to client:
   {"response": "Your appointment is booked for March 1st at 3:00 PM."}
```
---
---
---

```
User sends audio
↓
Groq Whisper → text
↓
Gemini → reasoning + JSON routing
↓
Backend executes tool
↓
Gemini returns response text
↓
gTTS converts text → audio file
↓
Return audio file to user
```

---
```
User speaks
↓
Groq Whisper (STT)
↓
Gemini 2.5 Flash (Agent logic)
↓
FastAPI executes tool
↓
Gemini generates response text
↓
gTTS converts to speech
↓
Return audio file
```

---
### ADD-ONs 

- user is registered to the application. he asks the agent to book an appointment the agent validates and booked the appointment. After the Agent has booked the appointment an SMS/Email/Notisfication is sent to the user app/mobile for the confirmation.