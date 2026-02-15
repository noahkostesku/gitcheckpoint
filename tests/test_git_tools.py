"""Tests for the real git operation tools."""

import json
import os

import pytest
from langgraph.checkpoint.base import empty_checkpoint

from src.checkpointer.git_checkpointer import GitCheckpointer
from src.tools.git_tools import (
    set_checkpointer,
    get_checkpointer,
    create_checkpoint,
    time_travel,
    fork_conversation,
    merge_conversations,
    conversation_diff,
    conversation_log,
    list_branches,
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
    """Create a checkpoint via the checkpointer and return its SHA."""
    ckpt = empty_checkpoint()
    if channel_values:
        ckpt["channel_values"] = channel_values
    config = _make_config(thread_id)
    meta = {"source": "loop", "step": 0}
    result = cp.put(config, ckpt, meta, {})
    return result["configurable"]["checkpoint_id"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def setup_checkpointer(tmp_path):
    """Create a fresh GitCheckpointer and wire it into the tools module."""
    repo_path = os.path.join(str(tmp_path), "test_conversations")
    cp = GitCheckpointer(repo_path=repo_path)
    set_checkpointer(cp)
    yield cp
    set_checkpointer(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# create_checkpoint
# ---------------------------------------------------------------------------

class TestCreateCheckpoint:
    def test_creates_git_commit(self, setup_checkpointer):
        cp = setup_checkpointer
        # First put a real checkpoint so the branch exists with state
        _put_checkpoint(cp, "t1", messages=["hello"])

        result = create_checkpoint.invoke({"label": "budget-discussion", "thread_id": "t1"})
        assert "budget-discussion" in result
        assert "commit" in result
        assert "t1" in result

    def test_commit_message_is_label(self, setup_checkpointer):
        cp = setup_checkpointer
        _put_checkpoint(cp, "t1")

        create_checkpoint.invoke({"label": "my-label", "thread_id": "t1"})

        branch = cp.repo.branches["thread-t1"]
        head_msg = branch.commit.message.strip()
        assert head_msg == "my-label"

    def test_creates_branch_if_new(self, setup_checkpointer):
        cp = setup_checkpointer
        create_checkpoint.invoke({"label": "first", "thread_id": "new-thread"})
        assert "thread-new-thread" in [b.name for b in cp.repo.branches]


# ---------------------------------------------------------------------------
# time_travel
# ---------------------------------------------------------------------------

class TestTimeTravel:
    def test_loads_correct_state(self, setup_checkpointer):
        cp = setup_checkpointer
        sha1 = _put_checkpoint(cp, "t1", count=1, topic="budget")
        _put_checkpoint(cp, "t1", count=2, topic="timeline")

        result = time_travel.invoke({"thread_id": "t1", "checkpoint_id": sha1})
        assert sha1[:7] in result
        assert "count: 1" in result
        assert "topic: budget" in result

    def test_nonexistent_checkpoint(self, setup_checkpointer):
        _put_checkpoint(setup_checkpointer, "t1")
        result = time_travel.invoke({"thread_id": "t1", "checkpoint_id": "0" * 40})
        assert "Error" in result or "not found" in result

    def test_empty_state_summary(self, setup_checkpointer):
        cp = setup_checkpointer
        sha = _put_checkpoint(cp, "t1")
        result = time_travel.invoke({"thread_id": "t1", "checkpoint_id": sha})
        assert sha[:7] in result


# ---------------------------------------------------------------------------
# fork_conversation
# ---------------------------------------------------------------------------

class TestForkConversation:
    def test_creates_new_branch(self, setup_checkpointer):
        cp = setup_checkpointer
        sha = _put_checkpoint(cp, "t1", data="original")

        result = fork_conversation.invoke({
            "source_thread_id": "t1",
            "checkpoint_id": sha,
            "new_thread_name": "alt-path",
        })

        assert "alt-path" in result
        assert sha[:7] in result
        assert "thread-alt-path" in [b.name for b in cp.repo.branches]

    def test_fork_from_mid_history(self, setup_checkpointer):
        cp = setup_checkpointer
        sha1 = _put_checkpoint(cp, "t1", step=1)
        _put_checkpoint(cp, "t1", step=2)
        _put_checkpoint(cp, "t1", step=3)

        fork_conversation.invoke({
            "source_thread_id": "t1",
            "checkpoint_id": sha1,
            "new_thread_name": "from-step1",
        })

        # The forked branch HEAD should be at sha1
        forked = cp.repo.branches["thread-from-step1"]
        assert forked.commit.hexsha == sha1

    def test_fork_duplicate_name_errors(self, setup_checkpointer):
        cp = setup_checkpointer
        sha = _put_checkpoint(cp, "t1")

        fork_conversation.invoke({
            "source_thread_id": "t1",
            "checkpoint_id": sha,
            "new_thread_name": "dup",
        })
        result = fork_conversation.invoke({
            "source_thread_id": "t1",
            "checkpoint_id": sha,
            "new_thread_name": "dup",
        })
        assert "Error" in result or "already exists" in result

    def test_fork_bad_checkpoint_errors(self, setup_checkpointer):
        _put_checkpoint(setup_checkpointer, "t1")
        result = fork_conversation.invoke({
            "source_thread_id": "t1",
            "checkpoint_id": "0" * 40,
            "new_thread_name": "bad",
        })
        assert "Error" in result or "not found" in result


# ---------------------------------------------------------------------------
# merge_conversations
# ---------------------------------------------------------------------------

class TestMergeConversations:
    def test_merge_ours(self, setup_checkpointer):
        cp = setup_checkpointer

        # Create two branches with diverging content
        _put_checkpoint(cp, "main-thread", data="shared-base")
        sha_base = cp.repo.branches["thread-main-thread"].commit.hexsha

        # Fork and add different content to each
        fork_conversation.invoke({
            "source_thread_id": "main-thread",
            "checkpoint_id": sha_base,
            "new_thread_name": "feature",
        })
        _put_checkpoint(cp, "feature", data="feature-work")

        _put_checkpoint(cp, "main-thread", data="main-continued")

        result = merge_conversations.invoke({
            "source_thread_id": "feature",
            "target_thread_id": "main-thread",
            "strategy": "ours",
        })
        assert "Merged" in result
        assert "main-thread" in result

    def test_merge_nonexistent_source(self, setup_checkpointer):
        _put_checkpoint(setup_checkpointer, "target")
        result = merge_conversations.invoke({
            "source_thread_id": "ghost",
            "target_thread_id": "target",
        })
        assert "Error" in result

    def test_merge_nonexistent_target(self, setup_checkpointer):
        _put_checkpoint(setup_checkpointer, "source")
        result = merge_conversations.invoke({
            "source_thread_id": "source",
            "target_thread_id": "ghost",
        })
        assert "Error" in result


# ---------------------------------------------------------------------------
# conversation_diff
# ---------------------------------------------------------------------------

class TestConversationDiff:
    def test_diff_shows_changes(self, setup_checkpointer):
        cp = setup_checkpointer
        sha1 = _put_checkpoint(cp, "t1", count=1, topic="budget")
        sha2 = _put_checkpoint(cp, "t1", count=2, topic="budget", extra="new-field")

        result = conversation_diff.invoke({
            "thread_id": "t1",
            "checkpoint_a": sha1,
            "checkpoint_b": sha2,
        })

        assert sha1[:7] in result
        assert sha2[:7] in result
        assert "count" in result
        assert "extra" in result

    def test_diff_no_changes(self, setup_checkpointer):
        cp = setup_checkpointer
        sha = _put_checkpoint(cp, "t1", data="same")

        result = conversation_diff.invoke({
            "thread_id": "t1",
            "checkpoint_a": sha,
            "checkpoint_b": sha,
        })
        assert "no differences" in result

    def test_diff_bad_checkpoint(self, setup_checkpointer):
        cp = setup_checkpointer
        sha = _put_checkpoint(cp, "t1")

        result = conversation_diff.invoke({
            "thread_id": "t1",
            "checkpoint_a": sha,
            "checkpoint_b": "0" * 40,
        })
        assert "Error" in result or "not found" in result


# ---------------------------------------------------------------------------
# conversation_log
# ---------------------------------------------------------------------------

class TestConversationLog:
    def test_log_shows_commits(self, setup_checkpointer):
        cp = setup_checkpointer
        _put_checkpoint(cp, "t1", step=1)
        _put_checkpoint(cp, "t1", step=2)
        _put_checkpoint(cp, "t1", step=3)

        result = conversation_log.invoke({"thread_id": "t1"})
        assert "thread-t1" in result
        # Should show commit lines (3 checkpoints + initial commit = 4)
        lines = [l for l in result.split("\n") if l.startswith("*")]
        assert len(lines) >= 3

    def test_log_with_limit(self, setup_checkpointer):
        cp = setup_checkpointer
        for i in range(5):
            _put_checkpoint(cp, "t1", step=i)

        result = conversation_log.invoke({"thread_id": "t1", "max_entries": 2})
        lines = [l for l in result.split("\n") if l.startswith("*")]
        assert len(lines) == 2

    def test_log_all_threads(self, setup_checkpointer):
        cp = setup_checkpointer
        _put_checkpoint(cp, "alpha", data="a")
        _put_checkpoint(cp, "beta", data="b")

        result = conversation_log.invoke({"thread_id": "all"})
        assert "alpha" in result
        assert "beta" in result

    def test_log_nonexistent_thread(self, setup_checkpointer):
        result = conversation_log.invoke({"thread_id": "ghost"})
        assert "not found" in result

    def test_log_no_threads(self, setup_checkpointer):
        result = conversation_log.invoke({"thread_id": "all"})
        assert "No conversation threads" in result


# ---------------------------------------------------------------------------
# list_branches
# ---------------------------------------------------------------------------

class TestListBranches:
    def test_lists_all_threads(self, setup_checkpointer):
        cp = setup_checkpointer
        _put_checkpoint(cp, "alpha", data="a")
        _put_checkpoint(cp, "beta", data="b")
        _put_checkpoint(cp, "gamma", data="c")

        result = list_branches.invoke({})
        assert "alpha" in result
        assert "beta" in result
        assert "gamma" in result

    def test_shows_commit_info(self, setup_checkpointer):
        cp = setup_checkpointer
        _put_checkpoint(cp, "t1", data="hello")

        result = list_branches.invoke({})
        # Should have SHA and message
        assert "t1" in result
        assert "(" in result  # SHA in parens

    def test_no_threads(self, setup_checkpointer):
        result = list_branches.invoke({})
        assert "No conversation threads" in result


# ---------------------------------------------------------------------------
# End-to-end: create → checkpoint → fork → log sequence
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_create_checkpoint_fork_log(self, setup_checkpointer):
        cp = setup_checkpointer

        # Step 1: Create some checkpoints
        sha1 = _put_checkpoint(cp, "main", messages=["hello"])
        sha2 = _put_checkpoint(cp, "main", messages=["hello", "world"])

        # Step 2: Create a named checkpoint
        result = create_checkpoint.invoke({"label": "before-fork", "thread_id": "main"})
        assert "before-fork" in result

        # Step 3: Fork from sha1
        result = fork_conversation.invoke({
            "source_thread_id": "main",
            "checkpoint_id": sha1,
            "new_thread_name": "exploration",
        })
        assert "exploration" in result

        # Step 4: Add content to the fork
        _put_checkpoint(cp, "exploration", messages=["hello", "alternate"])

        # Step 5: Check log
        log_result = conversation_log.invoke({"thread_id": "main"})
        assert "thread-main" in log_result

        # Step 6: List branches — should see both
        branches_result = list_branches.invoke({})
        assert "main" in branches_result
        assert "exploration" in branches_result

        # Step 7: Diff between the two original checkpoints
        diff_result = conversation_diff.invoke({
            "thread_id": "main",
            "checkpoint_a": sha1,
            "checkpoint_b": sha2,
        })
        assert "messages" in diff_result

        # Step 8: Time travel back to sha1
        tt_result = time_travel.invoke({"thread_id": "main", "checkpoint_id": sha1})
        assert sha1[:7] in tt_result
