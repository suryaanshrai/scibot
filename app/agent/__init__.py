"""
app.agent — SciBot multi-agent system.

Public API
----------
    from app.agent import OrchestratorAgent, AgentResponse

    agent = OrchestratorAgent("alice", "alice_pw")
    response = agent.run("Explain the attention mechanism")
    print(response.answer)
"""

from app.agent.checker import CheckResult
from app.agent.orchestrator import AgentResponse, OrchestratorAgent
from app.agent.state import AgentState, SourceRecord

__all__ = [
    "OrchestratorAgent",
    "AgentResponse",
    "AgentState",
    "SourceRecord",
    "CheckResult",
]
