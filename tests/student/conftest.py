"""conftest.py for the student test suite.

Provides fixtures for building complete AgentController instances backed
by the scripted (offline) model client — no Groq API key required.
"""
from __future__ import annotations

import pytest

from incidentzero.agent.controller import AgentController
from incidentzero.approval.gateway import AlwaysApproveGateway, AlwaysDenyGateway
from incidentzero.environment.engine import SimulationEnvironment
from incidentzero.model.scripted import ScriptedModelClient
from incidentzero.telemetry.budget import BudgetManager
from incidentzero.telemetry.trace import TraceRecorder
from incidentzero.tools.registry import ToolRegistry


@pytest.fixture
def env():
    return SimulationEnvironment("TEST-001", "public-a")


@pytest.fixture
def registry(env):
    return ToolRegistry(env)


@pytest.fixture
def tmp_trace(tmp_path):
    return TraceRecorder(tmp_path / "test_trace.jsonl")


def make_controller(
    scripted_decisions,
    scripted_structured,
    approval_gateway=None,
    budget=None,
    tmp_path=None,
    env=None,
):
    """Helper to build a fully wired AgentController for unit tests."""
    import tempfile, pathlib
    if tmp_path is None:
        tmp_path = pathlib.Path(tempfile.mkdtemp())
    if env is None:
        env = SimulationEnvironment("TEST-001", "public-a")
    if approval_gateway is None:
        approval_gateway = AlwaysApproveGateway()
    if budget is None:
        budget = BudgetManager(max_llm_calls=14, max_tool_calls=28)

    model = ScriptedModelClient(
        decisions=scripted_decisions,
        structured_outputs=scripted_structured,
    )
    trace = TraceRecorder(tmp_path / "trace.jsonl")
    return AgentController(
        model=model,
        tools=ToolRegistry(env),
        approval=approval_gateway,
        budget=budget,
        trace=trace,
    )
