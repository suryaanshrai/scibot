import os
from dotenv import load_dotenv

load_dotenv()


def get_env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


# ── LLM defaults ──────────────────────────────────────────────────────────────
DEFAULT_LLM_PROVIDER = get_env("DEFAULT_LLM_PROVIDER", "openai")
DEFAULT_LLM_MODEL = get_env("DEFAULT_LLM_MODEL")
DEFAULT_LLM_TEMPERATURE = get_env("DEFAULT_LLM_TEMPERATURE", "0.7")
DEFAULT_LLM_MAX_TOKENS = get_env("DEFAULT_LLM_MAX_TOKENS")

# ── Embedding defaults ─────────────────────────────────────────────────────────
DEFAULT_EMBEDDING_PROVIDER = get_env("DEFAULT_EMBEDDING_PROVIDER", "openai")
DEFAULT_EMBEDDING_MODEL = get_env("DEFAULT_EMBEDDING_MODEL")
DEFAULT_EMBEDDING_DIMENSIONS = get_env("DEFAULT_EMBEDDING_DIMENSIONS")

# ── Store defaults ─────────────────────────────────────────────────────────────
DEFAULT_STORE_PROVIDER = get_env("DEFAULT_STORE_PROVIDER", "chroma")
DEFAULT_STORE_COLLECTION = get_env("DEFAULT_STORE_COLLECTION", "scibot")
DEFAULT_STORE_NAMESPACE = get_env("DEFAULT_STORE_NAMESPACE", "")

# ── Provider API keys ──────────────────────────────────────────────────────────
OPENAI_API_KEY = get_env("OPENAI_API_KEY")
ANTHROPIC_API_KEY = get_env("ANTHROPIC_API_KEY")
GOOGLE_API_KEY = get_env("GOOGLE_API_KEY")
GROQ_API_KEY = get_env("GROQ_API_KEY")
MISTRAL_API_KEY = get_env("MISTRAL_API_KEY")
COHERE_API_KEY = get_env("COHERE_API_KEY")
DEEPSEEK_API_KEY = get_env("DEEPSEEK_API_KEY")
XAI_API_KEY = get_env("XAI_API_KEY")
OPENROUTER_API_KEY = get_env("OPENROUTER_API_KEY")
HUGGINGFACEHUB_API_TOKEN = get_env("HUGGINGFACEHUB_API_TOKEN")
IBM_API_KEY = get_env("IBM_API_KEY")
IBM_PROJECT_ID = get_env("IBM_PROJECT_ID")
IBM_URL = get_env("IBM_URL", "https://us-south.ml.cloud.ibm.com")

# ── Ollama ─────────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL = get_env("OLLAMA_BASE_URL", "http://localhost:11434")

# ── Chroma store ──────────────────────────────────────────────────────────────
CHROMA_URL = get_env("CHROMA_URL")
CHROMA_HOST = get_env("CHROMA_HOST")
CHROMA_PORT = get_env("CHROMA_PORT", "8000")

# ── Pinecone store ────────────────────────────────────────────────────────────
PINECONE_API_KEY = get_env("PINECONE_API_KEY")
PINECONE_INDEX_NAME = get_env("PINECONE_INDEX_NAME")

# ── Qdrant store ──────────────────────────────────────────────────────────────
QDRANT_URL = get_env("QDRANT_URL")
QDRANT_API_KEY = get_env("QDRANT_API_KEY")

# ── Milvus store ──────────────────────────────────────────────────────────────
MILVUS_URI = get_env("MILVUS_URI", "./milvus.db")

# ── MongoDB store ─────────────────────────────────────────────────────────────
MONGODB_CONNECTION_STRING = get_env("MONGODB_CONNECTION_STRING")
MONGODB_DATABASE_NAME = get_env("MONGODB_DATABASE_NAME", "scibot")

# ── Postgres store ────────────────────────────────────────────────────────────
POSTGRES_CONNECTION_STRING = get_env("POSTGRES_CONNECTION_STRING")

# ── External research APIs ────────────────────────────────────────────────────
# Semantic Scholar — optional; unlocks 100 req/s (vs 1 req/s anonymous)
SEMANTIC_SCHOLAR_API_KEY = get_env("SEMANTIC_SCHOLAR_API_KEY")
# NCBI/PubMed — optional; unlocks 10 req/s (vs 3 req/s anonymous)
NCBI_API_KEY = get_env("NCBI_API_KEY")

# ── Web search ───────────────────────────────────────────────────────────────
# Tavily — optional; preferred search backend when key is present
TAVILY_API_KEY = get_env("TAVILY_API_KEY")
# SerpAPI — optional; secondary search backend
SERPAPI_API_KEY = get_env("SERPAPI_API_KEY")

# ── GitHub ────────────────────────────────────────────────────────────────────
# GitHub personal access token — required by GithubFileLoader
GITHUB_TOKEN = get_env("GITHUB_TOKEN")

# ── Background workers (Redis brokers) ───────────────────────────────────────
# Separate Redis instances keep ingestion and agent queues isolated
REDIS_INGESTION_URL = get_env("REDIS_INGESTION_URL", "redis://localhost:6379/0")
REDIS_AGENT_URL = get_env("REDIS_AGENT_URL", "redis://localhost:6380/0")

# ── Chat history (MongoDB via Motor) ─────────────────────────────────────────
MONGODB_CHAT_URL = get_env("MONGODB_CHAT_URL", "mongodb://localhost:27017")
MONGODB_CHAT_DB_NAME = get_env("MONGODB_CHAT_DB_NAME", "scibot_chats")
