"""
Vector store search tool for scibot.

Retrieves the most relevant chunks from the user's ingested collection using a
two-phase parallel retrieval strategy, followed by optional LLM re-ranking.

Retrieval pipeline
------------------
1. Filter assembly
   ``source_id`` and ``source_type`` shorthand fields are translated into a
   unified filter dict via ``build_filter()``, then merged with any explicit
   ``filter`` parameter.

2. Parallel retrieval  (async; both run concurrently via asyncio.gather)
   Phase A — Semantic search: ``search_with_scores(query, k=k*2, ...)``
             Results below ``score_threshold`` are discarded.
   Phase B — MMR:             ``mmr_search(query, k=k, fetch_k=k*4, ...)``
             Diversity-weighted, reduces near-duplicate chunks from the same doc.

3. Merge + deduplicate
   Results from both phases are combined, deduplicated by (source_id,
   chunk_index), and ranked by best vector score.

4. LLM re-rank  (cost-guarded — only fires when pool size > 10 chunks)
   The configured LLM receives a compact prompt listing each candidate (index +
   first 200 chars) and returns a JSON relevance score array.  Results are
   re-sorted by score.  If the LLM is unavailable or returns malformed output
   the tool silently falls back to vector-score ranking.

Output
------
Per-result block: rank · vector_score · llm_score · source_url · title ·
                  source_type · chunk_index/chunk_count · content preview (400 chars)
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from langchain_core.documents import Document
from langchain_core.tools import tool
from pydantic import BaseModel, Field


# ── Input schema ──────────────────────────────────────────────────────────────

class SearchStorageInput(BaseModel):
    query: str = Field(description="Natural-language search query.")
    username: str = Field(description="scibot username.")
    password: str = Field(description="scibot password.")
    collection_name: str = Field(description="Name of the collection to search.")
    k: int = Field(default=5, description="Number of top results to return.")
    score_threshold: float = Field(
        default=0.3,
        description=(
            "Minimum vector similarity score to keep (0–1). "
            "Chunks below this threshold are discarded before re-ranking."
        ),
    )
    source_id: str | None = Field(
        default=None,
        description=(
            "Filter results to a specific source document by its source_id "
            "(e.g. 'arxiv:1706.03762').  Shorthand for filter={'source_id': ...}."
        ),
    )
    source_type: str | None = Field(
        default=None,
        description=(
            "Filter results to a specific source type "
            "(e.g. 'paper', 'youtube', 'webpage').  "
            "Shorthand for filter={'source_type': ...}."
        ),
    )
    filter: dict | None = Field(
        default=None,
        description=(
            "Advanced metadata filter using unified filter syntax. "
            "Merged with source_id / source_type when both are provided. "
            "Supports: {field: value}, {field: {$gt/$gte/$lt/$lte}}, "
            "{$and: [...]}, {$or: [...]}, {field: {$in: [...]}}."
        ),
    )


# ── Filter assembly ───────────────────────────────────────────────────────────

def _assemble_filter(
    source_id: str | None,
    source_type: str | None,
    explicit: dict | None,
) -> dict | None:
    """
    Combine shorthand and explicit filters.

    Resolution order:
    - source_id  → {"source_id": value}
    - source_type → {"source_type": value}
    - explicit filter dict
    - if multiple, wrap all in {"$and": [...]}
    """
    from app.retriever.data_store import build_filter

    parts: list[dict] = []
    if source_id:
        parts.append(build_filter(source_id=source_id))
    if source_type:
        parts.append(build_filter(source_type=source_type))
    if explicit:
        parts.append(explicit)

    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return {"$and": parts}


# ── Chunk identity key ────────────────────────────────────────────────────────

def _chunk_key(doc: Document) -> tuple:
    meta = doc.metadata
    return (
        meta.get("source_id") or "",
        meta.get("chunk_index", -1),
    )


# ── LLM re-ranking ────────────────────────────────────────────────────────────

_RERANK_PROMPT = """\
You are a relevance ranking assistant.  Given a search query and a list of
text chunks, return a JSON array of relevance scores (1–5, where 5 = highly
relevant, 1 = not relevant) with one score per chunk, in the same order.

Output ONLY a valid JSON array of numbers, e.g.: [5, 3, 4, 2, 1]

Search query: {query}

Chunks:
{chunks}"""


def _llm_rerank(
    query: str,
    candidates: list[Document],
    username: str,
    password: str,
) -> list[float] | None:
    """
    Return a list of relevance scores (1–5) for each candidate, or None on
    any failure.
    """
    try:
        from langchain_core.messages import HumanMessage

        from app.config.llm_model import get_llm
        from app.users.config import resolve_config

        cfg = resolve_config(username, password, None)
        llm = get_llm(cfg.get("llm"))
    except Exception:
        return None

    # Build compact chunk listing (index + first 200 chars)
    chunk_lines = "\n".join(
        f"[{i}] {doc.page_content[:200].replace(chr(10), ' ')}"
        for i, doc in enumerate(candidates)
    )
    prompt = _RERANK_PROMPT.format(query=query, chunks=chunk_lines)

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        text = response.content if hasattr(response, "content") else str(response)

        # Extract JSON array from the response
        match = re.search(r"\[[\d.,\s]+\]", text)
        if not match:
            return None
        scores = json.loads(match.group())
        if len(scores) != len(candidates):
            return None
        return [float(s) for s in scores]
    except Exception:
        return None


# ── Result formatter ──────────────────────────────────────────────────────────

def _format_result(
    rank: int,
    doc: Document,
    vector_score: float | None,
    llm_score: float | None,
) -> str:
    meta = doc.metadata
    lines: list[str] = [f"[{rank}]"]
    if vector_score is not None:
        lines.append(f"    Vector score : {vector_score:.4f}")
    if llm_score is not None:
        lines.append(f"    LLM score    : {llm_score:.1f}/5")
    lines += [
        f"    Title        : {meta.get('title') or '(no title)'}",
        f"    Source URL   : {meta.get('source_url') or ''}",
        f"    Source type  : {meta.get('source_type') or ''}",
        f"    Chunk        : {meta.get('chunk_index', '?')}/{meta.get('chunk_count', '?')}",
        f"    ─────────────────────────────────────────────────────────────",
        f"    {doc.page_content[:400].strip()}",
    ]
    return "\n".join(lines)


# ── Async retrieval helpers ───────────────────────────────────────────────────

def _semantic_search_sync(
    retriever: Any,
    query: str,
    k: int,
    filter: dict | None,
    score_threshold: float,
) -> list[tuple[Document, float]]:
    """Run search_with_scores synchronously; filter by score_threshold."""
    pairs: list[tuple[Document, float]] = retriever.search_with_scores(
        query, k=k, filter=filter
    )
    return [(doc, score) for doc, score in pairs if score >= score_threshold]


def _mmr_search_sync(
    retriever: Any,
    query: str,
    k: int,
    fetch_k: int,
    filter: dict | None,
) -> list[Document]:
    """Run mmr_search synchronously."""
    return retriever.mmr_search(
        query, k=k, fetch_k=fetch_k, lambda_mult=0.6, filter=filter
    )


# ── Tool ─────────────────────────────────────────────────────────────────────

@tool("search_storage", args_schema=SearchStorageInput)
async def search_storage(
    query: str,
    username: str,
    password: str,
    collection_name: str,
    k: int = 5,
    score_threshold: float = 0.3,
    source_id: str | None = None,
    source_type: str | None = None,
    filter: dict | None = None,
) -> str:
    """
    Search a scibot collection using parallel semantic and MMR retrieval,
    then re-rank the merged results using the configured LLM.

    Two retrieval strategies run concurrently:
    - Semantic search (similarity score threshold) — high-precision matches
    - MMR (Maximum Marginal Relevance) — diverse, non-redundant matches

    Results are merged, deduplicated, and optionally re-ranked by the LLM
    (only when >10 candidates; otherwise sorted by vector score).

    Use ``source_id`` or ``source_type`` for quick metadata filtering without
    having to construct a full filter dict.  For richer filters (range, $in,
    $or) use the ``filter`` parameter directly.
    """
    from app.retriever.data_store import get_retriever

    # ── Build effective filter ────────────────────────────────────────────────
    effective_filter = _assemble_filter(source_id, source_type, filter)

    # ── Lazy-initialise retriever (no network call yet) ───────────────────────
    try:
        retriever = get_retriever(username, collection_name, password=password)
    except Exception as exc:
        return f"Failed to connect to vector store: {exc}"

    # ── Parallel retrieval ────────────────────────────────────────────────────
    try:
        sem_results, mmr_results = await asyncio.gather(
            asyncio.to_thread(
                _semantic_search_sync,
                retriever, query, k * 2, effective_filter, score_threshold,
            ),
            asyncio.to_thread(
                _mmr_search_sync,
                retriever, query, k, k * 4, effective_filter,
            ),
        )
    except Exception as exc:
        return f"Retrieval failed: {exc}"

    # ── Merge + deduplicate ───────────────────────────────────────────────────
    # Build score map from semantic results; MMR docs get None score unless
    # they also appeared in semantic results.
    score_map: dict[tuple, float] = {}
    doc_map:   dict[tuple, Document] = {}

    for doc, score in sem_results:
        key = _chunk_key(doc)
        if key not in score_map or score > score_map[key]:
            score_map[key] = score
            doc_map[key] = doc

    for doc in mmr_results:
        key = _chunk_key(doc)
        if key not in doc_map:
            doc_map[key] = doc
            # MMR results without a semantic score get a neutral sentinel value
            score_map[key] = score_map.get(key, 0.0)

    # Sort by score descending
    ranked_keys = sorted(doc_map.keys(), key=lambda ky: score_map.get(ky, 0.0), reverse=True)
    candidates  = [doc_map[ky] for ky in ranked_keys]

    if not candidates:
        return (
            "No results found matching your query"
            + (" with the applied filters." if effective_filter else ".")
        )

    # ── LLM re-rank (cost guard: only when pool > 10) ─────────────────────────
    llm_scores: list[float] | None = None
    if len(candidates) > 10:
        llm_scores = _llm_rerank(query, candidates, username, password)
        if llm_scores:
            paired = sorted(
                zip(candidates, llm_scores),
                key=lambda t: t[1],
                reverse=True,
            )
            candidates = [c for c, _ in paired]
            llm_scores = [s for _, s in paired]

    # Truncate to top-k
    candidates  = candidates[:k]
    llm_scores  = llm_scores[:k] if llm_scores else None

    # ── Format output ─────────────────────────────────────────────────────────
    header = (
        f"Search results for: {query!r}\n"
        f"Collection: {collection_name}  |  "
        f"Returned: {len(candidates)}  |  "
        f"Re-ranked by LLM: {'yes' if llm_scores else 'no'}\n"
        + ("─" * 70)
    )

    blocks: list[str] = [header]
    for i, doc in enumerate(candidates):
        key        = _chunk_key(doc)
        vscore     = score_map.get(key)
        lscore     = llm_scores[i] if llm_scores else None
        blocks.append(_format_result(i + 1, doc, vscore, lscore))

    return "\n\n".join(blocks)
