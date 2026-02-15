"""GitHub integration tools for the github_ops_agent.

All tools operate on a shared PyGithub client and GitCheckpointer that must
be initialised via ``init_github()`` before any tool is invoked.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from langchain_core.tools import tool

from src.checkpointer.git_checkpointer import GitCheckpointer
from src.config import Settings
from src.tools.github_helpers import (
    ensure_remote_repo,
    generate_conversation_diff_markdown,
    generate_conversation_transcript,
)

if TYPE_CHECKING:
    from github import Github

# ---------------------------------------------------------------------------
# Module-level state (set during app init)
# ---------------------------------------------------------------------------

_github: "Github | None" = None
_settings: Settings | None = None
_checkpointer: GitCheckpointer | None = None


def init_github(settings: Settings, checkpointer: GitCheckpointer | None = None) -> None:
    """Wire up the GitHub client and checkpointer for all tools."""
    global _github, _settings, _checkpointer
    _settings = settings
    _checkpointer = checkpointer
    if settings.github_token:
        from github import Auth, Github
        _github = Github(auth=Auth.Token(settings.github_token))


def get_github() -> "Github":
    if _github is None:
        raise RuntimeError("GitHub client not initialised. Call init_github() first.")
    return _github


def get_settings() -> Settings:
    if _settings is None:
        raise RuntimeError("Settings not initialised. Call init_github() first.")
    return _settings


def get_checkpointer() -> GitCheckpointer:
    if _checkpointer is None:
        from src.tools.git_tools import get_checkpointer as _gt_get
        return _gt_get()
    return _checkpointer


# ---------------------------------------------------------------------------
# Tool 1: push_to_github
# ---------------------------------------------------------------------------

@tool
def push_to_github(thread_id: str, commit_message: str = "") -> str:
    """Push a conversation branch to the GitHub remote repository.

    Args:
        thread_id: The conversation thread to push
        commit_message: Optional message for the push
    """
    gh = get_github()
    settings = get_settings()
    cp = get_checkpointer()
    repo = cp.repo

    branch_name = cp._branch_name(thread_id)
    if branch_name not in [b.name for b in repo.branches]:
        return f"Error: thread '{thread_id}' not found."

    # Ensure remote repo exists on GitHub
    gh_repo = ensure_remote_repo(gh, settings.github_owner, settings.github_conversations_repo)
    remote_url = gh_repo.clone_url

    # Add/update origin remote
    try:
        origin = repo.remote("origin")
        if list(origin.urls)[0] != remote_url:
            origin.set_url(remote_url)
    except ValueError:
        origin = repo.create_remote("origin", remote_url)

    # Push the branch
    try:
        origin.push(refspec=f"{branch_name}:{branch_name}", force=True)
    except Exception as e:
        return f"Error pushing: {e}"

    return (
        f"Pushed thread '{thread_id}' → "
        f"https://github.com/{settings.github_owner}/{settings.github_conversations_repo}"
        f"/tree/{branch_name}"
    )


# ---------------------------------------------------------------------------
# Tool 2: create_issue_from_checkpoint
# ---------------------------------------------------------------------------

@tool
def create_issue_from_checkpoint(thread_id: str, checkpoint_id: str, title: str = "") -> str:
    """Create a GitHub Issue from an interesting conversation checkpoint.

    Args:
        thread_id: The conversation thread
        checkpoint_id: The checkpoint commit SHA
        title: Optional issue title (auto-generated from checkpoint if empty)
    """
    gh = get_github()
    settings = get_settings()
    cp = get_checkpointer()

    # Load checkpoint state
    config = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
            "checkpoint_id": checkpoint_id,
        }
    }
    try:
        tup = cp.get_tuple(config)
    except Exception:
        tup = None
    if tup is None:
        return f"Error: checkpoint {checkpoint_id} not found on thread {thread_id}"

    checkpoint = tup.checkpoint
    channel_values = checkpoint.get("channel_values", {})
    metadata = tup.metadata

    # Build title
    if not title:
        messages = channel_values.get("messages", [])
        if messages:
            last = messages[-1]
            if isinstance(last, dict):
                content = last.get("content", str(last))
            else:
                content = str(last)
            title = f"Conversation Moment: {content[:50]}"
        else:
            title = f"Conversation Moment: checkpoint {checkpoint_id[:7]}"

    # Build body
    body_lines = [
        f"## Conversation Checkpoint",
        "",
        f"**Thread:** `{thread_id}`",
        f"**Checkpoint:** `{checkpoint_id}`",
        f"**Source:** {metadata.get('source', 'unknown')}",
        f"**Step:** {metadata.get('step', 'N/A')}",
        "",
        "### State",
        "",
    ]

    messages = channel_values.get("messages", [])
    if messages:
        for m in messages[-5:]:  # Last 5 messages
            if isinstance(m, dict):
                role = m.get("role", m.get("type", "unknown"))
                content = m.get("content", str(m))
            else:
                role = "message"
                content = str(m)
            body_lines.append(f"> **{role}**: {content}")
            body_lines.append("")
    else:
        for k, v in channel_values.items():
            body_lines.append(f"- **{k}**: {v}")
        body_lines.append("")

    body_lines.extend([
        "---",
        f"*Checkout: `git checkout {checkpoint_id}`*",
        "",
        "*Created by GitCheckpoint*",
    ])
    body = "\n".join(body_lines)

    # Create issue
    gh_repo = ensure_remote_repo(gh, settings.github_owner, settings.github_conversations_repo)
    try:
        issue = gh_repo.create_issue(
            title=title,
            body=body,
            labels=["ai-conversation", "checkpoint"],
        )
    except Exception:
        # Labels may not exist — retry without labels
        issue = gh_repo.create_issue(title=title, body=body)

    return f"Created issue #{issue.number}: {issue.html_url}"


# ---------------------------------------------------------------------------
# Tool 3: create_conversation_pr
# ---------------------------------------------------------------------------

@tool
def create_conversation_pr(
    source_thread_id: str,
    target_thread_id: str = "main",
    title: str = "",
    description: str = "",
) -> str:
    """Create a GitHub Pull Request to review conversation changes.

    Args:
        source_thread_id: The branch with conversation changes
        target_thread_id: The base branch (default: main)
        title: PR title
        description: PR description
    """
    gh = get_github()
    settings = get_settings()
    cp = get_checkpointer()

    source_branch = cp._branch_name(source_thread_id)
    target_branch = cp._branch_name(target_thread_id)

    # Verify branches exist locally
    branch_names = [b.name for b in cp.repo.branches]
    if source_branch not in branch_names:
        return f"Error: source thread '{source_thread_id}' not found."
    if target_branch not in branch_names:
        return f"Error: target thread '{target_thread_id}' not found."

    # Ensure remote and push both branches
    gh_repo = ensure_remote_repo(gh, settings.github_owner, settings.github_conversations_repo)
    remote_url = gh_repo.clone_url

    try:
        origin = cp.repo.remote("origin")
        if list(origin.urls)[0] != remote_url:
            origin.set_url(remote_url)
    except ValueError:
        origin = cp.repo.create_remote("origin", remote_url)

    try:
        origin.push(refspec=f"{source_branch}:{source_branch}", force=True)
        origin.push(refspec=f"{target_branch}:{target_branch}", force=True)
    except Exception as e:
        return f"Error pushing branches: {e}"

    # Build PR body
    if not title:
        title = f"Conversation: {source_thread_id} → {target_thread_id}"

    diff_md = generate_conversation_diff_markdown(cp, source_thread_id, target_thread_id)
    body = description + "\n\n" + diff_md if description else diff_md
    body += "\n\n*Created by GitCheckpoint*"

    # Create PR
    try:
        pr = gh_repo.create_pull(
            title=title,
            body=body,
            head=source_branch,
            base=target_branch,
        )
    except Exception as e:
        return f"Error creating PR: {e}"

    return f"Created PR #{pr.number}: {pr.html_url}"


# ---------------------------------------------------------------------------
# Tool 4: share_as_gist
# ---------------------------------------------------------------------------

@tool
def share_as_gist(thread_id: str, checkpoint_range: str = "", public: bool = False) -> str:
    """Share a conversation transcript as a GitHub Gist.

    Args:
        thread_id: The conversation thread to share
        checkpoint_range: Optional "sha1..sha2" range (default: full thread)
        public: Whether the gist should be public
    """
    gh = get_github()
    cp = get_checkpointer()

    # Parse range
    start_sha = None
    end_sha = None
    if checkpoint_range and ".." in checkpoint_range:
        parts = checkpoint_range.split("..", 1)
        start_sha = parts[0].strip() or None
        end_sha = parts[1].strip() or None

    # Generate transcript
    transcript = generate_conversation_transcript(cp, thread_id, start_sha, end_sha)
    if "not found" in transcript:
        return transcript

    filename = f"conversation-{thread_id}.md"
    description = f"AI Conversation Thread: {thread_id}"

    # Create gist
    from github import InputFileContent
    user = gh.get_user()
    gist = user.create_gist(
        public=public,
        files={filename: InputFileContent(transcript)},
        description=description,
    )

    visibility = "public" if public else "secret"
    return f"Shared {visibility} gist: {gist.html_url}"


# ---------------------------------------------------------------------------
# Collected tool list
# ---------------------------------------------------------------------------

ALL_GITHUB_TOOLS = [
    push_to_github,
    create_issue_from_checkpoint,
    create_conversation_pr,
    share_as_gist,
]
