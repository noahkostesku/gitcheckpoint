"""GitCheckpointer: LangGraph checkpoint saver backed by Git.

Each conversation thread maps to a Git branch.
Each checkpoint maps to a Git commit containing state.json and metadata.json.
The commit SHA serves as the checkpoint ID.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator, Sequence
from typing import Any

import git
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langchain_core.runnables import RunnableConfig


class GitCheckpointer(BaseCheckpointSaver):
    """A checkpoint saver that stores LangGraph state as Git commits.

    - Each thread_id becomes a branch named ``thread-{thread_id}``
    - Each call to ``put()`` serialises state to JSON files and creates a commit
    - The commit SHA is the checkpoint_id
    - ``get_tuple()`` reads state back from a specific commit
    - ``list()`` walks the Git log to yield checkpoint history
    """

    def __init__(self, repo_path: str = ".conversations") -> None:
        super().__init__()
        self.repo_path = os.path.abspath(repo_path)
        self._lock = threading.Lock()
        self._ensure_repo()

    # ------------------------------------------------------------------
    # Repo helpers
    # ------------------------------------------------------------------

    def _ensure_repo(self) -> None:
        """Initialise the git repo if it doesn't already exist."""
        if not os.path.exists(self.repo_path):
            os.makedirs(self.repo_path)
            self.repo = git.Repo.init(self.repo_path)
            readme = os.path.join(self.repo_path, "README.md")
            with open(readme, "w") as f:
                f.write("# GitCheckpoint Conversations\n")
            self.repo.index.add(["README.md"])
            self.repo.index.commit("Initial commit")
        else:
            try:
                self.repo = git.Repo(self.repo_path)
                # Verify the repo is valid by checking HEAD
                _ = self.repo.head.commit
            except (git.InvalidGitRepositoryError, ValueError):
                # Corrupted repo — wipe and reinitialise
                import shutil
                shutil.rmtree(self.repo_path, ignore_errors=True)
                os.makedirs(self.repo_path)
                self.repo = git.Repo.init(self.repo_path)
                readme = os.path.join(self.repo_path, "README.md")
                with open(readme, "w") as f:
                    f.write("# GitCheckpoint Conversations\n")
                self.repo.index.add(["README.md"])
                self.repo.index.commit("Initial commit")
        # Clean up any stale lock files
        lock_dir = os.path.join(self.repo_path, ".git", "refs", "heads")
        if os.path.isdir(lock_dir):
            for f in os.listdir(lock_dir):
                if f.endswith(".lock"):
                    try:
                        os.remove(os.path.join(lock_dir, f))
                    except OSError:
                        pass

    def _branch_name(self, thread_id: str) -> str:
        """Map a thread_id to a git branch name."""
        return f"thread-{thread_id}"

    def _get_or_create_branch(self, thread_id: str) -> git.Head:
        """Return the branch for *thread_id*, creating it if needed."""
        name = self._branch_name(thread_id)
        existing = {b.name: b for b in self.repo.branches}
        if name in existing:
            return existing[name]
        return self.repo.create_head(name)

    def _cleanup_lock(self) -> None:
        """Remove stale index.lock if present."""
        lock_path = os.path.join(self.repo_path, ".git", "index.lock")
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
            except OSError:
                pass

    def _checkout_branch(self, branch: git.Head) -> None:
        """Checkout *branch*, cleaning up stale locks first."""
        self._cleanup_lock()
        branch.checkout()

    def _commit_message_from_metadata(self, metadata: CheckpointMetadata) -> str:
        """Derive a human-readable commit message from checkpoint metadata."""
        source = metadata.get("source", "checkpoint")
        step = metadata.get("step", 0)
        return f"checkpoint: source={source} step={step}"

    def _read_file_at_commit(self, commit: git.Commit, path: str) -> str | None:
        """Read a file from the tree of *commit*, returning None if missing."""
        try:
            blob = commit.tree / path
            return blob.data_stream.read().decode("utf-8")
        except (KeyError, TypeError):
            return None

    # ------------------------------------------------------------------
    # BaseCheckpointSaver interface — sync
    # ------------------------------------------------------------------

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Persist a checkpoint as a git commit.

        Returns a new ``RunnableConfig`` whose ``checkpoint_id`` is the commit SHA.
        """
        with self._lock:
            thread_id = config["configurable"]["thread_id"]
            checkpoint_ns = config["configurable"].get("checkpoint_ns", "")

            branch = self._get_or_create_branch(thread_id)
            self._checkout_branch(branch)

            # Write state.json
            state_path = os.path.join(self.repo_path, "state.json")
            with open(state_path, "w") as f:
                json.dump(checkpoint, f, indent=2, default=str)

            # Write metadata.json
            meta_path = os.path.join(self.repo_path, "metadata.json")
            meta_to_store = dict(metadata)
            meta_to_store["checkpoint_ns"] = checkpoint_ns
            with open(meta_path, "w") as f:
                json.dump(meta_to_store, f, indent=2, default=str)

            # Write pending_writes.json (empty on put — put_writes handles real writes)
            writes_path = os.path.join(self.repo_path, "pending_writes.json")
            with open(writes_path, "w") as f:
                json.dump([], f)

            # Stage and commit
            self.repo.index.add(["state.json", "metadata.json", "pending_writes.json"])
            message = self._commit_message_from_metadata(metadata)
            commit = self.repo.index.commit(message)

            return {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": commit.hexsha,
                }
            }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Store pending writes as a staged file in the repo."""
        with self._lock:
            thread_id = config["configurable"]["thread_id"]
            checkpoint_id = config["configurable"].get("checkpoint_id")

            branch = self._get_or_create_branch(thread_id)
            self._checkout_branch(branch)

            # Load existing pending writes if present
            writes_path = os.path.join(self.repo_path, "pending_writes.json")
            existing: list[dict] = []
            if os.path.exists(writes_path):
                with open(writes_path) as f:
                    try:
                        existing = json.load(f)
                    except json.JSONDecodeError:
                        existing = []

            # Append new writes
            for channel, value in writes:
                existing.append(
                    {
                        "task_id": task_id,
                        "task_path": task_path,
                        "channel": channel,
                        "value": value,
                        "checkpoint_id": checkpoint_id,
                    }
                )

            with open(writes_path, "w") as f:
                json.dump(existing, f, indent=2, default=str)

            self.repo.index.add(["pending_writes.json"])
            self.repo.index.commit(f"writes: task={task_id}")

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """Load a checkpoint from a specific commit (or branch HEAD)."""
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"].get("checkpoint_id")

        branch_name = self._branch_name(thread_id)
        if branch_name not in [b.name for b in self.repo.branches]:
            return None

        branch = self.repo.branches[branch_name]

        if checkpoint_id:
            # Find the specific commit by SHA
            try:
                commit = self.repo.commit(checkpoint_id)
            except (git.BadName, ValueError):
                return None
        else:
            # Use branch HEAD
            commit = branch.commit

        # Read state from that commit's tree
        state_raw = self._read_file_at_commit(commit, "state.json")
        if state_raw is None:
            return None

        checkpoint: Checkpoint = json.loads(state_raw)

        # Read metadata
        meta_raw = self._read_file_at_commit(commit, "metadata.json")
        metadata: CheckpointMetadata = json.loads(meta_raw) if meta_raw else {}

        # Read pending writes
        writes_raw = self._read_file_at_commit(commit, "pending_writes.json")
        pending_writes = None
        if writes_raw:
            raw_writes = json.loads(writes_raw)
            pending_writes = [
                (w["task_id"], w["channel"], w["value"]) for w in raw_writes
            ]

        # Determine parent config
        parent_config = None
        if commit.parents:
            parent_commit = commit.parents[0]
            parent_state = self._read_file_at_commit(parent_commit, "state.json")
            if parent_state is not None:
                parent_config = {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": parent_commit.hexsha,
                    }
                }

        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": commit.hexsha,
                }
            },
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=pending_writes,
        )

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        """Yield checkpoints by walking the git log of a thread's branch."""
        if config is None:
            return

        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        branch_name = self._branch_name(thread_id)

        if branch_name not in [b.name for b in self.repo.branches]:
            return

        branch = self.repo.branches[branch_name]

        before_id = None
        if before:
            before_id = before["configurable"].get("checkpoint_id")

        count = 0
        skip = before_id is not None

        for commit in self.repo.iter_commits(branch):
            if skip:
                if commit.hexsha == before_id:
                    skip = False
                continue

            state_raw = self._read_file_at_commit(commit, "state.json")
            if state_raw is None:
                continue

            checkpoint: Checkpoint = json.loads(state_raw)
            meta_raw = self._read_file_at_commit(commit, "metadata.json")
            metadata: CheckpointMetadata = json.loads(meta_raw) if meta_raw else {}

            # Apply filter
            if filter:
                match = all(metadata.get(k) == v for k, v in filter.items())
                if not match:
                    continue

            # Determine parent
            parent_config = None
            if commit.parents:
                parent_commit = commit.parents[0]
                parent_state = self._read_file_at_commit(parent_commit, "state.json")
                if parent_state is not None:
                    parent_config = {
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "checkpoint_id": parent_commit.hexsha,
                        }
                    }

            yield CheckpointTuple(
                config={
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": commit.hexsha,
                    }
                },
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config=parent_config,
            )

            count += 1
            if limit and count >= limit:
                return

    def delete_thread(self, thread_id: str) -> None:
        """Delete all checkpoints for a thread by removing its branch."""
        branch_name = self._branch_name(thread_id)
        branches = {b.name: b for b in self.repo.branches}
        if branch_name not in branches:
            return

        # Switch away from the branch before deleting it
        main = self.repo.heads[0]  # fallback to first branch
        for b in self.repo.branches:
            if b.name != branch_name:
                main = b
                break
        self._checkout_branch(main)
        self.repo.delete_head(branch_name, force=True)
