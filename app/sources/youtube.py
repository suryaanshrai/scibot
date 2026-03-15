"""
YouTube source adapter.

Fetches transcripts for a YouTube video or an entire playlist and returns
them as a list of Documents (one per video).

URL forms accepted:
  Single video  : https://www.youtube.com/watch?v=<id>
                  https://youtu.be/<id>
  Playlist      : https://www.youtube.com/playlist?list=<id>
                  https://www.youtube.com/watch?v=<vid>&list=<pid>  (video + list)

Uses LangChain's YoutubeLoader for transcript fetching and pytubefix for
playlist video enumeration.

Usage:
    from app.sources.youtube import YouTubeSource

    # Single video
    docs = YouTubeSource().fetch("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    # Full playlist
    docs = YouTubeSource().fetch("https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknc9TTnkwB0BH")
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from langchain_community.document_loaders import YoutubeLoader
from langchain_core.documents import Document


# ── URL helpers ───────────────────────────────────────────────────────────────

def _is_playlist_url(url: str) -> bool:
    """
    Return True when the URL points to a playlist rather than a single video.

    A URL is treated as a playlist when:
      - The path is /playlist  (pure playlist page), OR
      - The query string contains 'list=' but no 'v=' param
        (watch URLs with both v= and list= are treated as single-video + playlist
         context; we still load only the playlist in that case when the user
         passes the URL explicitly as a playlist).

    Rule: if 'list=' is present we treat it as a playlist request.
    """
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    return "list" in qs


def _get_playlist_video_urls(playlist_url: str) -> list[str]:
    """Return all video URLs in a YouTube playlist using pytubefix."""
    from pytubefix import Playlist

    playlist = Playlist(playlist_url)
    return list(playlist.video_urls)


def _get_video_metadata(url: str) -> dict:
    """
    Fetch video metadata (title, author, length, etc.) via pytubefix.
    Returns an empty dict on any failure so callers always get a usable result.
    """
    try:
        from pytubefix import YouTube

        yt = YouTube(url)
        return {
            "title": yt.title or "Unknown",
            "author": yt.author or "Unknown",
            "length_seconds": yt.length or 0,
            "publish_date": str(yt.publish_date.date()) if yt.publish_date else "Unknown",
            "thumbnail_url": yt.thumbnail_url or "",
        }
    except Exception:
        return {}


def _load_single_video(
    url: str,
    langs: list[str],
    playlist_url: str | None = None,
) -> list[Document]:
    """Load a transcript for one video URL and return its Documents."""
    try:
        # add_video_info=False avoids the broken `pytube` dependency;
        # we enrich metadata ourselves via pytubefix below.
        loader = YoutubeLoader.from_youtube_url(
            url,
            add_video_info=False,
            language=langs,
        )
        docs = loader.load()
    except Exception:
        # Transcript unavailable for this video — return an empty list so
        # playlist processing can continue with the remaining videos.
        return []

    if not docs:
        return []

    # Enrich every document with video metadata from pytubefix
    video_meta = _get_video_metadata(url)
    for doc in docs:
        doc.metadata.setdefault("source_url", url)
        doc.metadata.setdefault("source_type", "youtube")
        doc.metadata.update(video_meta)
        if playlist_url:
            doc.metadata["playlist_url"] = playlist_url
    return docs


# ── Public API ────────────────────────────────────────────────────────────────

class YouTubeSource:
    """Source adapter for YouTube video and playlist transcripts."""

    def fetch(
        self,
        url: str,
        *,
        language: list[str] | None = None,
        username: str = "default",
        collection_name: str = "sample",
    ) -> list[Document]:
        """
        Fetch transcripts for a YouTube video or playlist.

        Automatically detects whether *url* refers to a single video or a
        playlist (by the presence of a ``list=`` query parameter).

        Parameters
        ----------
        url             : YouTube video URL, video ID, or playlist URL
        language        : preferred transcript language codes, e.g. ["en", "en-US"].
                          Defaults to ["en"] when not specified.
        username        : user namespace (included for API consistency)
        collection_name : collection namespace (included for API consistency)

        Returns
        -------
        list[Document]  one Document per video with a transcript available;
                        metadata includes source_url, source_type, and
                        (for playlist items) playlist_url.
                        Videos without accessible transcripts are silently skipped.
        """
        langs = language or ["en"]

        if _is_playlist_url(url):
            return self._fetch_playlist(url, langs)

        return _load_single_video(url, langs)

    def _fetch_playlist(
        self,
        playlist_url: str,
        langs: list[str],
    ) -> list[Document]:
        """Enumerate all videos in a playlist and load each transcript."""
        video_urls = _get_playlist_video_urls(playlist_url)
        docs: list[Document] = []
        for video_url in video_urls:
            docs.extend(_load_single_video(video_url, langs, playlist_url=playlist_url))
        return docs
