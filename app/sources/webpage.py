"""
Webpage source adapter.

Loads a single web page and returns its content as a list of Documents.
Uses LangChain's WebBaseLoader (BeautifulSoup-based) for clean extraction.

Usage:
    from app.sources.webpage import WebpageSource

    docs = WebpageSource().fetch("https://example.com/article")
"""

from __future__ import annotations

from langchain_community.document_loaders import WebBaseLoader
from langchain_core.documents import Document


class WebpageSource:
    """Source adapter for a single web page URL."""

    def fetch(
        self,
        url: str,
        *,
        username: str = "default",
        collection_name: str = "sample",
    ) -> list[Document]:
        """
        Fetch and parse a single web page.

        Parameters
        ----------
        url             : fully-qualified URL (http/https)
        username        : user namespace for data storage (unused for web pages,
                          included for API consistency)
        collection_name : collection namespace (unused for web pages,
                          included for API consistency)

        Returns
        -------
        list[Document]  one Document per logical section returned by WebBaseLoader;
                        typically exactly one Document per URL.
        """
        loader = WebBaseLoader(web_paths=[url])
        docs = loader.load()
        # Ensure source metadata is populated
        for doc in docs:
            doc.metadata.setdefault("source_url", url)
            doc.metadata.setdefault("source_type", "webpage")
        return docs
