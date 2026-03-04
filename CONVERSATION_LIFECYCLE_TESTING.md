# Conversation Lifecycle Testing Guide

This document covers testing the new conversation lifecycle implementation, including session control, multiple turns, and error recovery.

---

## Test 1: Conversation Lifecycle Control

**Purpose:** Verify that conversations can be started and stopped cleanly, with proper WebSocket connection management.

### Setup
- Backend running: `uvicorn app.main:app --reload`
- Frontend running: `npm run dev`
- Open browser to `http://localhost:5173`

### Test Steps

1. **Page Load - No Auto-Connect**
   - Page loads
   - ✓ No WebSocket connection yet
   - ✓ "Start Conversation" button visible (green)
   - ✓ Mic button is **disabled** (grayed out)
   - ✓ Text input shows placeholder "Start a conversation first..."
   - ✓ Status: "Conversation ended. Click 'Start Conversation' to begin."

2. **Click Start Conversation**
   - Click the "Start Conversation" button
   - ✓ Button changes to "Stop Conversation" (red)
   - ✓ WebSocket connects
   - ✓ Socket state in debug panel: "connecting" → "open"
   - ✓ Event timeline shows: `conversation_started`, `socket_open`
   - ✓ Status: "Tap mic to record"
   - ✓ Mic button is **enabled**
   - ✓ Text input placeholder: "Type your message..."

3. **Stop Conversation**
   - While in active conversation, click "Stop Conversation" button
   - ✓ Button changes back to "Start Conversation" (green)
   - ✓ WebSocket closes **without auto-reconnecting**
   - ✓ Socket state: "closed" (stays closed, doesn't reconnect)
   - ✓ Event timeline shows: `conversation_stopped`, `socket_close`
   - ✓ Mic button is **disabled** again
   - ✓ Text input **disabled** and grayed out
   - ✓ Status: "Conversation ended. Click 'Start Conversation' to begin."

4. **Start Again**
   - Click "Start Conversation" again
   - ✓ New WebSocket connection opens
   - ✓ Socket state: "disconnected" → "connecting" → "open"
   - ✓ Fresh conversation (chat history cleared from UI, but backend stores it)
   - ✓ Mic button enabled

**Success Criteria:**
- WebSocket connects only when conversation is active
- WebSocket closes cleanly when conversation is stopped
- No auto-reconnection after stop
- Can start and stop multiple times without errors

---

## Test 2: Multiple Turns In One Conversation

**Purpose:** Verify that a conversation can continue across multiple voice/text interactions without closing the connection.

### Setup
- Same as Test 1
- Start a conversation (click "Start Conversation")

### Test Steps

1. **First Voice Turn**
   - Click Mic button
   - ✓ Status: "Recording... tap mic again to send"
   - ✓ Chunk counter increments (e.g., "Chunks sent: 3")
   - Speak: "I want to book an appointment on March 25th"
   - Click Mic again to stop
   - ✓ Status: "Processing voice..."
   - ✓ Event timeline shows: `recording_started`, `recording_stopped`, `audio_sent`
   - ✓ Receives `transcription` event with user text
   - ✓ Receives `agent_text` event with assistant response
   - ✓ Receives `audio_ready` event
   - ✓ Audio plays automatically
   - ✓ Chat shows user message + assistant reply
   - ✓ Status: "Tap mic to record"
   - ✓ Socket state: still "open" (didn't close)

2. **Text Message Turn**
   - Type: "What slots are available?"
   - Press Enter or click Send
   - ✓ Message appears in chat (user side)
   - ✓ Status: "Validating and generating response..."
   - ✓ Assistant response appears
   - ✓ Audio plays
   - ✓ Socket state: still "open"

3. **Second Voice Turn**
   - Click Mic again
   - Speak: "Book the 5 PM slot"
   - Stop
   - ✓ Transcription received
   - ✓ Agent response received
   - ✓ Audio plays
   - ✓ Chat updated with both messages

4. **Third Voice Turn**
   - Repeat Mic recording
   - Speak: "Thank you"
   - Stop
   - ✓ Socket still connected
   - ✓ Processing works without errors

**Verify After 3 Turns:**
- ✓ Socket state: "open" (entire time)
- ✓ No reconnection events in timeline
- ✓ No errors in debug panel or console
- ✓ Chat history shows all 6 messages (3 user + 3 assistant)
- ✓ No memory leaks - timestamps are current

**Success Criteria:**
- Socket persists across multiple turns
- No reconnections during conversation
- All message types (voice + text) work in sequence
- Chat history accumulates correctly

---

## Test 3: Error Recovery - Internet Disconnect

**Purpose:** Verify frontend and backend behavior when network is lost during conversation.

### Setup
- Start a conversation
- Perform one successful voice turn

### Simulate Internet Disconnect
Using browser DevTools:
1. Press F12 to open DevTools
2. Go to **Network** tab
3. Click the throttling dropdown (usually says "No throttling")
4. Select "Offline"

### Test Steps

1. **During Disconnect**
   - Try to record audio
   - Click Mic
   - ✓ Mic captures audio (offline doesn't affect MediaRecorder)
   - Speak and stop
   - ✓ Status shows connection error or timeout
   - ✓ WebSocket close handler triggered
   - ✓ Socket state: "closed"

2. **Auto-Reconnect Attempt**
   - ✓ Status: "Connection lost - reconnecting..."
   - ✓ Event timeline shows: `socket_close`, `reconnecting`
   - ✓ Attempts to connect (socket state: "connecting")
   - ✓ Connection fails (can't reach server)
   - ✓ Socket state: "error" or "closed"

3. **Bring Internet Back Online**
   - Click throttling dropdown
   - Select "No throttling"

   - ✓ Frontend auto-reconnects
   - ✓ Socket state: "connecting" → "open"
   - ✓ Event timeline shows: `reconnecting`, `socket_open`
   - ✓ Status: "Tap mic to record"
   - ✓ Mic button enabled
   - ✓ **Conversation is still active** (button still says "Stop Conversation")

4. **Resume Recording**
   - Click Mic
   - Speak: "Can I still book?"
   - Stop
   - ✓ Works normally
   - ✓ Receives transcription and response
   - ✓ No errors

**Success Criteria:**
- Frontend doesn't crash during disconnect
- Auto-reconnects when internet returns
- Conversation remains active (not closed)
- Can continue recording after reconnect

---

## Test 4: Error Recovery - Backend Server Down

**Purpose:** Test behavior when backend server is unreachable.

### Setup
- Start a conversation
- Perform one successful voice turn
- Backend is running

### Kill Backend Server
1. Find the terminal running `uvicorn`
2. Press Ctrl+C to stop it
3. **Do not restart yet**

### Test Steps

1. **Immediate After Kill**
   - Current connection closes
   - ✓ Event timeline shows: `socket_close`
   - ✓ Status: "Connection lost - reconnecting..."
   - ✓ Mic disabled temporarily

2. **Reconnection Attempts**
   - Frontend attempts to reconnect every 2 seconds
   - ✓ Event timeline shows repeated: `reconnecting`, `socket_error`, `socket_close`
   - ✓ Socket state cycles through "connecting" → "error" → "closed"
   - ✓ Status updates accordingly
   - ✓ **Frontend does not crash**
   - ✓ Mic remains disabled until connection succeeds

3. **Restart Backend**
   - In a terminal, run: `uvicorn app.main:app --reload`
   - Backend starts

   - ✓ Within 2 seconds, frontend reconnects
   - ✓ Socket state: "open"
   - ✓ Status: "Tap mic to record"
   - ✓ Mic button enabled
   - ✓ Conversation still active

4. **Resume**
   - Click Mic
   - Test a voice turn
   - ✓ Works normally
   - ✓ Backend processes correctly

**Success Criteria:**
- Frontend gracefully handles server down
- Auto-reconnect attempts continue
- No crashes or hung states
- Works immediately when server recovers
- Conversation stays active throughout

---

## Test 5: Error Recovery - Refresh Frontend

**Purpose:** Verify state handling when user refreshes browser.

### Setup
- Start a conversation
- Complete one voice turn
- Have chat history visible

### Refresh Browser
- Press F5 or Ctrl+R
- Page reloads

### Test Steps

1. **After Refresh**
   - ✓ Page loads
   - ✓ Chat history loaded from backend (messages visible)
   - ✓ Conversation is **not** automatically active
   - ✓ "Start Conversation" button visible
   - ✓ Mic button disabled
   - ✓ Status: "Conversation ended. Click 'Start Conversation' to begin."

2. **Start New Conversation**
   - Click "Start Conversation"
   - ✓ New WebSocket opens
   - ✓ Can record and interact normally
   - ✓ Chat history from before refresh is displayed
   - ✓ New messages append to history

**Success Criteria:**
- State properly resets on refresh
- Chat history persists (loaded from backend)
- Conversation doesn't auto-start
- No memory leaks from previous session

---

## Test 6: Mic Disabled When Socket Disconnected

**Purpose:** Verify that mic button is properly disabled in all disconnected states.

### Test Steps

1. **Page Load (No Conversation)**
   - ✓ Mic button disabled

2. **During Conversation Init**
   - Click "Start Conversation"
   - While on "connecting" state
   - ✓ Mic button disabled until socket opens

3. **In Active Conversation**
   - Socket open, conversation active
   - ✓ Mic button enabled

4. **During Processing**
   - After sending audio (status: "Processing voice...")
   - ✓ Mic button disabled

5. **After Stop Conversation**
   - Click "Stop Conversation"
   - ✓ Mic button disabled

6. **Simulated Disconnect** (using browser DevTools Network → Offline)
   - After reconnect wait
   - While "Connection lost - reconnecting..."
   - ✓ Mic button disabled
   - Once reconnected
   - ✓ Mic button enabled

**Success Criteria:**
- Mic button follows socket state correctly
- Always disabled when socket not open
- Prevents user from sending audio in invalid state

---

## Debug Panel Interpretation

The debug panel at the bottom shows real-time WebSocket status:

- **Socket**: Current state (disconnected, connecting, open, closed, error)
- **Chunks sent**: Number of audio chunks captured during recording
- **Last event**: Most recent WebSocket event type
- **Timeline**: Last 6 events in chronological order

### Common Event Sequences

**Successful recording in active conversation:**
```
conversation_started → socket_open → recording_started → 
recording_stopped → audio_sent → transcription → agent_text → audio_ready
```

**Disconnect and reconnect:**
```
socket_close → reconnecting → socket_error → reconnecting → socket_open
```

**Stop conversation:**
```
conversation_stopped → socket_close (no reconnect attempt)
```

---

## Known Limitations

- Auto-reconnect attempts every 2 seconds indefinitely while conversation active
- Clicking "Start Conversation" clears chat history from UI (but not from backend)
- Browser refresh closes conversation (requires manual restart)
- Network errors during audio encode will fail that recording (others can retry)

---

## Success Checklist

- [ ] Test 1: Conversation Lifecycle Control - All steps pass
- [ ] Test 2: Multiple Turns - Socket stays open, 3+ turns work
- [ ] Test 3: Internet Disconnect - Auto-reconnect works
- [ ] Test 4: Backend Down - Recovers and works
- [ ] Test 5: Refresh Frontend - State resets properly
- [ ] Test 6: Mic Disabled - Correct in all states

**If all pass:** Implementation is ready for production use!
