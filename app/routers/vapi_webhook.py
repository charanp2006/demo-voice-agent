"""
Vapi Server URL webhook – handles function-call requests from Vapi's
voice pipeline so tool execution stays on our backend (MongoDB, etc.).

Vapi POST payloads
──────────────────
{ "message": { "type": "function-call", "functionCall": { "name": "...", "parameters": {...} } } }
{ "message": { "type": "assistant-request", ... } }
{ "message": { "type": "status-update", ... } }
{ "message": { "type": "end-of-call-report", ... } }

We only need to act on `function-call`; the rest get a 200 OK.
"""

import json
import time
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.services.agent_service import _execute_tool

router = APIRouter(prefix="/vapi", tags=["vapi"])


@router.post("/webhook")
async def vapi_webhook(request: Request):
    """
    Vapi server-URL webhook.

    Receives tool/function calls from the Vapi pipeline, executes them
    against our database, and returns the result string.
    """
    body = await request.json()
    message = body.get("message", {})
    msg_type = message.get("type", "")

    # ── function-call: execute tool and return result ────────
    if msg_type == "function-call":
        fn = message.get("functionCall", {})
        name = fn.get("name", "")
        params = fn.get("parameters", {})
        print(f"[LATENCY][VAPI] function-call: {name}({json.dumps(params, default=str)})")

        tool_start = time.time()
        result = _execute_tool(name, params)
        tool_end = time.time()
        tool_ms = round((tool_end - tool_start) * 1000)
        result_str = json.dumps(result, default=str)
        print(f"[LATENCY][VAPI] {name} completed in {tool_ms} ms "
              f"(result: {result_str[:200]})")

        return JSONResponse({"result": result_str})

    # ── assistant-request: return dynamic assistant config ───
    if msg_type == "assistant-request":
        print("[vapi-webhook] assistant-request received (no dynamic override)")
        return JSONResponse({})

    # ── status-update / end-of-call-report: log only ─────────
    if msg_type in ("status-update", "end-of-call-report"):
        status = message.get("status") or message.get("type")
        print(f"[vapi-webhook] {msg_type}: {status}")
        return JSONResponse({})

    # ── unknown type: 200 OK ─────────────────────────────────
    print(f"[vapi-webhook] unhandled type: {msg_type}")
    return JSONResponse({})
