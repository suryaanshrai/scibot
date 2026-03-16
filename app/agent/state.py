"""
app.agent.state — Shared state types for the SciBot LangGraph agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated

from langgraph.graph import MessagesState

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VECTOR_STORE_RELEVANCE_THRESHOLD: float = 0.45
"""
Minimum vector similarity score for a search_storage chunk to be shown to
the LLM and included in the ## Sources section.  Chunks below this threshold
are still kept in state for auditing (filtered=True) but excluded from the
source manifest injected into the model's context.
"""

MSG_SUMMARIZE_THRESHOLD: int = 20
"""
When the messages list exceeds this length, finalize() will condense older
messages into a rolling summary and trim the state to the last few messages.
"""

# ---------------------------------------------------------------------------
# State reducers
# ---------------------------------------------------------------------------


def _list_reset_reducer(current: list, update: list | None) -> list:
    """
    Custom LangGraph state reducer for lists that support a turn-start reset.

    * ``update`` is a list  → append to current (standard accumulation within a turn)
    * ``update`` is ``None`` → reset to ``[]`` (used by recall_memories at turn start)
    """
    if update is None:
        return []
    return current + update


# ---------------------------------------------------------------------------
# Source record
# ---------------------------------------------------------------------------


@dataclass
class SourceRecord:
    """A single retrieved source with provenance and relevance metadata."""

    ref_id: int
    """Sequential citation number within the current conversation turn, e.g. 1 → [1]."""

    title: str
    """Human-readable title of the source."""

    url: str
    """Canonical URL or identifier (arxiv ID, PubMed PMID, file path, etc.)."""

    source_type: str
    """Category: 'paper' | 'webpage' | 'vector_store' | 'data' | 'unknown'."""

    tool_name: str
    """The tool that produced this record, e.g. 'arxiv_search', 'search_storage'."""

    snippet: str
    """First ~300 characters of the retrieved content."""

    relevance_score: float = 1.0
    """
    Similarity / relevance score (0–1).  For search_storage this is the
    cosine similarity; for other tools it defaults to 1.0 (not scored).
    """

    filtered: bool = False
    """
    True when relevance_score < VECTOR_STORE_RELEVANCE_THRESHOLD.
    Filtered records are kept in state for audit but not injected into the
    LLM context or the ## Sources section.
    """


# ---------------------------------------------------------------------------
# Graph context (injected at runtime, not stored in state)
# ---------------------------------------------------------------------------


@dataclass
class Context:
    """
    Runtime context injected into graph nodes that need the username for
    scoping long-term memory store operations.
    """

    username: str = ""


# ---------------------------------------------------------------------------
# Graph state
# ---------------------------------------------------------------------------


class AgentState(MessagesState):
    """
    Full state for the SciBot LangGraph orchestrator.

    Extends MessagesState (which gives us the ``messages`` field with the
    ``add_messages`` reducer) with:

    * ``summary``        – rolling condensed conversation summary (single string,
                           last-writer-wins; empty string when not yet condensed).
    * ``source_records`` – parsed source annotations (list, accumulated within a
                           turn via ``_list_reset_reducer``; reset to ``[]`` at
                           turn start by recall_memories returning ``None``).

    Tools used this turn are computed on-the-fly from message history via
    ``_get_turn_tool_names()`` — no separate state field needed.
    """

    summary: str
    source_records: Annotated[list[SourceRecord], _list_reset_reducer]
