from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

# ── Auth ──────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    username: str
    message: str


class UpdatePasswordRequest(BaseModel):
    new_password: str


class UpdateUsernameRequest(BaseModel):
    new_username: str


# ── Config ────────────────────────────────────────────────────────────────────

class LLMConfig(BaseModel):
    provider: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    api_key: str | None = None


class EmbeddingConfig(BaseModel):
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None


class StoreConfig(BaseModel):
    model_config = {"extra": "allow"}

    provider: str | None = None
    collection_name: str | None = None


class SearchConfig(BaseModel):
    tool: str | None = None
    whitelist_extra: list[str] | None = None


class UserConfigResponse(BaseModel):
    llm: LLMConfig | None = None
    embedding: EmbeddingConfig | None = None
    store: StoreConfig | None = None
    search: SearchConfig | None = None
    external_keys: dict[str, str] | None = None
    data_source_creds: dict[str, Any] | None = None


class UserConfigUpdate(BaseModel):
    llm: LLMConfig | None = None
    embedding: EmbeddingConfig | None = None
    store: StoreConfig | None = None
    search: SearchConfig | None = None
    external_keys: dict[str, str] | None = None
    data_source_creds: dict[str, Any] | None = None


# ── Collections ───────────────────────────────────────────────────────────────

class PaperSourceIn(BaseModel):
    url_or_path: str
    source_type: str | None = None
    fetch_references: bool | None = None
    reference_depth: int | None = None
    reference_top_n: int | None = None


class YoutubeSourceIn(BaseModel):
    url: str
    language: str | None = None


class GithubSourceIn(BaseModel):
    url: str
    branch: str | None = None


class WebSourceIn(BaseModel):
    url: str
    crawl: bool | None = None
    max_depth: int | None = None


class VideoSourceIn(BaseModel):
    file_path: str


class AudioSourceIn(BaseModel):
    file_path: str
    model_size: str | None = None


class ImageSourceIn(BaseModel):
    file_path: str
    description: str | None = None


class DynamicDataSourceIn(BaseModel):
    source_type: str
    file_path: str | None = None
    credential_key: str | None = None
    database: str | None = None
    table: str | None = None
    mongo_collection: str | None = None
    description: str | None = None


class CollectionSourcesIn(BaseModel):
    papers: list[PaperSourceIn] | None = None
    youtube: list[YoutubeSourceIn] | None = None
    github: list[GithubSourceIn] | None = None
    webpages: list[WebSourceIn] | None = None
    videos: list[VideoSourceIn] | None = None
    audios: list[AudioSourceIn] | None = None
    images: list[ImageSourceIn] | None = None
    dynamic_data_sources: list[DynamicDataSourceIn] | None = None


class CreateCollectionRequest(BaseModel):
    collection_name: str | None = None
    sources: CollectionSourcesIn
    config: dict[str, Any] | None = None


class AddSourcesRequest(BaseModel):
    sources: CollectionSourcesIn
    config: dict[str, Any] | None = None


class IngestRequest(BaseModel):
    source_ids: list[str] | None = None
    config: dict[str, Any] | None = None


class CollectionSummary(BaseModel):
    collection_name: str
    created_at: str
    updated_at: str
    source_counts: dict[str, int]


class CollectionDetail(BaseModel):
    collection_name: str
    username: str
    created_at: str
    updated_at: str
    sources: dict[str, Any]
    vector_collection: str | None = None
    ingestion_task_id: str | None = None
    ingestion_task_status: str | None = None


class IngestStatusResponse(BaseModel):
    task_id: str
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None


# ── Chats ─────────────────────────────────────────────────────────────────────

class CreateChatRequest(BaseModel):
    collection_name: str | None = None
    config_override: dict[str, Any] | None = None
    title: str | None = None


class UpdateChatRequest(BaseModel):
    collection_name: str | None = None
    config_override: dict[str, Any] | None = None
    title: str | None = None


class SendMessageRequest(BaseModel):
    content: str
    config_override: dict[str, Any] | None = None


class ResumeRequest(BaseModel):
    response: Any


class MessageOut(BaseModel):
    message_id: str
    role: str
    content: str
    timestamp: datetime
    task_id: str | None = None
    source_records: list[dict[str, Any]] | None = None
    interrupted: bool = False
    status: str = "completed"


class ChatSummary(BaseModel):
    chat_id: str
    chat_slug: str | None = None
    title: str | None
    collection_name: str | None
    created_at: datetime
    updated_at: datetime
    message_count: int


class ChatDetail(BaseModel):
    chat_id: str
    chat_slug: str | None = None
    title: str | None
    collection_name: str | None
    config_override: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
