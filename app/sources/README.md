# Sources

Individual source adapters — each fetches content from one type of input and returns `langchain_core.documents.Document` objects.  
These are the low-level building blocks. For multi-source grouping and lifecycle management see [COLLECTIONS.md](COLLECTIONS.md).

## Adapters

| Module | Source type | Key function |
|---|---|---|
| `arxiv.py` | arXiv papers (URL, ID, or `arxiv:…` prefix) | `fetch(url)`, `fetch_with_references(url, top_n, depth)` |
| `pubmed.py` | PubMed articles (URL or PMID) | `fetch(url)`, `fetch_with_references(url, top_n, depth)` |
| `pdf.py` | Local PDF files | `load(file_path)` |
| `latex.py` | Local `.tex` files | `load(file_path)` |
| `markdown.py` | Local `.md` files | `load(file_path)` |
| `youtube.py` | YouTube videos and playlists | `load(url, language)` |
| `github.py` | GitHub repos, folders, or single files | `load(url)` |
| `webpage.py` | Single web page | `load(url)` |
| `website.py` | Recursive site crawl | `crawl(url, max_depth)` |
| `video.py` | Local video files | `load(file_path)` |
| `audio.py` | Local audio files (Whisper transcription) | `load(file_path, model_size)` |
| `image.py` | Local image files | `load(file_path, description)` |

## Shared base (`base.py`)

```python
from app.sources.base import (
    PaperMetadata,   # TypedDict for paper fields
    FetchResult,     # TypedDict: {"primary": Document, "references": list[Document]}
    RefNode,         # TypedDict: reference graph node (depth, citation_count, referenced_by)
    make_document,   # make_document(content, metadata) -> Document
    SemanticScholarClient,   # arXiv reference graph via S2 API
    iCiteClient,             # PubMed reference graph via NIH iCite API
    collect_references_arxiv,
    collect_references_pubmed,
    resolve_data_dir,        # creates and returns app/data/{username}/{collection_name}/
)
```

## Paper metadata fields

Returned in `Document.metadata` by `arxiv.py` and `pubmed.py`:

```python
{
    "title":          "Attention Is All You Need",
    "authors":        ["Vaswani", "Shazeer", ...],
    "year":           2017,
    "abstract":       "...",
    "arxiv_id":       "1706.03762",      # arxiv only
    "pmid":           "12345678",        # pubmed only
    "doi":            "10.48550/...",
    "citation_count": 100000,
    "source_url":     "https://arxiv.org/abs/1706.03762",
    "paper_type":     "arxiv",           # "arxiv" | "pubmed" | "pdf" | "latex" | "markdown"
    "content_type":   "full_text",       # "full_text" | "abstract"
}
```

## Reference fetching (papers)

Both `arxiv.py` and `pubmed.py` support recursive reference graph traversal via their `-with_references` functions:

```python
from app.sources.arxiv import fetch_with_references

result = fetch_with_references(
    "https://arxiv.org/abs/1706.03762",
    top_n=10,    # keep top-N references by citation count per depth level
    depth=2,     # how many hops to traverse
)
# result["primary"]    -> the requested paper
# result["references"] -> list of reference Documents, sorted by citation_count desc
```

Requires `SEMANTIC_SCHOLAR_API_KEY` (arXiv) or `NCBI_API_KEY` (PubMed) in `app/config/settings.py` for full citation data. Works without keys at reduced quality.

## Source ID convention

Every Document produced by these adapters carries a `source_id` in its metadata, used by the ingestion layer for per-source vector targeting:

| Source type | source_id format |
|---|---|
| arXiv | `arxiv:1706.03762` |
| PubMed | `pubmed:12345678` |
| PDF / LaTeX / Markdown | `pdf:/abs/path/file.pdf` |
| YouTube | `youtube:https://youtu.be/…` |
| GitHub | `github:https://github.com/owner/repo` |
| Webpage | `webpage:https://example.com/article` |
| Video | `video:/abs/path/lecture.mp4` |
| Audio | `audio:/abs/path/talk.mp3` |
| Image | `image:/abs/path/figure.png` |
