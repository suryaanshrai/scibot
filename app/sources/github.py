"""
GitHub source adapter.

Loads code and documentation from a GitHub repository given any GitHub URL:
  - Repository root  : https://github.com/{owner}/{repo}
  - Branch root      : https://github.com/{owner}/{repo}/tree/{branch}
  - Folder           : https://github.com/{owner}/{repo}/tree/{branch}/{path/to/folder}
  - Single file      : https://github.com/{owner}/{repo}/blob/{branch}/{path/to/file}

Uses LangChain's GithubFileLoader which fetches file contents via the GitHub REST API.
A GitHub personal access token (GITHUB_TOKEN env var) is required.

Usage:
    from app.sources.github import GitHubSource

    docs = GitHubSource().fetch("https://github.com/langchain-ai/langchain")
    docs = GitHubSource().fetch("https://github.com/owner/repo/blob/main/README.md")
"""

from __future__ import annotations

import re
from typing import Callable

from langchain_community.document_loaders.github import GithubFileLoader
from langchain_core.documents import Document

from app.config.settings import GITHUB_TOKEN


# ── URL parsing ───────────────────────────────────────────────────────────────

_GITHUB_URL_RE = re.compile(
    r"https?://github\.com/"
    r"(?P<owner>[^/]+)/"
    r"(?P<repo>[^/]+)"
    r"(?:/(?P<type>tree|blob)/(?P<branch>[^/]+)(?P<path>/.*))?"
    r"/?$"
)


def _parse_github_url(url: str) -> tuple[str, str, str, str | None]:
    """
    Parse a GitHub URL into (owner, repo, branch, subpath).

    subpath is None for a repository/branch root, or a string like
    "/src/utils" (folder) or "/README.md" (single file).
    type_ "blob" signals a single file; "tree" or None signals a directory.
    """
    url = url.rstrip("/")
    m = _GITHUB_URL_RE.match(url)
    if not m:
        raise ValueError(
            f"Cannot parse GitHub URL: {url!r}. "
            "Expected format: https://github.com/{{owner}}/{{repo}}[/tree|blob/{{branch}}[/{{path}}]]"
        )

    owner = m.group("owner")
    repo = m.group("repo")
    url_type = m.group("type")          # "tree" | "blob" | None
    branch = m.group("branch") or "main"
    subpath = m.group("path")           # e.g. "/src/utils" or "/README.md" or None

    # Normalise: subpath without leading slash
    if subpath:
        subpath = subpath.lstrip("/")

    return owner, repo, branch, url_type, subpath  # type: ignore[return-value]


# File extensions treated as binary — skipped by default
_BINARY_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".svg",
    ".pdf", ".zip", ".tar", ".gz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".whl", ".egg",
    ".pyc", ".pyd", ".pyo",
    ".mp3", ".mp4", ".wav", ".ogg", ".flac",
    ".ttf", ".woff", ".woff2", ".eot",
    ".db", ".sqlite", ".pkl", ".pickle", ".npy", ".npz",
    ".bin", ".dat", ".parquet", ".arrow",
})


def _is_text_file(path: str) -> bool:
    """Return True when the file extension is known-text (or unknown — let GitHub API decide)."""
    ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return ext not in _BINARY_EXTENSIONS


def _make_file_filter(
    url_type: str | None,
    subpath: str | None,
) -> Callable[[str], bool]:
    """
    Return a file_filter callable for GithubFileLoader.

    - No subpath (root)      → accept all files
    - url_type == "blob"     → accept exactly that one file
    - url_type == "tree"     → accept all files under that folder prefix
    """
    if not subpath:
        # Repository or branch root — load all text files
        return lambda fp: _is_text_file(fp)

    if url_type == "blob":
        # Single file: exact match (caller's responsibility if it's binary)
        return lambda fp: fp == subpath

    # Folder (tree): prefix match, text files only
    prefix = subpath if subpath.endswith("/") else subpath + "/"
    return lambda fp: _is_text_file(fp) and (fp == subpath or fp.startswith(prefix))


# ── Public API ────────────────────────────────────────────────────────────────

class GitHubSource:
    """Source adapter for GitHub repositories, folders, and single files."""

    def __init__(self, access_token: str | None = None) -> None:
        self._token = access_token or GITHUB_TOKEN
        if not self._token:
            raise ValueError(
                "A GitHub personal access token is required. "
                "Set the GITHUB_TOKEN environment variable or pass access_token= explicitly."
            )

    def fetch(
        self,
        url: str,
        *,
        username: str = "default",
        collection_name: str = "sample",
    ) -> list[Document]:
        """
        Load files from a GitHub URL.

        Parameters
        ----------
        url             : GitHub URL (repository root, folder, or single file)
        username        : user namespace (included for API consistency)
        collection_name : collection namespace (included for API consistency)

        Returns
        -------
        list[Document]  one Document per file loaded; metadata includes
                        'source' (raw GitHub URL), 'file_path', 'branch', 'repo'.
        """
        owner, repo, branch, url_type, subpath = _parse_github_url(url)
        file_filter = _make_file_filter(url_type, subpath)

        loader = GithubFileLoader(
            repo=f"{owner}/{repo}",
            branch=branch,
            access_token=self._token,
            github_api_url="https://api.github.com",
            file_filter=file_filter,
        )
        docs = loader.load()

        for doc in docs:
            doc.metadata.setdefault("source_type", "github")
            doc.metadata.setdefault("repo", f"{owner}/{repo}")
            doc.metadata.setdefault("branch", branch)

        return docs
