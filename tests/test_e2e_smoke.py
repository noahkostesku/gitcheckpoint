"""End-to-end smoke test — runs the full pipeline with real APIs.

Requires ANTHROPIC_API_KEY to be set. GITHUB_TOKEN enables gist tests.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

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

@pytest.fixture(scope="module")
def e2e_client(tmp_path_factory):
    """Create a real app with real API keys for e2e testing."""
    tmp = tmp_path_factory.mktemp("e2e")
    repo_path = str(tmp / "conversations")
    cp = GitCheckpointer(repo_path)

    settings = Settings()
    graph = build_supervisor_graph(settings, checkpointer=cp)

    set_checkpointer(cp)
    init_github(settings, checkpointer=cp)

    application = create_app(
        settings=settings,
        checkpointer=cp,
        graph=graph,
    )

    yield TestClient(application), cp


# ---------------------------------------------------------------------------
# Full pipeline smoke test
# ---------------------------------------------------------------------------

@needs_anthropic
class TestFullPipeline:
    def test_health(self, e2e_client):
        client, _ = e2e_client
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_chat_creates_response(self, e2e_client):
        client, _ = e2e_client
        r = client.post("/api/chat", json={
            "message": "Hello, say just 'Hi back' and nothing else",
            "thread_id": "smoke-test",
        })
        assert r.status_code == 200
        data = r.json()
        assert "response" in data
        assert len(data["response"]) > 0
        assert data["thread_id"] == "smoke-test"

    def test_second_message_builds_history(self, e2e_client):
        client, _ = e2e_client
        r = client.post("/api/chat", json={
            "message": "What was my first message? Reply in 5 words or less.",
            "thread_id": "smoke-test",
        })
        assert r.status_code == 200
        assert len(r.json()["response"]) > 0

    def test_checkpoint_after_chat(self, e2e_client):
        client, cp = e2e_client
        r = client.post("/api/checkpoint", json={
            "thread_id": "smoke-test",
            "label": "after-hello",
        })
        assert r.status_code == 200
        assert "after-hello" in r.json()["result"]

    def test_list_threads(self, e2e_client):
        client, _ = e2e_client
        r = client.get("/api/threads")
        assert r.status_code == 200
        assert "smoke-test" in r.json()["result"]

    def test_conversation_log(self, e2e_client):
        client, _ = e2e_client
        r = client.get("/api/threads/smoke-test/log")
        assert r.status_code == 200
        result = r.json()["result"]
        assert "thread-smoke-test" in result or "*" in result

    def test_fork_conversation(self, e2e_client):
        client, cp = e2e_client
        # Get the HEAD SHA to fork from
        branch = cp.repo.branches[cp._branch_name("smoke-test")]
        sha = branch.commit.hexsha

        r = client.post("/api/fork", json={
            "source_thread_id": "smoke-test",
            "checkpoint_id": sha,
            "new_thread_name": "smoke-fork",
        })
        assert r.status_code == 200
        assert "smoke-fork" in r.json()["result"]

    def test_chat_on_fork(self, e2e_client):
        client, _ = e2e_client
        r = client.post("/api/chat", json={
            "message": "We forked! Say 'Fork acknowledged' and nothing else.",
            "thread_id": "smoke-fork",
        })
        assert r.status_code == 200
        assert len(r.json()["response"]) > 0

    def test_threads_shows_both(self, e2e_client):
        client, _ = e2e_client
        r = client.get("/api/threads")
        assert r.status_code == 200
        result = r.json()["result"]
        assert "smoke-test" in result
        assert "smoke-fork" in result

    def test_merge_fork_back(self, e2e_client):
        client, _ = e2e_client
        r = client.post("/api/merge", json={
            "source_thread_id": "smoke-fork",
            "target_thread_id": "smoke-test",
        })
        assert r.status_code == 200
        assert "Merged" in r.json()["result"]


@needs_anthropic
@needs_github
class TestGistE2E:
    def test_share_as_gist(self, e2e_client):
        client, _ = e2e_client
        # First ensure there's data on the thread
        client.post("/api/chat", json={
            "message": "This will be shared as a gist. Reply 'Noted'.",
            "thread_id": "gist-test",
        })

        r = client.post("/api/github/gist", json={
            "thread_id": "gist-test",
        })
        assert r.status_code == 200
        result = r.json()["result"]
        assert "gist.github.com" in result
