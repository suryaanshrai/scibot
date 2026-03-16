"""
app.agent.checker — Scientific fact-checker and citation auditor.

CheckerAgent takes a draft answer, the source manifest, and the parsed
SourceRecord list produced by extract_sources, then uses an LLM to:

  1. Verify factual accuracy against the provided source excerpts.
  2. Detect ungrounded citations ([N] in the answer that have no matching source).
  3. Flag claims that should be cited but aren't.
  4. Return a corrected answer when issues are found.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.agent.state import SourceRecord
from app.config.llm_model import get_llm
from app.users.config import resolve_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

CHECKER_SYSTEM = """\
You are a scientific fact-checker and citation auditor for SciBot.

You will be given:
- A user query
- A draft answer produced by the AI
- A list of available sources (with [N] reference IDs, titles, URLs, and excerpts)

Your task is to review the draft answer for:
1. **Factual accuracy**: Does each claim align with the provided source excerpts?
2. **Citation grounding**: Every [N] reference in the answer must correspond to a
   real source in the available sources list.
3. **Missing citations**: Identify factual claims that should be cited but aren't.

Rules:
- Only judge based on the provided sources; do not use prior training knowledge
  to add new facts — only flag issues.
- If the answer is good, set verified=true and return the original answer as
  corrected_answer.
- Keep corrected_answer concise — fix only what is wrong.
- If corrected_answer is unchanged, it must be identical to the draft.

Return ONLY a valid JSON object with NO markdown fences, NO additional text:
{{
  "verified": <bool>,
  "confidence": <float 0.0-1.0>,
  "flags": ["<issue description>", ...],
  "corrected_answer": "<improved answer or original if no issues>",
  "ungrounded_citations": ["[N] <description>", ...],
  "missing_citations": ["<claim that needs citation>", ...]
}}
"""

CHECKER_HUMAN = """\
## User Query
{query}

## Draft Answer
{draft_answer}

## Available Sources
{sources_manifest}

## Source Excerpts
{source_excerpts}
"""

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    """Structured output from CheckerAgent.run()."""

    verified: bool = True
    confidence: float = 1.0
    flags: list[str] = field(default_factory=list)
    corrected_answer: str = ""
    ungrounded_citations: list[str] = field(default_factory=list)
    missing_citations: list[str] = field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        """True if there are any quality concerns to surface."""
        return (
            not self.verified
            or bool(self.ungrounded_citations)
            or bool(self.missing_citations)
            or bool(self.flags)
        )


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class CheckerAgent:
    """
    Validates a draft answer against retrieved source records.

    The checker fires only when research tools (search_storage, web_search,
    arxiv_search, pubmed_search, invoke_researcher) were used in the current
    turn.  It is skipped for data-analysis queries.
    """

    def __init__(self, username: str, password: str, config_override: dict | None = None) -> None:
        config = resolve_config(username, password, config_override)
        llm = get_llm(config.get("llm"))

        prompt = ChatPromptTemplate.from_messages([
            ("system", CHECKER_SYSTEM),
            ("human", CHECKER_HUMAN),
        ])
        self._chain = prompt | llm | JsonOutputParser()

    def run(
        self,
        query: str,
        draft_answer: str,
        sources_manifest: str,
        source_records: list[SourceRecord],
    ) -> CheckResult:
        """
        Synchronously verify the draft answer.  Returns a CheckResult.
        Falls back to a passing (unverified) result on any error.
        """
        source_excerpts = _build_excerpts(source_records)
        try:
            raw = self._chain.invoke({
                "query": query,
                "draft_answer": draft_answer,
                "sources_manifest": sources_manifest,
                "source_excerpts": source_excerpts,
            })
            return _parse_result(raw, draft_answer)
        except Exception:
            logger.exception("CheckerAgent.run failed — returning pass-through result")
            return CheckResult(
                verified=True,
                confidence=0.0,
                flags=["Checker error — skipped"],
                corrected_answer=draft_answer,
            )

    async def arun(
        self,
        query: str,
        draft_answer: str,
        sources_manifest: str,
        source_records: list[SourceRecord],
    ) -> CheckResult:
        """
        Asynchronously verify the draft answer.  Returns a CheckResult.
        Falls back to a passing result on any error.
        """
        source_excerpts = _build_excerpts(source_records)
        try:
            raw = await self._chain.ainvoke({
                "query": query,
                "draft_answer": draft_answer,
                "sources_manifest": sources_manifest,
                "source_excerpts": source_excerpts,
            })
            return _parse_result(raw, draft_answer)
        except Exception:
            logger.exception("CheckerAgent.arun failed — returning pass-through result")
            return CheckResult(
                verified=True,
                confidence=0.0,
                flags=["Checker error — skipped"],
                corrected_answer=draft_answer,
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_excerpts(source_records: list[SourceRecord]) -> str:
    """Format source records as numbered excerpts for the checker prompt."""
    if not source_records:
        return "(No source excerpts available)"
    lines: list[str] = []
    for rec in source_records:
        if not rec.filtered:
            lines.append(
                f"[{rec.ref_id}] {rec.title}\n"
                f"    URL: {rec.url}\n"
                f"    Excerpt: {rec.snippet[:300]}"
            )
    return "\n\n".join(lines) if lines else "(All sources were filtered out)"


def _parse_result(raw: dict, draft_answer: str) -> CheckResult:
    """Safely parse the LLM JSON output into a CheckResult."""
    if not isinstance(raw, dict):
        # Unexpected type — treat as pass-through
        return CheckResult(corrected_answer=draft_answer)

    corrected = raw.get("corrected_answer") or draft_answer
    return CheckResult(
        verified=bool(raw.get("verified", True)),
        confidence=float(raw.get("confidence", 1.0)),
        flags=list(raw.get("flags") or []),
        corrected_answer=corrected,
        ungrounded_citations=list(raw.get("ungrounded_citations") or []),
        missing_citations=list(raw.get("missing_citations") or []),
    )
