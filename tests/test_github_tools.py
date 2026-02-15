"""Tests for GitHub integration tools — real git, real GitHub API (with skip guards)."""

from __future__ import annotations

import os

import pytest
from langgraph.checkpoint.base import empty_checkpoint

from src.checkpointer.git_checkpointer import GitCheckpointer
from src.config import Settings
from src.tools.git_tools import set_checkpointer as set_git_checkpointer
from src.tools.github_tools import (
    init_github,
    push_to_github,
    create_issue_from_checkpoint,
    create_conversation_pr,
    share_as_gist,
    ALL_GITHUB_TOOLS,
)
import src.tools.github_tools as github_tools_mod
from src.tools.github_helpers import (
    ensure_remote_repo,
    generate_conversation_transcript,
    generate_conversation_diff_markdown,
)

# ---------------------------------------------------------------------------
# Skip guards
# ---------------------------------------------------------------------------

needs_github = pytest.mark.skipif(
    not os.getenv("GITHUB_TOKEN"), reason="GITHUB_TOKEN not set"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(thread_id: str, checkpoint_id: str | None = None) -> dict:
    cfg: dict = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    if checkpoint_id:
        cfg["configurable"]["checkpoint_id"] = checkpoint_id
    return cfg


def _put_checkpoint(cp: GitCheckpointer, thread_id: str, **channel_values) -> str:
    """Put a checkpoint and return its SHA."""
    ckpt = empty_checkpoint()
    if channel_values:
        ckpt["channel_values"] = channel_values
    config = _make_config(thread_id)
    meta = {"source": "loop", "step": 0}
    result = cp.put(config, ckpt, meta, {})
    return result["configurable"]["checkpoint_id"]


def _load_settings() -> Settings:
    """Load real settings from .env."""
    return Settings()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def setup_all(tmp_path):
    """Wire up a fresh checkpointer for every test.

    GitHub client is only initialised if GITHUB_TOKEN is present.
    """
    repo_path = os.path.join(str(tmp_path), "test_conversations")
    cp = GitCheckpointer(repo_path=repo_path)

    # Wire into git tools
    set_git_checkpointer(cp)

    # Wire into github tools with real settings if available
    try:
        settings = _load_settings()
    except Exception:
        # Minimal settings for non-GitHub tests
        settings = Settings(
            anthropic_api_key="unused",
            smallest_api_key="unused",
            github_token="",
        )

    init_github(settings, checkpointer=cp)

    yield {
        "cp": cp,
        "settings": settings,
    }

    # Teardown
    set_git_checkpointer(None)  # type: ignore[arg-type]
    github_tools_mod._github = None
    github_tools_mod._settings = None
    github_tools_mod._checkpointer = None


# ---------------------------------------------------------------------------
# Helper tests — pure git, no GitHub API needed
# ---------------------------------------------------------------------------

class TestGenerateTranscript:
    def test_generates_markdown(self, setup_all):
        cp = setup_all["cp"]
        _put_checkpoint(cp, "t1", messages=[
            {"role": "user", "content": "Hello!"},
            {"role": "assistant", "content": "Hi there!"},
        ])

        transcript = generate_conversation_transcript(cp, "t1")
        assert "# Conversation: t1" in transcript
        assert "Hello!" in transcript
        assert "Hi there!" in transcript

    def test_nonexistent_thread(self, setup_all):
        cp = setup_all["cp"]
        result = generate_conversation_transcript(cp, "ghost")
        assert "not found" in result

    def test_transcript_with_non_message_state(self, setup_all):
        cp = setup_all["cp"]
        _put_checkpoint(cp, "t1", count=42, topic="budget")
        transcript = generate_conversation_transcript(cp, "t1")
        assert "count" in transcript
        assert "budget" in transcript


class TestGenerateDiffMarkdown:
    def test_generates_diff(self, setup_all):
        cp = setup_all["cp"]
        _put_checkpoint(cp, "alpha", data="a-stuff")
        _put_checkpoint(cp, "beta", data="b-stuff")

        diff = generate_conversation_diff_markdown(cp, "alpha", "beta")
        assert "Conversation Diff" in diff
        assert "alpha" in diff
        assert "beta" in diff

    def test_missing_thread(self, setup_all):
        cp = setup_all["cp"]
        _put_checkpoint(cp, "alpha", data="a")
        diff = generate_conversation_diff_markdown(cp, "alpha", "ghost")
        assert "Error" in diff or "not found" in diff


# ---------------------------------------------------------------------------
# push_to_github — requires GITHUB_TOKEN
# ---------------------------------------------------------------------------

@needs_github
class TestPushToGithub:
    def test_push_returns_url(self, setup_all):
        cp = setup_all["cp"]
        _put_checkpoint(cp, "t1", data="hello")

        result = push_to_github.invoke({"thread_id": "t1"})
        assert "Pushed" in result
        assert "thread-t1" in result
        assert "github.com" in result

    def test_push_nonexistent_thread(self, setup_all):
        result = push_to_github.invoke({"thread_id": "ghost"})
        assert "Error" in result


# ---------------------------------------------------------------------------
# create_issue_from_checkpoint — requires GITHUB_TOKEN
# ---------------------------------------------------------------------------

@needs_github
class TestCreateIssueFromCheckpoint:
    def test_creates_issue_with_title(self, setup_all):
        cp = setup_all["cp"]
        sha = _put_checkpoint(cp, "t1", messages=[
            {"role": "user", "content": "What about the budget?"},
        ])

        result = create_issue_from_checkpoint.invoke({
            "thread_id": "t1",
            "checkpoint_id": sha,
            "title": "Budget Discussion",
        })

        assert "Created issue" in result
        assert "issues/" in result

    def test_auto_title_from_message(self, setup_all):
        cp = setup_all["cp"]
        sha = _put_checkpoint(cp, "t1", messages=[
            {"role": "user", "content": "This is an interesting conversation moment"},
        ])

        result = create_issue_from_checkpoint.invoke({
            "thread_id": "t1",
            "checkpoint_id": sha,
        })

        assert "Created issue" in result

    def test_bad_checkpoint_returns_error(self, setup_all):
        cp = setup_all["cp"]
        _put_checkpoint(cp, "t1")

        result = create_issue_from_checkpoint.invoke({
            "thread_id": "t1",
            "checkpoint_id": "0" * 40,
        })
        assert "Error" in result or "not found" in result


# ---------------------------------------------------------------------------
# create_conversation_pr — requires GITHUB_TOKEN
# ---------------------------------------------------------------------------

@needs_github
class TestCreateConversationPR:
    def test_creates_pr(self, setup_all):
        cp = setup_all["cp"]
        _put_checkpoint(cp, "main", data="base")
        _put_checkpoint(cp, "feature", data="new-feature")

        result = create_conversation_pr.invoke({
            "source_thread_id": "feature",
            "target_thread_id": "main",
            "title": "Review my feature convo",
        })

        assert "Created PR" in result or "Error" not in result

    def test_pr_missing_source(self, setup_all):
        cp = setup_all["cp"]
        _put_checkpoint(cp, "main", data="base")

        result = create_conversation_pr.invoke({
            "source_thread_id": "ghost",
            "target_thread_id": "main",
        })
        assert "Error" in result

    def test_pr_missing_target(self, setup_all):
        cp = setup_all["cp"]
        _put_checkpoint(cp, "feature", data="stuff")

        result = create_conversation_pr.invoke({
            "source_thread_id": "feature",
            "target_thread_id": "ghost",
        })
        assert "Error" in result


# ---------------------------------------------------------------------------
# share_as_gist — requires GITHUB_TOKEN
# ---------------------------------------------------------------------------

@needs_github
class TestShareAsGist:
    def test_creates_gist(self, setup_all):
        cp = setup_all["cp"]
        _put_checkpoint(cp, "t1", messages=[
            {"role": "user", "content": "Hello"},
        ])

        result = share_as_gist.invoke({"thread_id": "t1"})
        assert "gist" in result.lower()
        assert "gist.github.com" in result

    def test_gist_is_secret_by_default(self, setup_all):
        cp = setup_all["cp"]
        _put_checkpoint(cp, "t1", data="hello")

        result = share_as_gist.invoke({"thread_id": "t1"})
        assert "secret" in result

    def test_gist_can_be_public(self, setup_all):
        cp = setup_all["cp"]
        _put_checkpoint(cp, "t1", data="hello")

        result = share_as_gist.invoke({"thread_id": "t1", "public": True})
        assert "public" in result

    def test_gist_nonexistent_thread(self, setup_all):
        result = share_as_gist.invoke({"thread_id": "ghost"})
        assert "not found" in result


# ---------------------------------------------------------------------------
# Tool metadata — no API needed
# ---------------------------------------------------------------------------

class TestToolMetadata:
    def test_all_tools_have_names(self):
        expected = {
            "push_to_github",
            "create_issue_from_checkpoint",
            "create_conversation_pr",
            "share_as_gist",
        }
        assert {t.name for t in ALL_GITHUB_TOOLS} == expected

    def test_all_tools_are_invocable(self):
        for t in ALL_GITHUB_TOOLS:
            assert hasattr(t, "invoke")


# ---------------------------------------------------------------------------
# init_github — no API needed (tests module-level wiring)
# ---------------------------------------------------------------------------

class TestInitGithub:
    def test_init_sets_module_state(self, setup_all):
        cp = setup_all["cp"]
        settings = Settings(
            anthropic_api_key="test",
            smallest_api_key="test",
            github_token="",
        )

        init_github(settings, checkpointer=cp)

        assert github_tools_mod._settings is settings
        assert github_tools_mod._checkpointer is cp

    def test_init_skips_github_if_no_token(self, setup_all):
        settings = Settings(
            anthropic_api_key="test",
            smallest_api_key="test",
            github_token="",
        )
        github_tools_mod._github = None

        init_github(settings)

        assert github_tools_mod._github is None


# ---------------------------------------------------------------------------
# ensure_remote_repo — requires GITHUB_TOKEN
# ---------------------------------------------------------------------------

@needs_github
class TestEnsureRemoteRepo:
    def test_returns_existing_repo(self, setup_all):
        from github import Auth, Github

        settings = _load_settings()
        gh = Github(auth=Auth.Token(settings.github_token))
        repo = ensure_remote_repo(
            gh, settings.github_owner, settings.github_conversations_repo
        )
        assert repo is not None
        assert repo.name == settings.github_conversations_repo
