"""FastAPI server — ties together the LangGraph supervisor, git tools, and voice layer."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

import pathlib

import fastapi
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.checkpointer.git_checkpointer import GitCheckpointer
from src.config import Settings
from src.graph.supervisor import build_supervisor_graph
from src.voice.audio_converter import webm_to_wav
from src.voice.command_parser import VoiceCommandParser
from src.voice.sentence_buffer import SentenceBuffer
from src.voice.session_manager import VoiceSessionManager

logger = logging.getLogger("gitcheckpoint")


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"
    voice_response: bool = False


class ChatResponse(BaseModel):
    response: str
    thread_id: str
    checkpoint_id: str | None = None
    audio_url: str | None = None


class CheckpointRequest(BaseModel):
    thread_id: str
    label: str


class TimeTravelRequest(BaseModel):
    thread_id: str
    checkpoint_id: str


class ForkRequest(BaseModel):
    source_thread_id: str
    checkpoint_id: str
    new_thread_name: str
    initial_message: str = ""


class MergeRequest(BaseModel):
    source_thread_id: str
    target_thread_id: str


class PushRequest(BaseModel):
    thread_id: str


class GistRequest(BaseModel):
    thread_id: str
    public: bool = False


# ---------------------------------------------------------------------------
# Voice WebSocket helpers
# ---------------------------------------------------------------------------

UI_INTENTS = {
    "switch_thread", "toggle_sidebar", "toggle_graph",
    "show_diff", "new_thread", "current_state", "deactivate", "help",
}

UI_CONFIRMATIONS = {
    "switch_thread": "Got it, switching to {thread_name}.",
    "toggle_sidebar": "Done!",
    "toggle_graph": "Done!",
    "show_diff": "Here's the diff.",
    "new_thread": "Created {thread_name}. Ready to go!",
}

DEACTIVATE_RESPONSES = [
    "Got it, I'll be here. Just say 'Hey Git' when you need me.",
    "I'll be right here if you need me.",
    "See you soon! Just say 'Hey Git' to wake me up.",
]

# Regex for parsing inline UI commands from agent responses: [UI:action:params]
import re
UI_CMD_PATTERN = re.compile(r'\[UI:(\w+)(?::([^\]]*))?\]')


def _build_ui_context(checkpointer, thread_id: str, session: dict) -> str:
    """Build UI state context string for supervisor invocations."""
    try:
        repo = checkpointer.repo
        branch_name = checkpointer._branch_name(thread_id)
        branches = [b.name for b in repo.branches]
        thread_branches = [b for b in branches if b.startswith("thread-")]

        if branch_name in branches:
            branch = repo.branches[branch_name]
            head_sha = branch.commit.hexsha[:7]
            head_msg = branch.commit.message.strip().split("\n")[0]
            commit_count = sum(1 for _ in repo.iter_commits(branch_name))
        else:
            head_sha = "none"
            head_msg = "no commits yet"
            commit_count = 0
    except Exception:
        thread_branches = []
        head_sha = "none"
        head_msg = "no commits yet"
        commit_count = 0

    msg_count = session.get("message_count", 0)
    is_first = msg_count == 0

    return (
        f"[UI STATE]\n"
        f"Active thread: {thread_id}\n"
        f"Threads: {len(thread_branches)}\n"
        f"Commits on this thread: {commit_count}\n"
        f"Current HEAD: {head_sha} — {head_msg}\n"
        f"Sidebar visible: {session.get('sidebar_visible', True)}\n"
        f"Graph panel visible: {session.get('graph_visible', True)}\n"
        f"First interaction: {is_first}\n"
        f"Exchanges so far: {msg_count}\n"
        f"[/UI STATE]"
    )


async def _stt_transcribe(wav_bytes: bytes, settings: "Settings") -> str:
    """Send WAV audio to Smallest.ai Pulse STT and return transcript."""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://waves-api.smallest.ai/api/v1/pulse/get_text",
            params={"model": "pulse", "language": "en"},
            headers={
                "Authorization": f"Bearer {settings.smallest_api_key}",
                "Content-Type": "audio/wav",
            },
            content=wav_bytes,
            timeout=120.0,
        )
    if resp.status_code != 200:
        raise RuntimeError(f"STT API returned {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    return data.get("transcription", "")


async def _handle_voice_ui_command(
    websocket: "WebSocket",
    command: dict,
    tts_service,
    checkpointer: "GitCheckpointer",
    thread_id: str,
) -> bool:
    """Handle UI-level voice commands. Returns True if handled."""
    intent = command.get("intent", "")
    params = command.get("params", {})

    if intent not in UI_INTENTS:
        return False

    # Special: help — spoken capabilities overview
    if intent == "help":
        help_text = (
            "Here's what I can do. "
            "I save our conversation as we talk — every exchange is a checkpoint, "
            "like a save point in a game. "
            "Say 'save checkpoint' to mark an important moment. "
            "Say 'what if' to explore an alternative — I'll fork into a new branch. "
            "Say 'go back to' any checkpoint to rewind time. "
            "Say 'merge' to combine two branches. "
            "Say 'push to GitHub' to share the conversation tree with your team. "
            "Say 'show me the status' to see where we are. "
            "Or just talk to me naturally — I'll figure out what you need."
        )
        await websocket.send_json({
            "type": "response_text", "content": help_text, "done": True,
        })
        if tts_service:
            try:
                audio = await tts_service.async_synthesize_bytes(help_text)
                if audio:
                    await websocket.send_json({
                        "type": "audio_chunk",
                        "data": base64.b64encode(audio).decode(),
                        "sequence": 0,
                    })
            except Exception as e:
                logger.warning("TTS for help failed: %s", e)
        await websocket.send_json({"type": "audio_done"})
        return True

    # Special: current_state reads directly from git
    if intent == "current_state":
        await _handle_current_state(websocket, tts_service, checkpointer, thread_id)
        return True

    # Special: deactivate — farewell message, then signal frontend to go passive
    if intent == "deactivate":
        import random
        farewell = random.choice(DEACTIVATE_RESPONSES)
        await websocket.send_json({
            "type": "response_text", "content": farewell, "done": True,
        })
        if tts_service:
            try:
                audio = await tts_service.async_synthesize_bytes(farewell)
                if audio:
                    await websocket.send_json({
                        "type": "audio_chunk",
                        "data": base64.b64encode(audio).decode(),
                        "sequence": 0,
                    })
            except Exception as e:
                logger.warning("TTS for deactivation failed: %s", e)
        await websocket.send_json({"type": "audio_done"})
        return True

    # Send UI command to frontend
    await websocket.send_json({
        "type": "ui_command",
        "action": intent,
        "params": params,
    })

    # Speak confirmation
    template = UI_CONFIRMATIONS.get(intent, "Done.")
    confirmation = template.format(**params) if params else template
    await websocket.send_json({
        "type": "response_text", "content": confirmation, "done": True,
    })

    if tts_service:
        try:
            audio = await tts_service.async_synthesize_bytes(confirmation)
            if audio:
                await websocket.send_json({
                    "type": "audio_chunk",
                    "data": base64.b64encode(audio).decode(),
                    "sequence": 0,
                })
        except Exception as e:
            logger.warning("TTS for UI confirmation failed: %s", e)

    await websocket.send_json({"type": "audio_done"})
    return True


async def _handle_current_state(websocket, tts_service, checkpointer, thread_id):
    """Read git state and speak a summary."""
    try:
        repo = checkpointer.repo
        branch_name = checkpointer._branch_name(thread_id)
        branches = [b.name for b in repo.branches]
        thread_branches = [b for b in branches if b.startswith("thread-")]

        if branch_name in branches:
            branch = repo.branches[branch_name]
            head_sha = branch.commit.hexsha[:7]
            head_msg = branch.commit.message.strip().split("\n")[0]
            commit_count = sum(1 for _ in repo.iter_commits(branch_name))
        else:
            head_sha = "none"
            head_msg = "no commits"
            commit_count = 0

        display_name = thread_id
        summary = (
            f"You're on the {display_name} thread, "
            f"at checkpoint {head_sha} — '{head_msg}'. "
            f"{commit_count} checkpoints here, "
            f"{len(thread_branches)} threads total."
        )
    except Exception as e:
        summary = f"Hmm, I couldn't read the current state. {e}"

    await websocket.send_json({
        "type": "response_text", "content": summary, "done": True,
    })

    if tts_service:
        try:
            audio = await tts_service.async_synthesize_bytes(summary)
            if audio:
                await websocket.send_json({
                    "type": "audio_chunk",
                    "data": base64.b64encode(audio).decode(),
                    "sequence": 0,
                })
        except Exception as e:
            logger.warning("TTS for current_state failed: %s", e)

    await websocket.send_json({"type": "audio_done"})

    # Also send state_update for UI highlighting
    await _broadcast_state(websocket, checkpointer, thread_id)


async def _stream_supervisor_response(
    websocket: "WebSocket",
    graph,
    transcript: str,
    thread_id: str,
    tts_service,
    ui_context: str = "",
):
    """Stream LangGraph supervisor response with sentence-buffered TTS.

    Parses inline [UI:action:params] commands from agent responses,
    sends them as ui_command frames, and strips them from spoken text.
    """
    sentence_buffer = SentenceBuffer()
    tts_queue: asyncio.Queue[str | None] = asyncio.Queue()
    seq_counter = 0
    # Accumulate full response to extract UI commands at sentence boundaries
    pending_text = ""

    async def tts_worker():
        nonlocal seq_counter
        while True:
            sentence = await tts_queue.get()
            if sentence is None:
                break
            if not tts_service:
                continue
            try:
                audio = await asyncio.wait_for(
                    tts_service.async_synthesize_bytes(sentence),
                    timeout=30.0,
                )
                if audio:
                    await websocket.send_json({
                        "type": "audio_chunk",
                        "data": base64.b64encode(audio).decode(),
                        "sequence": seq_counter,
                    })
                    seq_counter += 1
            except asyncio.TimeoutError:
                logger.warning("TTS timeout for sentence: %s", sentence[:50])
            except Exception as e:
                logger.warning("TTS failed: %s", e)

    async def _extract_and_send_ui_commands(text: str) -> str:
        """Extract [UI:action:params] from text, send as ui_command frames."""
        matches = UI_CMD_PATTERN.findall(text)
        for action, params_str in matches:
            # Parse params — support key=value or plain string
            params = {}
            if params_str:
                if "=" in params_str:
                    for part in params_str.split(","):
                        if "=" in part:
                            k, v = part.strip().split("=", 1)
                            params[k.strip()] = v.strip()
                else:
                    params = {"value": params_str.strip()}
            await websocket.send_json({
                "type": "ui_command",
                "action": action,
                "params": params,
            })
        # Strip UI commands from text
        return UI_CMD_PATTERN.sub("", text).strip()

    tts_task = asyncio.create_task(tts_worker())

    # Build input with UI context
    user_content = transcript
    if ui_context:
        user_content = f"{ui_context}\n\nUser: {transcript}"

    try:
        async for event in graph.astream_events(
            {"messages": [{"role": "user", "content": user_content}]},
            {"configurable": {"thread_id": thread_id}},
            version="v2",
        ):
            kind = event.get("event", "")
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    token = chunk.content
                    if isinstance(token, str):
                        # Check for routing announcements from supervisor
                        if token.startswith("Let me") or token.startswith("On it"):
                            await websocket.send_json({
                                "type": "agent_routing",
                                "message": token,
                            })
                            await tts_queue.put(token)
                        else:
                            pending_text += token
                            # Send raw token for display (UI commands visible briefly)
                            await websocket.send_json({
                                "type": "response_text",
                                "content": token,
                                "done": False,
                            })
                            # Process complete sentences
                            for sentence in sentence_buffer.add_token(token):
                                clean = await _extract_and_send_ui_commands(sentence)
                                if clean:
                                    await tts_queue.put(clean)
    except Exception as e:
        logger.error("Supervisor streaming error: %s", e)
        await websocket.send_json({
            "type": "error", "message": str(e),
        })

    # Flush remaining buffer
    remaining = sentence_buffer.flush()
    if remaining:
        clean = await _extract_and_send_ui_commands(remaining)
        if clean:
            await tts_queue.put(clean)

    # Signal TTS worker to stop and wait
    await tts_queue.put(None)
    await tts_task

    await websocket.send_json({
        "type": "response_text", "content": "", "done": True,
    })
    await websocket.send_json({"type": "audio_done"})


async def _broadcast_state(
    websocket: "WebSocket",
    checkpointer: "GitCheckpointer",
    thread_id: str,
):
    """Send git state updates to the frontend."""
    try:
        from src.tools.git_tools import list_branches, conversation_log

        branches_result = list_branches.invoke({})
        await websocket.send_json({
            "type": "state_update",
            "kind": "threads_changed",
            "data": {"raw": branches_result},
        })

        log_result = conversation_log.invoke({
            "thread_id": thread_id, "max_entries": 50,
        })
        await websocket.send_json({
            "type": "state_update",
            "kind": "log_changed",
            "data": {"raw": log_result, "thread_id": thread_id},
        })
    except Exception as e:
        logger.warning("State broadcast failed: %s", e)


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def _register_routes(application: FastAPI) -> None:  # noqa: C901
    """Attach all endpoint handlers to *application*."""

    def _get_graph(app: FastAPI):
        return app.state.graph

    def _get_checkpointer(app: FastAPI) -> GitCheckpointer:
        return app.state.checkpointer

    # ---- 1. POST /api/chat ------------------------------------------------

    @application.post("/api/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest):
        """Send a message to the GitCheckpoint agent."""
        import time as _time

        graph = _get_graph(application)
        last_err = None
        for attempt in range(3):
            try:
                result = await asyncio.to_thread(
                    graph.invoke,
                    {"messages": [{"role": "user", "content": request.message}]},
                    {"configurable": {"thread_id": request.thread_id}},
                )
                break
            except Exception as e:
                last_err = e
                if "Lock" in str(e) and attempt < 2:
                    _time.sleep(0.3 * (attempt + 1))
                    continue
                raise HTTPException(status_code=500, detail=str(e))
        else:
            raise HTTPException(status_code=500, detail=str(last_err))

        # Get the last AI message with actual text content
        response_text = ""
        for msg in reversed(result["messages"]):
            if msg.type == "ai" and msg.content and isinstance(msg.content, str):
                response_text = msg.content
                break
        checkpoint_id = None
        cp = _get_checkpointer(application)
        branch_name = cp._branch_name(request.thread_id)
        if branch_name in [b.name for b in cp.repo.branches]:
            checkpoint_id = cp.repo.branches[branch_name].commit.hexsha

        audio_url = None
        if request.voice_response and hasattr(application.state, "tts"):
            try:
                path = application.state.tts.synthesize(
                    response_text,
                    output_path=f"voice_response_{request.thread_id}.wav",
                )
                audio_url = f"/static/{path}"
            except Exception:
                pass

        return ChatResponse(
            response=response_text,
            thread_id=request.thread_id,
            checkpoint_id=checkpoint_id,
            audio_url=audio_url,
        )

    # ---- 2. POST /api/checkpoint ------------------------------------------

    @application.post("/api/checkpoint")
    async def create_checkpoint(request: CheckpointRequest):
        """Manually create a named checkpoint."""
        from src.tools.git_tools import create_checkpoint as _cp_tool

        try:
            result = _cp_tool.invoke(
                {"label": request.label, "thread_id": request.thread_id}
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        return {"result": result}

    # ---- 3. POST /api/time-travel -----------------------------------------

    @application.post("/api/time-travel")
    async def time_travel(request: TimeTravelRequest):
        """Time travel to a specific checkpoint."""
        from src.tools.git_tools import time_travel as _tt_tool

        result = _tt_tool.invoke(
            {"thread_id": request.thread_id, "checkpoint_id": request.checkpoint_id}
        )
        if result.startswith("Error"):
            raise HTTPException(status_code=404, detail=result)
        return {"result": result}

    # ---- 4. POST /api/fork ------------------------------------------------

    @application.post("/api/fork")
    async def fork_conversation(request: ForkRequest):
        """Fork a conversation at a checkpoint."""
        from src.tools.git_tools import fork_conversation as _fork_tool

        result = _fork_tool.invoke({
            "source_thread_id": request.source_thread_id,
            "checkpoint_id": request.checkpoint_id,
            "new_thread_name": request.new_thread_name,
        })
        if result.startswith("Error"):
            raise HTTPException(status_code=400, detail=result)

        if request.initial_message:
            graph = _get_graph(application)
            try:
                await asyncio.to_thread(
                    graph.invoke,
                    {"messages": [{"role": "user", "content": request.initial_message}]},
                    {"configurable": {"thread_id": request.new_thread_name}},
                )
            except Exception:
                pass

        return {"result": result}

    # ---- 5. POST /api/merge -----------------------------------------------

    @application.post("/api/merge")
    async def merge_conversations(request: MergeRequest):
        """Merge two conversation branches."""
        from src.tools.git_tools import merge_conversations as _merge_tool

        result = _merge_tool.invoke({
            "source_thread_id": request.source_thread_id,
            "target_thread_id": request.target_thread_id,
        })
        if result.startswith("Error"):
            raise HTTPException(status_code=400, detail=result)
        return {"result": result}

    # ---- 6. GET /api/threads ----------------------------------------------

    @application.get("/api/threads")
    async def list_threads():
        """List all conversation threads (branches)."""
        from src.tools.git_tools import list_branches as _lb_tool

        result = _lb_tool.invoke({})
        return {"result": result}

    # ---- 7. GET /api/threads/{thread_id}/log ------------------------------

    @application.get("/api/threads/{thread_id}/log")
    async def get_conversation_log(thread_id: str, limit: int = 20):
        """Get the conversation log for a thread."""
        from src.tools.git_tools import conversation_log as _log_tool

        result = _log_tool.invoke(
            {"thread_id": thread_id, "max_entries": limit}
        )
        return {"result": result}

    # ---- 8. GET /api/threads/{thread_id}/diff/{checkpoint_a}/{checkpoint_b}

    @application.get("/api/threads/{thread_id}/diff/{checkpoint_a}/{checkpoint_b}")
    async def get_diff(thread_id: str, checkpoint_a: str, checkpoint_b: str):
        """Get diff between two checkpoints."""
        from src.tools.git_tools import conversation_diff as _diff_tool

        result = _diff_tool.invoke({
            "thread_id": thread_id,
            "checkpoint_a": checkpoint_a,
            "checkpoint_b": checkpoint_b,
        })
        if "Error" in result:
            raise HTTPException(status_code=404, detail=result)
        return {"result": result}

    # ---- 9. POST /api/github/push -----------------------------------------

    @application.post("/api/github/push")
    async def push_to_github(request: PushRequest):
        """Push a conversation branch to GitHub."""
        from src.tools.github_tools import push_to_github as _push_tool

        try:
            result = _push_tool.invoke({"thread_id": request.thread_id})
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if result.startswith("Error"):
            raise HTTPException(status_code=400, detail=result)
        return {"result": result}

    # ---- 10. POST /api/github/gist ----------------------------------------

    @application.post("/api/github/gist")
    async def share_as_gist(request: GistRequest):
        """Share conversation as a GitHub Gist."""
        from src.tools.github_tools import share_as_gist as _gist_tool

        try:
            result = _gist_tool.invoke({
                "thread_id": request.thread_id,
                "public": request.public,
            })
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if "not found" in result:
            raise HTTPException(status_code=400, detail=result)
        return {"result": result}

    # ---- 11. WebSocket /ws/chat -------------------------------------------

    @application.websocket("/ws/chat")
    async def websocket_chat(websocket: WebSocket):
        """WebSocket endpoint for real-time streaming conversations."""
        await websocket.accept()
        try:
            thread_id = await websocket.receive_text()

            while True:
                message = await websocket.receive_text()
                graph = _get_graph(application)

                try:
                    async for event in graph.astream_events(
                        {"messages": [{"role": "user", "content": message}]},
                        {"configurable": {"thread_id": thread_id}},
                        version="v2",
                    ):
                        kind = event.get("event", "")
                        if kind == "on_chat_model_stream":
                            chunk = event.get("data", {}).get("chunk")
                            if chunk and hasattr(chunk, "content") and chunk.content:
                                await websocket.send_json(
                                    {"type": "token", "content": chunk.content}
                                )
                except Exception as e:
                    await websocket.send_json(
                        {"type": "error", "content": str(e)}
                    )

                await websocket.send_json({"type": "done"})

        except WebSocketDisconnect:
            pass

    # ---- 11b. WebSocket /ws/voice ------------------------------------------

    @application.websocket("/ws/voice")
    async def websocket_voice(websocket: WebSocket):
        """Bidirectional voice WebSocket for full conversational voice mode.

        Protocol:
          Client → Server:
            - binary frames: raw audio chunks from MediaRecorder
            - text frames: JSON control messages
              {"type": "start_recording", "thread_id": "...", "sample_rate": 16000}
              {"type": "stop_recording"}
              {"type": "ui_command", "action": "...", "params": {...}}
          Server → Client:
            - text frames: JSON messages
              {"type": "transcript", "text": "..."}
              {"type": "agent_routing", "agent": "...", "message": "..."}
              {"type": "response_text", "content": "...", "done": false}
              {"type": "audio_chunk", "data": "<base64 PCM>", "sequence": N}
              {"type": "audio_done"}
              {"type": "state_update", "kind": "...", "data": {...}}
              {"type": "ui_command", "action": "...", "params": {...}}
              {"type": "ready_for_input"}
              {"type": "error", "message": "..."}
        """
        await websocket.accept()
        thread_id = "default"
        audio_buffer = bytearray()
        sample_rate = 16000
        tts_service = getattr(application.state, "tts", None)
        parser = getattr(application.state, "parser", None)
        settings: Settings = application.state.settings
        # Session state tracking for UI context
        session = {
            "message_count": 0,
            "sidebar_visible": True,
            "graph_visible": True,
        }

        try:
            while True:
                raw = await websocket.receive()

                # Binary frame — audio chunk
                if "bytes" in raw and raw["bytes"]:
                    audio_buffer.extend(raw["bytes"])
                    continue

                # Text frame — JSON control message
                text = raw.get("text", "")
                if not text:
                    continue

                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type", "")

                if msg_type == "start_recording":
                    thread_id = msg.get("thread_id", thread_id)
                    sample_rate = msg.get("sample_rate", 16000)
                    audio_buffer.clear()
                    continue

                if msg_type == "stop_recording":
                    if not audio_buffer:
                        await websocket.send_json(
                            {"type": "error", "message": "No audio received"}
                        )
                        await websocket.send_json({"type": "ready_for_input"})
                        continue

                    # --- Convert WebM → WAV ---
                    try:
                        wav_bytes = await webm_to_wav(
                            bytes(audio_buffer), sample_rate=sample_rate
                        )
                    except Exception as e:
                        logger.error("Audio conversion failed: %s", e)
                        await websocket.send_json(
                            {"type": "error", "message": f"Audio conversion failed: {e}"}
                        )
                        await websocket.send_json({"type": "ready_for_input"})
                        audio_buffer.clear()
                        continue
                    audio_buffer.clear()

                    # --- STT: WAV → text ---
                    try:
                        transcript = await _stt_transcribe(wav_bytes, settings)
                    except Exception as e:
                        logger.error("STT failed: %s", e)
                        await websocket.send_json(
                            {"type": "error", "message": f"Transcription failed: {e}"}
                        )
                        await websocket.send_json({"type": "ready_for_input"})
                        continue

                    if not transcript.strip():
                        await websocket.send_json(
                            {"type": "error", "message": "No speech detected"}
                        )
                        await websocket.send_json({"type": "ready_for_input"})
                        continue

                    await websocket.send_json(
                        {"type": "transcript", "text": transcript}
                    )

                    # --- Check for UI commands ---
                    ui_handled = False
                    if parser:
                        try:
                            command = await asyncio.to_thread(
                                parser.parse_sync, transcript
                            )
                            ui_handled = await _handle_voice_ui_command(
                                websocket, command, tts_service,
                                application.state.checkpointer, thread_id,
                            )
                        except Exception:
                            pass

                    if not ui_handled:
                        # --- Build UI context for supervisor ---
                        ctx = _build_ui_context(
                            application.state.checkpointer,
                            thread_id, session,
                        )
                        # --- Route through LangGraph supervisor ---
                        await _stream_supervisor_response(
                            websocket,
                            application.state.graph,
                            transcript,
                            thread_id,
                            tts_service,
                            ui_context=ctx,
                        )

                    session["message_count"] = session.get("message_count", 0) + 1

                    # --- Broadcast state updates ---
                    await _broadcast_state(
                        websocket,
                        application.state.checkpointer,
                        thread_id,
                    )

                    await websocket.send_json({"type": "ready_for_input"})
                    continue

                if msg_type == "transcript_direct":
                    # Pre-transcribed text from wake word detection
                    transcript = msg.get("text", "").strip()
                    if not transcript:
                        await websocket.send_json({"type": "ready_for_input"})
                        continue

                    await websocket.send_json(
                        {"type": "transcript", "text": transcript}
                    )

                    # Check for UI commands
                    ui_handled = False
                    if parser:
                        try:
                            command = await asyncio.to_thread(
                                parser.parse_sync, transcript
                            )
                            ui_handled = await _handle_voice_ui_command(
                                websocket, command, tts_service,
                                application.state.checkpointer, thread_id,
                            )
                        except Exception:
                            pass

                    if not ui_handled:
                        ctx = _build_ui_context(
                            application.state.checkpointer,
                            thread_id, session,
                        )
                        await _stream_supervisor_response(
                            websocket,
                            application.state.graph,
                            transcript,
                            thread_id,
                            tts_service,
                            ui_context=ctx,
                        )

                    session["message_count"] = session.get("message_count", 0) + 1

                    await _broadcast_state(
                        websocket,
                        application.state.checkpointer,
                        thread_id,
                    )
                    await websocket.send_json({"type": "ready_for_input"})
                    continue

                if msg_type == "ui_command":
                    # Direct UI command from frontend (not voice-parsed)
                    action = msg.get("action", "")
                    params = msg.get("params", {})
                    if action == "switch_thread":
                        thread_id = params.get("thread_id", thread_id)
                    # Track visibility state
                    if action == "ui_state_sync":
                        session["sidebar_visible"] = params.get("sidebar", session.get("sidebar_visible", True))
                        session["graph_visible"] = params.get("graph", session.get("graph_visible", True))
                    continue

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error("Voice WebSocket error: %s", e)

    # ---- 12a. POST /api/voice/transcribe ------------------------------------

    @application.post("/api/voice/transcribe")
    async def voice_transcribe(request: fastapi.Request):
        """Transcribe audio using Smallest.ai Pulse STT REST API."""
        content_type = request.headers.get("content-type", "")

        # Accept raw audio bytes or multipart form
        if "multipart" in content_type:
            form = await request.form()
            audio_file = form.get("audio")
            if audio_file is None:
                raise HTTPException(status_code=400, detail="No audio file provided")
            audio_bytes = await audio_file.read()
        else:
            audio_bytes = await request.body()

        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Empty audio data")

        settings = application.state.settings
        if not settings.smallest_api_key:
            raise HTTPException(
                status_code=503, detail="STT not available — SMALLEST_API_KEY not set"
            )

        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://waves-api.smallest.ai/api/v1/pulse/get_text",
                params={"model": "pulse", "language": "en"},
                headers={
                    "Authorization": f"Bearer {settings.smallest_api_key}",
                    "Content-Type": "audio/wav",
                },
                content=audio_bytes,
                timeout=120.0,
            )

        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"STT API returned {resp.status_code}: {resp.text}",
            )

        data = resp.json()
        transcript = data.get("transcription", "")
        return {"transcript": transcript}

    # ---- 12. POST /api/voice/webhook --------------------------------------

    @application.post("/api/voice/webhook")
    async def voice_webhook(payload: dict):
        """Webhook endpoint for Smallest.ai Atoms call events."""
        event_type = payload.get("event", payload.get("type", ""))

        if event_type == "call_started":
            call_id = payload.get("call_id", "")
            if hasattr(application.state, "session_manager"):
                application.state.session_manager.register_session(call_id)
            return {"status": "session_registered", "call_id": call_id}

        elif event_type == "transcription":
            call_id = payload.get("call_id", "")
            transcript = payload.get("transcript", "")
            if hasattr(application.state, "session_manager"):
                try:
                    response_text, audio_path = (
                        await application.state.session_manager.handle_voice_input(
                            call_id, transcript
                        )
                    )
                    return {
                        "status": "ok",
                        "response": response_text,
                        "audio_path": audio_path,
                    }
                except Exception as e:
                    return {"status": "error", "detail": str(e)}

            return {"status": "no_session_manager"}

        elif event_type == "call_ended":
            call_id = payload.get("call_id", "")
            if hasattr(application.state, "session_manager"):
                application.state.session_manager.end_session(call_id)
            return {"status": "session_ended", "call_id": call_id}

        return {"status": "unhandled_event", "event": event_type}

    # ---- 13. GET /api/health ----------------------------------------------

    @application.get("/api/health")
    async def health_check():
        return {"status": "ok", "service": "gitcheckpoint"}


# ---------------------------------------------------------------------------
# Lifespan — initialise shared state once on startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(application: FastAPI):
    # --- Load and validate settings ---
    settings = Settings()

    if not settings.anthropic_api_key:
        raise RuntimeError("Missing required: ANTHROPIC_API_KEY")
    if not settings.smallest_api_key:
        logger.warning("SMALLEST_API_KEY not set — voice/TTS features disabled")
    if not settings.github_token:
        logger.warning("GITHUB_TOKEN not set — GitHub features disabled")

    # --- Init checkpointer (auto-reinitialise if corrupted) ---
    try:
        checkpointer = GitCheckpointer(settings.checkpoint_dir)
    except Exception:
        import shutil
        logger.warning("Corrupted .conversations repo — reinitialising")
        shutil.rmtree(settings.checkpoint_dir, ignore_errors=True)
        checkpointer = GitCheckpointer(settings.checkpoint_dir)

    # --- Build supervisor graph ---
    graph = build_supervisor_graph(settings, checkpointer=checkpointer)

    # --- Optional: TTS service ---
    tts = None
    try:
        from src.voice.tts_service import TTSService

        tts = TTSService(settings)
    except (ImportError, Exception) as e:
        logger.warning("TTS init failed (text-only mode): %s", e)

    # --- Optional: Voice command parser ---
    parser = None
    session_mgr = None
    try:
        from langchain_anthropic import ChatAnthropic
        model = ChatAnthropic(
            model="claude-sonnet-4-20250514",
            api_key=settings.anthropic_api_key,
        )
        parser = VoiceCommandParser(model)
        session_mgr = VoiceSessionManager(
            graph_app=graph, tts_service=tts, command_parser=parser,
        )
    except Exception as e:
        logger.warning("Voice parser init failed: %s", e)

    application.state.settings = settings
    application.state.checkpointer = checkpointer
    application.state.graph = graph
    if tts:
        application.state.tts = tts
    if parser:
        application.state.parser = parser
    if session_mgr:
        application.state.session_manager = session_mgr

    logger.info("GitCheckpoint server started on %s:%s", settings.host, settings.port)
    yield


# ---------------------------------------------------------------------------
# App factory + default instance
# ---------------------------------------------------------------------------

def create_app(
    settings: Settings | None = None,
    checkpointer: GitCheckpointer | None = None,
    graph: Any | None = None,
) -> FastAPI:
    """Create and return the FastAPI application.

    When *settings*, *checkpointer*, and *graph* are all provided the lifespan
    hook is skipped (useful for testing).
    """
    use_lifespan = settings is None

    application = FastAPI(
        title="GitCheckpoint API",
        description="Version Control for Conversations",
        version="0.1.0",
        lifespan=lifespan if use_lifespan else None,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if settings is not None:
        application.state.settings = settings
    if checkpointer is not None:
        application.state.checkpointer = checkpointer
    if graph is not None:
        application.state.graph = graph

    _register_routes(application)

    # Serve the built React frontend if available.
    # The frontend is built into frontend/dist during Docker build.
    _frontend_dir = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if _frontend_dir.is_dir():
        # Mount static assets (JS, CSS, images) at /assets
        _assets_dir = _frontend_dir / "assets"
        if _assets_dir.is_dir():
            application.mount(
                "/assets",
                StaticFiles(directory=str(_assets_dir)),
                name="frontend-assets",
            )

        # Catch-all: serve index.html for any non-API, non-WS route (SPA routing)
        @application.get("/{full_path:path}")
        async def serve_spa(request: Request, full_path: str):
            # Serve actual static files (favicon, manifest, etc.)
            file_path = _frontend_dir / full_path
            if full_path and file_path.is_file():
                return FileResponse(str(file_path))
            # Everything else → index.html (React Router handles it)
            return FileResponse(str(_frontend_dir / "index.html"))

    return application


# Default app instance — used by ``uvicorn src.api.server:app``
app = create_app()
