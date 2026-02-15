"""Helper functions for GitHub integration tools."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from github import Github
    from src.checkpointer.git_checkpointer import GitCheckpointer


def ensure_remote_repo(github: "Github", owner: str, repo_name: str):
    """Return the conversations repo on GitHub, creating it if it doesn't exist.

    Returns a ``github.Repository.Repository`` object.
    """
    try:
        return github.get_repo(f"{owner}/{repo_name}")
    except Exception:
        user = github.get_user()
        return user.create_repo(
            repo_name,
            description="GitCheckpoint conversation history",
            private=True,
            auto_init=True,
        )


def generate_conversation_transcript(
    checkpointer: "GitCheckpointer",
    thread_id: str,
    start_sha: str | None = None,
    end_sha: str | None = None,
) -> str:
    """Generate a markdown transcript from conversation checkpoints.

    Walks the git log for *thread_id* and formats each checkpoint's
    ``channel_values`` into a readable markdown document.
    """
    repo = checkpointer.repo
    branch_name = checkpointer._branch_name(thread_id)

    if branch_name not in [b.name for b in repo.branches]:
        return f"Thread '{thread_id}' not found."

    branch = repo.branches[branch_name]

    # Collect commits (newest first)
    commits: list = []
    in_range = start_sha is None
    for commit in repo.iter_commits(branch):
        if not in_range:
            if commit.hexsha == end_sha or commit.hexsha.startswith(end_sha or ""):
                in_range = True
            else:
                continue

        commits.append(commit)

        if start_sha and (commit.hexsha == start_sha or commit.hexsha.startswith(start_sha)):
            break

    # Reverse so oldest is first
    commits.reverse()

    lines = [
        f"# Conversation: {thread_id}",
        "",
        f"*Generated at {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*",
        "",
        "---",
        "",
    ]

    for commit in commits:
        state_raw = checkpointer._read_file_at_commit(commit, "state.json")
        if state_raw is None:
            continue

        state = json.loads(state_raw)
        channel_values = state.get("channel_values", {})
        sha = commit.hexsha[:7]
        ts = datetime.fromtimestamp(commit.committed_date, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
        msg = commit.message.strip().split("\n")[0]

        lines.append(f"### Checkpoint `{sha}` — {msg}")
        lines.append(f"*{ts}*")
        lines.append("")

        messages = channel_values.get("messages", [])
        if isinstance(messages, list) and messages:
            for m in messages:
                if isinstance(m, dict):
                    role = m.get("role", m.get("type", "unknown"))
                    content = m.get("content", str(m))
                else:
                    role = "message"
                    content = str(m)
                lines.append(f"**{role}**: {content}")
                lines.append("")
        else:
            # Show all channel values as a summary
            for key, val in channel_values.items():
                lines.append(f"- **{key}**: {_fmt(val)}")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def generate_conversation_diff_markdown(
    checkpointer: "GitCheckpointer",
    thread_a: str,
    thread_b: str,
) -> str:
    """Generate a markdown diff between two conversation branches.

    Compares the HEAD state of each branch.
    """
    repo = checkpointer.repo
    branch_a = checkpointer._branch_name(thread_a)
    branch_b = checkpointer._branch_name(thread_b)

    branches = {b.name: b for b in repo.branches}
    if branch_a not in branches or branch_b not in branches:
        return "Error: one or both threads not found."

    head_a = branches[branch_a].commit
    head_b = branches[branch_b].commit

    state_a_raw = checkpointer._read_file_at_commit(head_a, "state.json")
    state_b_raw = checkpointer._read_file_at_commit(head_b, "state.json")

    state_a = json.loads(state_a_raw).get("channel_values", {}) if state_a_raw else {}
    state_b = json.loads(state_b_raw).get("channel_values", {}) if state_b_raw else {}

    lines = [
        f"# Conversation Diff",
        "",
        f"**{thread_a}** (`{head_a.hexsha[:7]}`) → **{thread_b}** (`{head_b.hexsha[:7]}`)",
        "",
    ]

    all_keys = sorted(set(list(state_a.keys()) + list(state_b.keys())))
    has_diff = False
    for key in all_keys:
        val_a = state_a.get(key)
        val_b = state_b.get(key)
        if val_a == val_b:
            continue
        has_diff = True
        if val_a is None:
            lines.append(f"- **+ {key}**: {_fmt(val_b)}")
        elif val_b is None:
            lines.append(f"- **- {key}**: {_fmt(val_a)}")
        else:
            lines.append(f"- **{key}**: {_fmt(val_a)} → {_fmt(val_b)}")

    if not has_diff:
        lines.append("*(no differences)*")

    return "\n".join(lines)


def _fmt(val: object) -> str:
    """Short string representation."""
    if isinstance(val, list):
        return f"[{len(val)} items]"
    s = str(val)
    return s[:100] + "..." if len(s) > 100 else s
