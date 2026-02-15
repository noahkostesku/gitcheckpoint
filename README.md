# GitCheckpoint

Version control for AI conversations. Save, rewind, branch, and merge your chats like code -- with voice.

## What It Does

- Every conversation turn becomes a Git commit
- Branch conversations to explore "what if" scenarios
- Rewind to any point in a conversation
- Fork, merge, and diff conversation threads
- Push conversation history to GitHub
- Talk to it -- voice-first interface with a floating orb UI

## System Architecture

```
+-----------------------------------------------------------+
|                        BROWSER                            |
|                                                           |
|   VoiceOrb        ThreadSidebar    GitGraph    ChatPanel  |
|   (mic/speaker)   (branches)       (commits)   (text)    |
|       |                |               |           |      |
|       +--------+-------+-------+-------+-----------+      |
|                |               |                          |
|          voiceSocket.js     api.js                        |
|          (WebSocket)        (REST)                        |
+--------------|----------------|---------------------------+
               |                |
          wss://ws/voice   https://api/*
               |                |
+--------------|----------------|---------------------------+
|              v                v          FASTAPI SERVER    |
|   +-------------------+  +------------------+             |
|   |   Voice Pipeline  |  |   REST Handlers  |             |
|   |                   |  |                  |             |
|   |  WebM -> WAV      |  |  /api/chat       |             |
|   |  Pulse STT        |  |  /api/checkpoint |             |
|   |  Sentence Buffer  |  |  /api/fork       |             |
|   |  Waves TTS        |  |  /api/merge      |             |
|   +--------+----------+  |  /api/push ...   |             |
|            |              +--------+---------+             |
|            |                       |                      |
|            +-----------+-----------+                      |
|                        |                                  |
|                        v                                  |
|            +-----------------------+                      |
|            | LangGraph Supervisor  |                      |
|            |   (Claude Sonnet)     |                      |
|            +-----------+-----------+                      |
|                        |                                  |
|          +-------------+-------------+                    |
|          |             |             |                    |
|          v             v             v                    |
|   conversation   git_ops       github_ops                |
|     _agent        _agent         _agent                  |
|          |             |             |                    |
|          |        +----+----+   +----+----+              |
|          |        |  Tools  |   |  Tools  |              |
|          |        +---------+   +---------+              |
|          |        checkpoint    push                     |
|          |        rewind        gist                     |
|          |        fork          issues                   |
|          |        merge                                  |
|          |        diff                                   |
|          |             |             |                    |
|          +-------------+-------------+                   |
|                        |                                  |
|             +----------+----------+                       |
|             |                     |                       |
|             v                     v                       |
|   +------------------+  +-------------------+             |
|   | GitCheckpointer  |  |    GitHub API     |             |
|   | (.conversations/ |  |    (PyGithub)     |             |
|   |   local git repo)|  +-------------------+             |
|   +------------------+                                    |
|   thread = branch                                         |
|   checkpoint = commit                                     |
|   state = JSON in tree                                    |
+-----------------------------------------------------------+
```

## LangGraph Agent Architecture

```
                         +-------+
                         | START |
                         +---+---+
                             |
                             v
                    +--------+--------+
                    |   SUPERVISOR    |
                    |  (Claude LLM)  |
                    |                 |
                    |  - classifies   |
                    |    user intent  |
                    |  - picks agent  |
                    |    or FINISH    |
                    +---+----+----+--+
                        |    |    |
          +-------------+    |    +-------------+
          |                  |                  |
          v                  v                  v
+---------+------+ +--------+-------+ +--------+--------+
| conversation   | | git_ops        | | github_ops      |
| _agent         | | _agent         | | _agent          |
|                | |                | |                 |
| General chat,  | | Git tools:     | | GitHub tools:   |
| planning,      | |  checkpoint    | |  push           |
| brainstorming, | |  time_travel   | |  share_as_gist  |
| questions      | |  fork          | |  create_issue   |
|                | |  merge         | |  create_pr      |
|                | |  diff          | |                 |
|                | |  list_branches | |                 |
|                | |  conv_log      | |                 |
+-------+--------+ +-------+--------+ +--------+--------+
        |                   |                   |
        +-------------------+-------------------+
                            |
                            v
                   +--------+--------+
                   |   SUPERVISOR    |
                   | (routes again   |
                   |  or FINISH)     |
                   +--------+--------+
                            |
                            v
                  +---------+---------+
                  | MAYBE_SUMMARIZE   |
                  |                   |
                  | if messages > 20: |
                  |   compress older  |
                  |   into summary    |
                  +---------+---------+
                            |
                            v
                        +---+---+
                        |  END  |
                        +-------+

State at every step:
  - messages[]        shared conversation history
  - next              routing decision
  - agent_responded   prevents double-routing
  - summary           compressed older context
```

## Voice Pipeline

```
 MIC                                                       SPEAKER
  |                                                           ^
  v                                                           |
[MediaRecorder]                                    [Web Audio API]
  |  (WebM/Opus, 250ms chunks)                       ^  (decode + play)
  v                                                   |
[WebSocket binary frames]                    [base64 audio_chunk]
  |                                                   ^
  v                                                   |
[audio_converter]                            [Smallest.ai Waves]
  |  WebM -> WAV (ffmpeg)                      ^  TTS per sentence
  v                                            |
[Pulse STT]                              [sentence_buffer]
  |  WAV -> transcript                     ^  tokens -> sentences
  v                                        |
[Supervisor] -----> [Agent] -----> [stream response tokens]
```

## Agent Workflow

1. User speaks or types a message
2. Supervisor LLM classifies intent and routes to the appropriate agent
3. Agent executes tools (git operations, GitHub API calls, or plain conversation)
4. Response streams back as text tokens, buffered into sentences for TTS
5. Audio chunks stream to the browser for playback
6. After playback finishes, mic auto-resumes for the next turn

Routing rules:
- `conversation_agent` -- general chat, planning, brainstorming
- `git_ops_agent` -- save, checkpoint, rewind, fork, merge, diff, time travel
- `github_ops_agent` -- push, gist, share, issues, pull requests

## API Routes

### REST

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | Send a message, get agent response |
| POST | `/api/checkpoint` | Create a named checkpoint |
| POST | `/api/time-travel` | Rewind to a specific checkpoint |
| POST | `/api/fork` | Fork a conversation at a checkpoint |
| POST | `/api/merge` | Merge two conversation branches |
| GET | `/api/threads` | List all conversation threads |
| GET | `/api/threads/{id}/log` | Get conversation log for a thread |
| GET | `/api/threads/{id}/diff/{a}/{b}` | Diff between two checkpoints |
| POST | `/api/github/push` | Push a thread to GitHub |
| POST | `/api/github/gist` | Share a thread as a GitHub Gist |
| GET | `/health` | Health check |

### WebSocket

| Path | Description |
|------|-------------|
| `/ws/voice` | Bidirectional voice -- audio in, audio + text out |
| `/ws/chat` | Text-based streaming chat |

## File Structure

```
gitcheckpoint/
├── main.py                          # Entry point (uvicorn)
├── Dockerfile
├── pyproject.toml
├── requirements.txt
│
├── src/
│   ├── config.py                    # Pydantic settings (.env)
│   │
│   ├── checkpointer/
│   │   └── git_checkpointer.py      # Core: Git-backed LangGraph checkpointer
│   │
│   ├── graph/
│   │   ├── state.py                 # ConversationState type
│   │   └── supervisor.py            # Supervisor graph + routing logic
│   │
│   ├── agents/
│   │   ├── conversation_agent.py    # General conversation
│   │   ├── git_ops_agent.py         # Git operations
│   │   └── github_ops_agent.py      # GitHub operations
│   │
│   ├── tools/
│   │   ├── git_tools.py             # @tool: checkpoint, rewind, fork, merge, diff
│   │   ├── github_tools.py          # @tool: push, gist
│   │   ├── github_helpers.py        # GitHub API utilities
│   │   └── memory_tools.py          # Cross-session memory
│   │
│   ├── voice/
│   │   ├── tts_service.py           # Smallest.ai Waves TTS
│   │   ├── audio_converter.py       # WebM to WAV conversion
│   │   ├── sentence_buffer.py       # Sentence-level TTS streaming
│   │   ├── command_parser.py        # Voice intent parsing
│   │   ├── atoms_agent.py           # Smallest.ai Atoms config
│   │   └── session_manager.py       # Voice session management
│   │
│   └── api/
│       └── server.py                # FastAPI app, all routes, WS handlers
│
├── frontend/
│   ├── index.html
│   ├── vite.config.js
│   └── src/
│       ├── App.jsx                  # Main layout
│       ├── components/
│       │   ├── VoiceOrb.jsx         # Floating animated orb (voice UI)
│       │   ├── ChatPanel.jsx        # Text chat interface
│       │   ├── ThreadSidebar.jsx    # Thread list sidebar
│       │   ├── GitGraph.jsx         # Commit graph visualization
│       │   ├── ControlsBar.jsx      # Action buttons
│       │   └── DiffViewer.jsx       # Checkpoint diff display
│       └── lib/
│           ├── api.js               # REST client
│           ├── voiceSocket.js       # Voice WebSocket client + audio playback
│           └── websocket.js         # Chat WebSocket client
│
└── tests/
    ├── test_git_checkpointer.py
    ├── test_supervisor.py
    ├── test_git_tools.py
    ├── test_github_tools.py
    ├── test_voice.py
    └── test_api.py
```

## Setup

```bash
# Backend
cp .env.example .env   # Fill in API keys
pip install -e ".[voice,dev]"
python main.py

# Frontend
cd frontend
npm install
npm run dev
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key |
| `SMALLEST_API_KEY` | Yes | Smallest.ai API key |
| `GITHUB_TOKEN` | No | GitHub fine-grained token (for push/gist) |
| `GITHUB_OWNER` | No | GitHub username |
| `GITHUB_CONVERSATIONS_REPO` | No | Repo name for pushed conversations |
| `VITE_API_URL` | No | Backend URL for frontend (production) |

## Tech Stack

- **Backend:** Python, FastAPI, LangGraph, LangChain, GitPython, PyGithub
- **LLM:** Claude Sonnet (via langchain-anthropic)
- **Voice:** Smallest.ai Waves (TTS) + Atoms (voice agent)
- **Frontend:** React, Vite, Framer Motion, Web Audio API
- **Storage:** Git repository (conversations), MemorySaver / Postgres / Redis (state)

## Tests

```bash
python -m pytest tests/ -v
```

## License

MIT
