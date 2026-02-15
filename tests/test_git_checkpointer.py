"""Tests for GitCheckpointer — the git-backed LangGraph checkpoint saver."""

import json
import os
import tempfile

import pytest

from src.checkpointer.git_checkpointer import GitCheckpointer
from langgraph.checkpoint.base import empty_checkpoint


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(thread_id: str, checkpoint_id: str | None = None) -> dict:
    cfg: dict = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
        }
    }
    if checkpoint_id:
        cfg["configurable"]["checkpoint_id"] = checkpoint_id
    return cfg


def _make_checkpoint(**channel_values) -> dict:
    """Return a fresh Checkpoint with optional channel value overrides."""
    cp = empty_checkpoint()
    if channel_values:
        cp["channel_values"] = channel_values
    return cp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_repo(tmp_path):
    """Return a GitCheckpointer rooted in a temp directory."""
    repo_path = os.path.join(str(tmp_path), "test_conversations")
    return GitCheckpointer(repo_path=repo_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInit:
    def test_creates_repo_directory(self, tmp_path):
        repo_path = os.path.join(str(tmp_path), "new_repo")
        cp = GitCheckpointer(repo_path=repo_path)
        assert os.path.isdir(repo_path)
        assert os.path.isdir(os.path.join(repo_path, ".git"))

    def test_initial_commit_exists(self, tmp_repo):
        commits = list(tmp_repo.repo.iter_commits())
        assert len(commits) == 1
        assert commits[0].message.strip() == "Initial commit"

    def test_reopen_existing_repo(self, tmp_path):
        repo_path = os.path.join(str(tmp_path), "reopen_repo")
        cp1 = GitCheckpointer(repo_path=repo_path)
        cp2 = GitCheckpointer(repo_path=repo_path)
        # Should not crash, same repo
        commits = list(cp2.repo.iter_commits())
        assert len(commits) == 1


class TestPutAndGet:
    def test_put_creates_commit(self, tmp_repo):
        config = _make_config("thread-1")
        checkpoint = _make_checkpoint(messages=["hello"])
        metadata = {"source": "input", "step": -1}

        result_config = tmp_repo.put(config, checkpoint, metadata, {})

        # The result should contain a commit SHA as checkpoint_id
        sha = result_config["configurable"]["checkpoint_id"]
        assert len(sha) == 40  # full git SHA

    def test_put_get_roundtrip(self, tmp_repo):
        config = _make_config("thread-1")
        checkpoint = _make_checkpoint(messages=["hello", "world"])
        metadata = {"source": "loop", "step": 0}

        result_config = tmp_repo.put(config, checkpoint, metadata, {})

        # Get it back
        tup = tmp_repo.get_tuple(result_config)
        assert tup is not None
        assert tup.checkpoint["channel_values"] == {"messages": ["hello", "world"]}
        assert tup.metadata["source"] == "loop"
        assert tup.metadata["step"] == 0

    def test_get_latest_without_checkpoint_id(self, tmp_repo):
        config = _make_config("thread-1")

        # Put two checkpoints
        cp1 = _make_checkpoint(count=1)
        tmp_repo.put(config, cp1, {"source": "input", "step": -1}, {})

        cp2 = _make_checkpoint(count=2)
        tmp_repo.put(config, cp2, {"source": "loop", "step": 0}, {})

        # Get without specifying checkpoint_id → should get latest
        tup = tmp_repo.get_tuple(_make_config("thread-1"))
        assert tup is not None
        assert tup.checkpoint["channel_values"] == {"count": 2}

    def test_get_by_specific_sha(self, tmp_repo):
        config = _make_config("thread-1")

        cp1 = _make_checkpoint(count=1)
        r1 = tmp_repo.put(config, cp1, {"source": "input", "step": -1}, {})
        sha1 = r1["configurable"]["checkpoint_id"]

        cp2 = _make_checkpoint(count=2)
        tmp_repo.put(config, cp2, {"source": "loop", "step": 0}, {})

        # Retrieve the first checkpoint specifically
        tup = tmp_repo.get_tuple(_make_config("thread-1", checkpoint_id=sha1))
        assert tup is not None
        assert tup.checkpoint["channel_values"] == {"count": 1}

    def test_get_nonexistent_thread_returns_none(self, tmp_repo):
        config = _make_config("nonexistent")
        assert tmp_repo.get_tuple(config) is None

    def test_get_convenience_method(self, tmp_repo):
        config = _make_config("thread-1")
        checkpoint = _make_checkpoint(x=42)
        tmp_repo.put(config, checkpoint, {"source": "input", "step": -1}, {})

        result = tmp_repo.get(_make_config("thread-1"))
        assert result is not None
        assert result["channel_values"] == {"x": 42}


class TestList:
    def test_list_checkpoints(self, tmp_repo):
        config = _make_config("thread-1")

        for i in range(3):
            cp = _make_checkpoint(step=i)
            tmp_repo.put(config, cp, {"source": "loop", "step": i}, {})

        results = list(tmp_repo.list(_make_config("thread-1")))
        # Should be in reverse chronological order (newest first)
        assert len(results) == 3
        assert results[0].checkpoint["channel_values"]["step"] == 2
        assert results[2].checkpoint["channel_values"]["step"] == 0

    def test_list_with_limit(self, tmp_repo):
        config = _make_config("thread-1")

        for i in range(5):
            cp = _make_checkpoint(step=i)
            tmp_repo.put(config, cp, {"source": "loop", "step": i}, {})

        results = list(tmp_repo.list(_make_config("thread-1"), limit=2))
        assert len(results) == 2

    def test_list_with_before(self, tmp_repo):
        config = _make_config("thread-1")
        shas = []

        for i in range(3):
            cp = _make_checkpoint(step=i)
            r = tmp_repo.put(config, cp, {"source": "loop", "step": i}, {})
            shas.append(r["configurable"]["checkpoint_id"])

        # List everything before the last checkpoint
        before_config = _make_config("thread-1", checkpoint_id=shas[2])
        results = list(tmp_repo.list(_make_config("thread-1"), before=before_config))
        assert len(results) == 2
        assert results[0].checkpoint["channel_values"]["step"] == 1
        assert results[1].checkpoint["channel_values"]["step"] == 0

    def test_list_empty_thread(self, tmp_repo):
        results = list(tmp_repo.list(_make_config("nonexistent")))
        assert results == []

    def test_list_with_filter(self, tmp_repo):
        config = _make_config("thread-1")

        tmp_repo.put(config, _make_checkpoint(a=1), {"source": "input", "step": -1}, {})
        tmp_repo.put(config, _make_checkpoint(a=2), {"source": "loop", "step": 0}, {})
        tmp_repo.put(config, _make_checkpoint(a=3), {"source": "loop", "step": 1}, {})

        results = list(tmp_repo.list(
            _make_config("thread-1"),
            filter={"source": "loop"},
        ))
        assert len(results) == 2


class TestBranching:
    def test_two_threads_create_two_branches(self, tmp_repo):
        config_a = _make_config("alpha")
        config_b = _make_config("beta")

        tmp_repo.put(config_a, _make_checkpoint(who="alpha"), {"source": "input", "step": -1}, {})
        tmp_repo.put(config_b, _make_checkpoint(who="beta"), {"source": "input", "step": -1}, {})

        branch_names = [b.name for b in tmp_repo.repo.branches]
        assert "thread-alpha" in branch_names
        assert "thread-beta" in branch_names

    def test_threads_are_isolated(self, tmp_repo):
        config_a = _make_config("alpha")
        config_b = _make_config("beta")

        tmp_repo.put(config_a, _make_checkpoint(data="a"), {"source": "input", "step": -1}, {})
        tmp_repo.put(config_b, _make_checkpoint(data="b"), {"source": "input", "step": -1}, {})

        tup_a = tmp_repo.get_tuple(_make_config("alpha"))
        tup_b = tmp_repo.get_tuple(_make_config("beta"))

        assert tup_a.checkpoint["channel_values"] == {"data": "a"}
        assert tup_b.checkpoint["channel_values"] == {"data": "b"}


class TestPutWrites:
    def test_put_writes_creates_commit(self, tmp_repo):
        config = _make_config("thread-1")

        # First create a checkpoint
        tmp_repo.put(config, _make_checkpoint(), {"source": "input", "step": -1}, {})

        # Now store writes
        cfg = _make_config("thread-1", checkpoint_id="abc123")
        tmp_repo.put_writes(cfg, [("messages", "hello")], task_id="task-1")

        # Verify the writes file exists in the latest commit
        branch = tmp_repo.repo.branches["thread-thread-1"]
        head = branch.commit
        writes_raw = tmp_repo._read_file_at_commit(head, "pending_writes.json")
        writes = json.loads(writes_raw)
        assert len(writes) == 1
        assert writes[0]["channel"] == "messages"
        assert writes[0]["value"] == "hello"
        assert writes[0]["task_id"] == "task-1"


class TestDeleteThread:
    def test_delete_removes_branch(self, tmp_repo):
        config = _make_config("doomed")
        tmp_repo.put(config, _make_checkpoint(), {"source": "input", "step": -1}, {})
        assert "thread-doomed" in [b.name for b in tmp_repo.repo.branches]

        tmp_repo.delete_thread("doomed")
        assert "thread-doomed" not in [b.name for b in tmp_repo.repo.branches]

    def test_delete_nonexistent_thread_is_noop(self, tmp_repo):
        tmp_repo.delete_thread("ghost")  # should not raise


class TestParentConfig:
    def test_checkpoint_has_parent(self, tmp_repo):
        config = _make_config("thread-1")

        r1 = tmp_repo.put(config, _make_checkpoint(v=1), {"source": "input", "step": -1}, {})
        r2 = tmp_repo.put(config, _make_checkpoint(v=2), {"source": "loop", "step": 0}, {})

        tup = tmp_repo.get_tuple(r2)
        assert tup.parent_config is not None
        assert tup.parent_config["configurable"]["checkpoint_id"] == r1["configurable"]["checkpoint_id"]
