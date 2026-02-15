"""Tests for the supervisor multi-agent graph."""

import os

import pytest
from langchain_anthropic import ChatAnthropic

from src.agents.conversation_agent import create_conversation_agent
from src.agents.git_ops_agent import create_git_ops_agent
from src.agents.github_ops_agent import create_github_ops_agent
from src.checkpointer.git_checkpointer import GitCheckpointer
from src.config import Settings
from src.graph.state import ConversationState
from src.graph.supervisor import build_supervisor_graph, create_supervisor, SUPERVISOR_PROMPT
from src.tools.git_tools import ALL_GIT_TOOLS
from src.tools.github_tools import ALL_GITHUB_TOOLS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def dummy_model():
    """A ChatAnthropic instance with a dummy key (never actually called)."""
    return ChatAnthropic(model="claude-sonnet-4-20250514", api_key="sk-test-dummy")


@pytest.fixture
def tmp_checkpointer(tmp_path):
    repo_path = os.path.join(str(tmp_path), "test_conversations")
    return GitCheckpointer(repo_path=repo_path)


@pytest.fixture
def compiled_graph(dummy_model, tmp_checkpointer):
    """Build and compile the full supervisor graph with a temp checkpointer."""
    convo = create_conversation_agent(dummy_model)
    git_agent = create_git_ops_agent(dummy_model, git_tools=ALL_GIT_TOOLS)
    github_agent = create_github_ops_agent(dummy_model, github_tools=ALL_GITHUB_TOOLS)

    workflow = create_supervisor(
        agents=[convo, git_agent, github_agent],
        model=dummy_model,
        prompt=SUPERVISOR_PROMPT,
    )
    return workflow.compile(checkpointer=tmp_checkpointer)


# ---------------------------------------------------------------------------
# State schema tests
# ---------------------------------------------------------------------------

class TestConversationState:
    def test_state_has_required_keys(self):
        keys = set(ConversationState.__annotations__.keys())
        assert "messages" in keys
        assert "current_thread_id" in keys
        assert "current_checkpoint_id" in keys
        assert "active_branches" in keys
        assert "last_git_operation" in keys
        assert "voice_enabled" in keys


# ---------------------------------------------------------------------------
# Graph compilation tests
# ---------------------------------------------------------------------------

class TestGraphCompilation:
    def test_graph_compiles(self, compiled_graph):
        assert compiled_graph is not None

    def test_graph_has_supervisor_node(self, compiled_graph):
        nodes = list(compiled_graph.get_graph().nodes)
        assert "supervisor" in nodes

    def test_graph_has_conversation_agent(self, compiled_graph):
        nodes = list(compiled_graph.get_graph().nodes)
        assert "conversation_agent" in nodes

    def test_graph_has_git_ops_agent(self, compiled_graph):
        nodes = list(compiled_graph.get_graph().nodes)
        assert "git_ops_agent" in nodes

    def test_graph_has_github_ops_agent(self, compiled_graph):
        nodes = list(compiled_graph.get_graph().nodes)
        assert "github_ops_agent" in nodes

    def test_graph_has_all_expected_nodes(self, compiled_graph):
        nodes = set(compiled_graph.get_graph().nodes)
        expected = {"__start__", "__end__", "supervisor", "conversation_agent", "git_ops_agent", "github_ops_agent", "maybe_summarize"}
        assert expected == nodes

    def test_supervisor_routes_to_all_agents(self, compiled_graph):
        """Verify the supervisor has conditional edges to every agent."""
        edges = compiled_graph.get_graph().edges
        supervisor_targets = {e.target for e in edges if e.source == "supervisor"}
        assert "conversation_agent" in supervisor_targets
        assert "git_ops_agent" in supervisor_targets
        assert "github_ops_agent" in supervisor_targets
        assert "maybe_summarize" in supervisor_targets

    def test_agents_return_to_supervisor(self, compiled_graph):
        """All agents should route back to supervisor after completion."""
        edges = compiled_graph.get_graph().edges
        for agent in ("conversation_agent", "git_ops_agent", "github_ops_agent"):
            targets = {e.target for e in edges if e.source == agent}
            assert "supervisor" in targets, f"{agent} should route back to supervisor"

    def test_start_goes_to_supervisor(self, compiled_graph):
        edges = compiled_graph.get_graph().edges
        start_targets = {e.target for e in edges if e.source == "__start__"}
        assert "supervisor" in start_targets


# ---------------------------------------------------------------------------
# Agent creation tests
# ---------------------------------------------------------------------------

class TestAgentCreation:
    def test_conversation_agent_has_no_tools(self, dummy_model):
        agent = create_conversation_agent(dummy_model)
        assert agent is not None

    def test_git_ops_agent_has_tools(self, dummy_model):
        agent = create_git_ops_agent(dummy_model, ALL_GIT_TOOLS)
        assert agent is not None

    def test_github_ops_agent_has_tools(self, dummy_model):
        agent = create_github_ops_agent(dummy_model, ALL_GITHUB_TOOLS)
        assert agent is not None


# ---------------------------------------------------------------------------
# Tool tests
# ---------------------------------------------------------------------------

class TestToolStubs:
    def test_git_tools_are_invocable(self):
        for tool in ALL_GIT_TOOLS:
            assert hasattr(tool, "invoke")
            assert hasattr(tool, "name")

    def test_github_tools_are_invocable(self):
        for tool in ALL_GITHUB_TOOLS:
            assert hasattr(tool, "invoke")
            assert hasattr(tool, "name")

    def test_git_tool_names(self):
        names = {t.name for t in ALL_GIT_TOOLS}
        expected = {
            "create_checkpoint", "time_travel", "fork_conversation",
            "merge_conversations", "conversation_diff", "conversation_log",
            "list_branches",
        }
        assert names == expected

    def test_github_tool_names(self):
        names = {t.name for t in ALL_GITHUB_TOOLS}
        expected = {
            "push_to_github", "create_issue_from_checkpoint",
            "create_conversation_pr", "share_as_gist",
        }
        assert names == expected

    def test_github_tool_names_match(self):
        names = {t.name for t in ALL_GITHUB_TOOLS}
        assert "push_to_github" in names
        assert "share_as_gist" in names


# ---------------------------------------------------------------------------
# build_supervisor_graph integration test
# ---------------------------------------------------------------------------

class TestBuildSupervisorGraph:
    def test_build_with_settings(self, tmp_path):
        """Test that build_supervisor_graph works with a real Settings object."""
        settings = Settings(
            anthropic_api_key="sk-test-dummy",
            smallest_api_key="sk-test-dummy",
            github_token="",
            github_owner="testowner",
            github_conversations_repo="gitcheckpoint-conversations",
            checkpoint_dir=os.path.join(str(tmp_path), "conversations"),
        )

        cp = GitCheckpointer(settings.checkpoint_dir)
        app = build_supervisor_graph(settings, checkpointer=cp)
        nodes = set(app.get_graph().nodes)
        assert "supervisor" in nodes
        assert "conversation_agent" in nodes


# ---------------------------------------------------------------------------
# Routing tests
# ---------------------------------------------------------------------------

class TestRouting:
    """Verify the graph structure supports the expected routing patterns."""

    def test_supervisor_can_route_to_conversation(self, compiled_graph):
        edges = compiled_graph.get_graph().edges
        supervisor_targets = {e.target for e in edges if e.source == "supervisor" and e.conditional}
        assert "conversation_agent" in supervisor_targets

    def test_supervisor_can_route_to_git_ops(self, compiled_graph):
        edges = compiled_graph.get_graph().edges
        supervisor_targets = {e.target for e in edges if e.source == "supervisor" and e.conditional}
        assert "git_ops_agent" in supervisor_targets

    def test_supervisor_can_route_to_github_ops(self, compiled_graph):
        edges = compiled_graph.get_graph().edges
        supervisor_targets = {e.target for e in edges if e.source == "supervisor" and e.conditional}
        assert "github_ops_agent" in supervisor_targets

    def test_supervisor_can_end(self, compiled_graph):
        """Supervisor routes to maybe_summarize (which leads to END) on FINISH."""
        edges = compiled_graph.get_graph().edges
        supervisor_targets = {e.target for e in edges if e.source == "supervisor" and e.conditional}
        assert "maybe_summarize" in supervisor_targets
        # maybe_summarize leads to END
        summarize_targets = {e.target for e in edges if e.source == "maybe_summarize"}
        assert "__end__" in summarize_targets
