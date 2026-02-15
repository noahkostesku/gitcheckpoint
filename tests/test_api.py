"""Tests for the FastAPI server — real git, real graph (with skip guards for LLM)."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.base import empty_checkpoint

from src.checkpointer.git_checkpointer import GitCheckpointer
from src.config import Settings
from src.graph.supervisor import build_supervisor_graph
from src.tools.git_tools import set_checkpointer
from src.tools.github_tools import init_github
from src.api.server import create_app

# ---------------------------------------------------------------------------
# Skip guards
# ---------------------------------------------------------------------------

needs_anthropic = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set"
)

needs_github = pytest.mark.skipif(
    not os.getenv("GITHUB_TOKEN"), reason="GITHUB_TOKEN not set"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_repo(tmp_path):
    """Create a temporary GitCheckpointer repo."""
    repo_path = str(tmp_path / "conversations")
    cp = GitCheckpointer(repo_path)
    return cp


@pytest.fixture()
def settings(tmp_repo):
    """Build a real Settings object with a dummy Anthropic key for graph compilation."""
    return Settings(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "sk-test-dummy"),
        smallest_api_key=os.getenv("SMALLEST_API_KEY", "sk-test-dummy"),
        github_token=os.getenv("GITHUB_TOKEN", ""),
        checkpoint_dir=tmp_repo.repo_path,
    )


@pytest.fixture()
def graph(settings, tmp_repo):
    """Build a real compiled supervisor graph."""
    return build_supervisor_graph(settings, checkpointer=tmp_repo)


@pytest.fixture()
def client(tmp_repo, graph, settings):
    """Provide a TestClient wired to a real app with real graph."""
    set_checkpointer(tmp_repo)
    init_github(settings, checkpointer=tmp_repo)

    application = create_app(
        settings=settings,
        checkpointer=tmp_repo,
        graph=graph,
    )

    return TestClient(application)


# ---------------------------------------------------------------------------
# Helpers — seed data
# ---------------------------------------------------------------------------

def _seed_thread(cp: GitCheckpointer, thread_id: str, n: int = 2):
    """Create *n* checkpoints on *thread_id*, return list of SHAs."""
    shas = []
    for i in range(n):
        checkpoint = empty_checkpoint()
        checkpoint["channel_values"] = {
            "messages": [{"role": "user", "content": f"Message {i}"}]
        }
        config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
            }
        }
        result = cp.put(config, checkpoint, {"source": "input", "step": i}, {})
        shas.append(result["configurable"]["checkpoint_id"])
    return shas


# ---------------------------------------------------------------------------
# 13. GET /api/health — always runs
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_health_returns_200(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "gitcheckpoint"


# ---------------------------------------------------------------------------
# 1. POST /api/chat — requires ANTHROPIC_API_KEY
# ---------------------------------------------------------------------------

@needs_anthropic
class TestChat:
    def test_chat_returns_response(self, client):
        resp = client.post(
            "/api/chat",
            json={"message": "Hello, say just 'Hi' in one word", "thread_id": "test-thread"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["response"]) > 0
        assert data["thread_id"] == "test-thread"

    def test_chat_default_thread(self, client):
        resp = client.post("/api/chat", json={"message": "Say just 'OK'"})
        assert resp.status_code == 200
        assert resp.json()["thread_id"] == "default"


# ---------------------------------------------------------------------------
# 6. GET /api/threads — always runs (pure git)
# ---------------------------------------------------------------------------

class TestListThreads:
    def test_empty_threads(self, client):
        resp = client.get("/api/threads")
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data

    def test_threads_after_seed(self, client, tmp_repo):
        _seed_thread(tmp_repo, "alpha")
        _seed_thread(tmp_repo, "beta")
        resp = client.get("/api/threads")
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert "alpha" in result
        assert "beta" in result


# ---------------------------------------------------------------------------
# 2. POST /api/checkpoint — always runs (pure git)
# ---------------------------------------------------------------------------

class TestCheckpoint:
    def test_create_checkpoint(self, client, tmp_repo):
        _seed_thread(tmp_repo, "ck-thread")
        resp = client.post(
            "/api/checkpoint",
            json={"thread_id": "ck-thread", "label": "my-save-point"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "my-save-point" in data["result"]

    def test_checkpoint_creates_commit(self, client, tmp_repo):
        _seed_thread(tmp_repo, "ck2")
        resp = client.post(
            "/api/checkpoint",
            json={"thread_id": "ck2", "label": "second-save"},
        )
        assert resp.status_code == 200
        branch = tmp_repo.repo.branches[tmp_repo._branch_name("ck2")]
        assert "second-save" in branch.commit.message


# ---------------------------------------------------------------------------
# 7. GET /api/threads/{thread_id}/log — always runs
# ---------------------------------------------------------------------------

class TestConversationLog:
    def test_log_returns_entries(self, client, tmp_repo):
        _seed_thread(tmp_repo, "log-thread", n=3)
        resp = client.get("/api/threads/log-thread/log")
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert "checkpoint" in result.lower() or "*" in result

    def test_log_with_limit(self, client, tmp_repo):
        _seed_thread(tmp_repo, "log-lim", n=5)
        resp = client.get("/api/threads/log-lim/log?limit=2")
        assert resp.status_code == 200

    def test_log_missing_thread(self, client):
        resp = client.get("/api/threads/nonexistent/log")
        assert resp.status_code == 200
        assert "not found" in resp.json()["result"].lower()


# ---------------------------------------------------------------------------
# 3. POST /api/time-travel — always runs
# ---------------------------------------------------------------------------

class TestTimeTravel:
    def test_time_travel_to_checkpoint(self, client, tmp_repo):
        shas = _seed_thread(tmp_repo, "tt-thread", n=3)
        resp = client.post(
            "/api/time-travel",
            json={"thread_id": "tt-thread", "checkpoint_id": shas[0]},
        )
        assert resp.status_code == 200
        assert "Time traveled" in resp.json()["result"]

    def test_time_travel_bad_sha(self, client, tmp_repo):
        _seed_thread(tmp_repo, "tt2")
        resp = client.post(
            "/api/time-travel",
            json={"thread_id": "tt2", "checkpoint_id": "0" * 40},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 4. POST /api/fork — always runs
# ---------------------------------------------------------------------------

class TestFork:
    def test_fork_conversation(self, client, tmp_repo):
        shas = _seed_thread(tmp_repo, "fork-src", n=2)
        resp = client.post(
            "/api/fork",
            json={
                "source_thread_id": "fork-src",
                "checkpoint_id": shas[0],
                "new_thread_name": "fork-dest",
            },
        )
        assert resp.status_code == 200
        assert "fork-dest" in resp.json()["result"]
        branch_names = [b.name for b in tmp_repo.repo.branches]
        assert tmp_repo._branch_name("fork-dest") in branch_names

    def test_fork_duplicate_name(self, client, tmp_repo):
        shas = _seed_thread(tmp_repo, "dup-src")
        _seed_thread(tmp_repo, "dup-dest")
        resp = client.post(
            "/api/fork",
            json={
                "source_thread_id": "dup-src",
                "checkpoint_id": shas[0],
                "new_thread_name": "dup-dest",
            },
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 5. POST /api/merge — always runs
# ---------------------------------------------------------------------------

class TestMerge:
    def test_merge_conversations(self, client, tmp_repo):
        _seed_thread(tmp_repo, "merge-src")
        _seed_thread(tmp_repo, "merge-tgt")
        resp = client.post(
            "/api/merge",
            json={
                "source_thread_id": "merge-src",
                "target_thread_id": "merge-tgt",
            },
        )
        assert resp.status_code == 200
        assert "Merged" in resp.json()["result"]

    def test_merge_missing_source(self, client):
        resp = client.post(
            "/api/merge",
            json={
                "source_thread_id": "ghost",
                "target_thread_id": "also-ghost",
            },
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 8. GET /api/threads/{thread_id}/diff/{a}/{b} — always runs
# ---------------------------------------------------------------------------

class TestDiff:
    def test_diff_between_checkpoints(self, client, tmp_repo):
        shas = _seed_thread(tmp_repo, "diff-thread", n=3)
        resp = client.get(
            f"/api/threads/diff-thread/diff/{shas[0]}/{shas[2]}"
        )
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert "Diff" in result or "diff" in result.lower()

    def test_diff_bad_sha(self, client, tmp_repo):
        shas = _seed_thread(tmp_repo, "diff2")
        resp = client.get(
            f"/api/threads/diff2/diff/{shas[0]}/{'0' * 40}"
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 9. POST /api/github/push — error handling (no token = clean 400)
# ---------------------------------------------------------------------------

class TestGithubPush:
    def test_push_missing_thread(self, client):
        resp = client.post(
            "/api/github/push",
            json={"thread_id": "no-such-thread"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 10. POST /api/github/gist — error handling
# ---------------------------------------------------------------------------

class TestGithubGist:
    def test_gist_missing_thread(self, client):
        resp = client.post(
            "/api/github/gist",
            json={"thread_id": "no-thread"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 12. POST /api/voice/webhook — always runs
# ---------------------------------------------------------------------------

class TestVoiceWebhook:
    def test_call_started(self, client):
        resp = client.post(
            "/api/voice/webhook",
            json={"event": "call_started", "call_id": "call-1"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "session_registered"

    def test_call_ended(self, client):
        resp = client.post(
            "/api/voice/webhook",
            json={"event": "call_ended", "call_id": "call-2"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "session_ended"

    def test_unhandled_event(self, client):
        resp = client.post(
            "/api/voice/webhook",
            json={"event": "something_else"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "unhandled_event"


# ---------------------------------------------------------------------------
# 11. WebSocket /ws/chat — requires ANTHROPIC_API_KEY for full round-trip
# ---------------------------------------------------------------------------

class TestWebSocket:
    def test_websocket_connection(self, client):
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_text("ws-thread")
            # Connection accepted = success


# ---------------------------------------------------------------------------
# Full flow: seed → checkpoint → fork → merge (pure git, always runs)
# ---------------------------------------------------------------------------

class TestFullFlow:
    def test_chat_checkpoint_fork_merge(self, client, tmp_repo):
        # 1. Seed the thread with data
        shas = _seed_thread(tmp_repo, "flow-thread", n=2)

        # 2. Create a named checkpoint
        resp = client.post(
            "/api/checkpoint",
            json={"thread_id": "flow-thread", "label": "milestone-1"},
        )
        assert resp.status_code == 200

        # Get the checkpoint SHA from the branch HEAD
        branch = tmp_repo.repo.branches[tmp_repo._branch_name("flow-thread")]
        fork_sha = branch.commit.hexsha

        # 3. Fork at that checkpoint
        resp = client.post(
            "/api/fork",
            json={
                "source_thread_id": "flow-thread",
                "checkpoint_id": fork_sha,
                "new_thread_name": "flow-fork",
            },
        )
        assert resp.status_code == 200

        # 4. Verify both threads exist
        resp = client.get("/api/threads")
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert "flow-thread" in result
        assert "flow-fork" in result

        # 5. Add some data to the fork
        _seed_thread(tmp_repo, "flow-fork", n=1)

        # 6. Merge fork back
        resp = client.post(
            "/api/merge",
            json={
                "source_thread_id": "flow-fork",
                "target_thread_id": "flow-thread",
            },
        )
        assert resp.status_code == 200
        assert "Merged" in resp.json()["result"]

        # 7. Check log shows the merge
        resp = client.get("/api/threads/flow-thread/log")
        assert resp.status_code == 200
