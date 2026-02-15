"""Git operation tools for the git_ops_agent.

All tools operate on a shared GitCheckpointer instance that must be set
via ``set_checkpointer()`` before any tool is invoked.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import git
from langchain_core.tools import tool
from langgraph.checkpoint.base import empty_checkpoint

from src.checkpointer.git_checkpointer import GitCheckpointer

# ---------------------------------------------------------------------------
# Module-level checkpointer instance (set during app init)
# ---------------------------------------------------------------------------

_checkpointer: GitCheckpointer | None = None


def set_checkpointer(cp: GitCheckpointer) -> None:
    global _checkpointer
    _checkpointer = cp


def get_checkpointer() -> GitCheckpointer:
    if _checkpointer is None:
        raise RuntimeError("GitCheckpointer not initialized. Call set_checkpointer() first.")
    return _checkpointer


# ---------------------------------------------------------------------------
# Tool 1: create_checkpoint
# ---------------------------------------------------------------------------

@tool
def create_checkpoint(label: str, thread_id: str) -> str:
    """Save the current conversation state as a named checkpoint (Git commit).

    Args:
        label: A descriptive name for this checkpoint (e.g., 'budget-discussion')
        thread_id: The conversation thread ID
    """
    cp = get_checkpointer()
    repo = cp.repo

    branch = cp._get_or_create_branch(thread_id)
    cp._checkout_branch(branch)

    # Write a label file so the commit has content to track
    label_path = os.path.join(cp.repo_path, "label.txt")
    with open(label_path, "w") as f:
        f.write(label)

    repo.index.add(["label.txt"])
    # Also stage state.json / metadata.json if they exist on disk
    for fname in ("state.json", "metadata.json", "pending_writes.json"):
        fpath = os.path.join(cp.repo_path, fname)
        if os.path.exists(fpath):
            repo.index.add([fname])

    commit = repo.index.commit(label[:80])
    return f"Created checkpoint '{label}' at commit {commit.hexsha[:7]} on thread {thread_id}"


# ---------------------------------------------------------------------------
# Tool 2: time_travel
# ---------------------------------------------------------------------------

@tool
def time_travel(thread_id: str, checkpoint_id: str) -> str:
    """Travel back to a specific checkpoint in the conversation.

    Args:
        thread_id: The conversation thread ID
        checkpoint_id: The commit SHA to travel back to
    """
    cp = get_checkpointer()

    config = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
            "checkpoint_id": checkpoint_id,
        }
    }

    try:
        tup = cp.get_tuple(config)
    except (ValueError, Exception):
        tup = None
    if tup is None:
        return f"Error: checkpoint {checkpoint_id} not found on thread {thread_id}"

    checkpoint = tup.checkpoint
    channel_values = checkpoint.get("channel_values", {})

    # Build a concise summary of what's at this checkpoint
    summary_parts = []
    for key, val in channel_values.items():
        if isinstance(val, list):
            summary_parts.append(f"{key}: {len(val)} items")
        elif isinstance(val, str) and len(val) > 80:
            summary_parts.append(f"{key}: {val[:80]}...")
        else:
            summary_parts.append(f"{key}: {val}")
    summary = ", ".join(summary_parts) if summary_parts else "(empty state)"

    return f"Time traveled to checkpoint {checkpoint_id[:7]}. State: {summary}"


# ---------------------------------------------------------------------------
# Tool 3: fork_conversation
# ---------------------------------------------------------------------------

@tool
def fork_conversation(source_thread_id: str, checkpoint_id: str, new_thread_name: str) -> str:
    """Fork a conversation at a specific checkpoint, creating a new branch.

    Args:
        source_thread_id: The original conversation thread
        checkpoint_id: The commit SHA to fork from
        new_thread_name: Name for the new conversation branch
    """
    cp = get_checkpointer()
    repo = cp.repo

    # Resolve the source commit
    try:
        source_commit = repo.commit(checkpoint_id)
        # Verify the commit is valid by accessing its tree
        _ = source_commit.tree
    except Exception:
        return f"Error: checkpoint {checkpoint_id} not found"

    # Create new branch from that commit
    new_branch_name = cp._branch_name(new_thread_name)
    if new_branch_name in [b.name for b in repo.branches]:
        return f"Error: thread '{new_thread_name}' already exists"

    repo.create_head(new_branch_name, source_commit)
    return (
        f"Forked conversation at {checkpoint_id[:7]} → "
        f"new thread '{new_thread_name}' (branch {new_branch_name})"
    )


# ---------------------------------------------------------------------------
# Tool 4: merge_conversations
# ---------------------------------------------------------------------------

@tool
def merge_conversations(source_thread_id: str, target_thread_id: str, strategy: str = "ours") -> str:
    """Merge one conversation branch into another.

    Args:
        source_thread_id: Branch to merge FROM
        target_thread_id: Branch to merge INTO
        strategy: Merge strategy ('ours' or 'theirs')
    """
    cp = get_checkpointer()
    repo = cp.repo

    source_branch_name = cp._branch_name(source_thread_id)
    target_branch_name = cp._branch_name(target_thread_id)

    branches = {b.name: b for b in repo.branches}
    if source_branch_name not in branches:
        return f"Error: source thread '{source_thread_id}' not found"
    if target_branch_name not in branches:
        return f"Error: target thread '{target_thread_id}' not found"

    source_branch = branches[source_branch_name]
    target_branch = branches[target_branch_name]

    # Checkout target branch
    cp._checkout_branch(target_branch)

    # Perform merge
    try:
        if strategy == "theirs":
            # Accept all changes from source
            repo.git.merge(source_branch_name, strategy_option="theirs", no_edit=True)
        else:
            # Default: 'ours' — keep target state, record merge
            repo.git.merge(source_branch_name, strategy_option="ours", no_edit=True)
    except git.GitCommandError as e:
        # If merge conflicts, abort and report
        try:
            repo.git.merge("--abort")
        except git.GitCommandError:
            pass
        return f"Error merging: {e}. Merge aborted."

    merge_sha = target_branch.commit.hexsha[:7]
    return (
        f"Merged thread '{source_thread_id}' into '{target_thread_id}' "
        f"using strategy '{strategy}'. Merge commit: {merge_sha}"
    )


# ---------------------------------------------------------------------------
# Tool 5: conversation_diff
# ---------------------------------------------------------------------------

@tool
def conversation_diff(thread_id: str, checkpoint_a: str, checkpoint_b: str) -> str:
    """Show the difference between two conversation checkpoints.

    Args:
        thread_id: The conversation thread
        checkpoint_a: First checkpoint SHA
        checkpoint_b: Second checkpoint SHA
    """
    cp = get_checkpointer()

    # Load both checkpoints
    config_a = {"configurable": {"thread_id": thread_id, "checkpoint_ns": "", "checkpoint_id": checkpoint_a}}
    config_b = {"configurable": {"thread_id": thread_id, "checkpoint_ns": "", "checkpoint_id": checkpoint_b}}

    try:
        tup_a = cp.get_tuple(config_a)
    except (ValueError, Exception):
        tup_a = None
    try:
        tup_b = cp.get_tuple(config_b)
    except (ValueError, Exception):
        tup_b = None

    if tup_a is None:
        return f"Error: checkpoint {checkpoint_a} not found"
    if tup_b is None:
        return f"Error: checkpoint {checkpoint_b} not found"

    state_a = tup_a.checkpoint.get("channel_values", {})
    state_b = tup_b.checkpoint.get("channel_values", {})

    # Compute diff
    lines = [f"Diff: {checkpoint_a[:7]} → {checkpoint_b[:7]}", ""]

    all_keys = sorted(set(list(state_a.keys()) + list(state_b.keys())))
    for key in all_keys:
        val_a = state_a.get(key)
        val_b = state_b.get(key)
        if val_a == val_b:
            continue
        if val_a is None:
            lines.append(f"+ {key}: {_summarize_value(val_b)}")
        elif val_b is None:
            lines.append(f"- {key}: {_summarize_value(val_a)}")
        elif isinstance(val_a, list) and isinstance(val_b, list):
            added = len(val_b) - len(val_a)
            if added > 0:
                lines.append(f"  {key}: {len(val_a)} → {len(val_b)} items (+{added})")
                # Show newly added items
                for item in val_b[len(val_a):]:
                    lines.append(f"    + {_summarize_value(item)}")
            elif added < 0:
                lines.append(f"  {key}: {len(val_a)} → {len(val_b)} items ({added})")
            else:
                lines.append(f"  {key}: {len(val_a)} items (modified)")
        else:
            lines.append(f"  {key}: {_summarize_value(val_a)} → {_summarize_value(val_b)}")

    if len(lines) == 2:
        lines.append("(no differences)")

    return "\n".join(lines)


def _summarize_value(val: object) -> str:
    """Produce a short string representation of a value for diffs."""
    if isinstance(val, list):
        return f"[{len(val)} items]"
    s = str(val)
    return s[:80] + "..." if len(s) > 80 else s


# ---------------------------------------------------------------------------
# Tool 6: conversation_log
# ---------------------------------------------------------------------------

@tool
def conversation_log(thread_id: str, max_entries: int = 20) -> str:
    """Show the Git-style log of conversation checkpoints.

    Args:
        thread_id: The conversation thread (or 'all' for all threads)
        max_entries: Maximum log entries to show
    """
    cp = get_checkpointer()
    repo = cp.repo

    lines: list[str] = []

    if thread_id == "all":
        threads = []
        for branch in repo.branches:
            if branch.name.startswith("thread-"):
                tid = branch.name[len("thread-"):]
                threads.append(tid)
        if not threads:
            return "No conversation threads found."
        for tid in threads:
            lines.append(f"=== Thread: {tid} ===")
            lines.append(_format_thread_log(cp, tid, max_entries))
            lines.append("")
        return "\n".join(lines).rstrip()
    else:
        branch_name = cp._branch_name(thread_id)
        if branch_name not in [b.name for b in repo.branches]:
            return f"Thread '{thread_id}' not found."
        return _format_thread_log(cp, thread_id, max_entries)


def _format_thread_log(cp: GitCheckpointer, thread_id: str, max_entries: int) -> str:
    """Format git log for a single thread."""
    repo = cp.repo
    branch_name = cp._branch_name(thread_id)
    branch = repo.branches[branch_name]

    lines: list[str] = []
    is_head = repo.head.is_detached is False and repo.active_branch.name == branch_name

    for i, commit in enumerate(repo.iter_commits(branch)):
        if i >= max_entries:
            lines.append(f"  ... ({max_entries}+ entries, use max_entries to see more)")
            break

        sha = commit.hexsha[:7]
        msg = commit.message.strip().split("\n")[0]
        ts = datetime.fromtimestamp(commit.committed_date, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")

        ref = ""
        if i == 0:
            ref_parts = [branch_name]
            if is_head:
                ref_parts.insert(0, "HEAD ->")
            ref = f" ({', '.join(ref_parts)})"

        lines.append(f"* {sha}{ref} {msg}  [{ts}]")

    return "\n".join(lines) if lines else "(no checkpoints)"


# ---------------------------------------------------------------------------
# Tool 7: list_branches
# ---------------------------------------------------------------------------

@tool
def list_branches() -> str:
    """List all conversation threads (branches) in the repository."""
    cp = get_checkpointer()
    repo = cp.repo

    thread_branches = []
    for branch in repo.branches:
        if branch.name.startswith("thread-"):
            thread_branches.append(branch)

    if not thread_branches:
        return "No conversation threads found."

    lines: list[str] = []
    active = None
    if not repo.head.is_detached:
        active = repo.active_branch.name

    for branch in sorted(thread_branches, key=lambda b: b.name):
        head_commit = branch.commit
        sha = head_commit.hexsha[:7]
        msg = head_commit.message.strip().split("\n")[0][:60]
        ts = datetime.fromtimestamp(head_commit.committed_date, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        prefix = "* " if branch.name == active else "  "
        thread_id = branch.name[len("thread-"):]
        lines.append(f"{prefix}{thread_id} ({sha}) {msg}  [{ts}]")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Collected tool list
# ---------------------------------------------------------------------------

ALL_GIT_TOOLS = [
    create_checkpoint,
    time_travel,
    fork_conversation,
    merge_conversations,
    conversation_diff,
    conversation_log,
    list_branches,
]
