"""FastAPI server — ties together the LangGraph supervisor, git tools, and voice layer."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

import fastapi
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.checkpointer.git_checkpointer import GitCheckpointer
from src.config import Settings
from src.graph.supervisor import build_supervisor_graph
from src.voice.command_parser import VoiceCommandParser
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
    return application


# Default app instance — used by ``uvicorn src.api.server:app``
app = create_app()
