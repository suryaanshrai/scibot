"""
Website source adapter.

Crawls an entire website starting from a root URL up to a configurable depth,
returning each discovered page as a Document.
Uses LangChain's RecursiveUrlLoader.

Usage:
    from app.sources.website import WebsiteSource

    docs = WebsiteSource().fetch("https://docs.example.com", max_depth=2)
"""

from __future__ import annotations

from langchain_community.document_loaders.recursive_url_loader import RecursiveUrlLoader
from langchain_core.documents import Document


class WebsiteSource:
    """Source adapter for recursive multi-page website crawling."""

    def fetch(
        self,
        url: str,
        *,
        max_depth: int = 2,
        username: str = "default",
        collection_name: str = "sample",
    ) -> list[Document]:
        """
        Recursively crawl a website and return all discovered pages.

        Parameters
        ----------
        url             : root URL to start crawling from
        max_depth       : how many link-hops from the root to follow (default 2)
        username        : user namespace (included for API consistency)
        collection_name : collection namespace (included for API consistency)

        Returns
        -------
        list[Document]  one Document per crawled page.
        """
        loader = RecursiveUrlLoader(
            url=url,
            max_depth=max_depth,
        )
        docs = loader.load()
        for doc in docs:
            doc.metadata.setdefault("source_type", "website")
            doc.metadata.setdefault("root_url", url)
        return docs
