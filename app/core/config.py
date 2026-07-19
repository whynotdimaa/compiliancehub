from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "ComplianceHub"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    max_upload_mb: int = 50

    # Chunking
    chunk_max_chars: int = 1500
    chunk_overlap_chars: int = 150

    # Security
    secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # PostgreSQL
    database_url: str = "postgresql+asyncpg://compliance:compliance@postgres:5432/compliancehub"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # RabbitMQ (Celery broker)
    rabbitmq_url: str = "amqp://compliance:compliance@rabbitmq:5672//"

    # Redis (cache + Celery result backend)
    redis_url: str = "redis://redis:6379/0"

    # Neo4j
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "compliance123"

    # MinIO
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "compliance"
    minio_secret_key: str = "compliance123"
    minio_bucket: str = "documents"
    minio_secure: bool = False

    # LLM (OpenAI-compatible; Ollama = http://localhost:11434/v1 + any key)
    llm_base_url: str = "https://api.groq.com/openai/v1"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # Graph (Neo4j)
    graph_search_enabled: bool = True
    graph_candidates: int = 20
    graph_expansion_weight: float = 0.4  # 1-hop co-occurrence vs direct entity match

    # Retrieval
    reranker_model: str = "BAAI/bge-reranker-base"
    retrieval_candidates: int = 20  # per retriever, before fusion
    rerank_candidates: int = 10     # fused candidates sent to the cross-encoder
    search_top_k: int = 5
    rrf_k: int = 60

    # RAG agent (CRAG)
    rag_min_relevant: int = 2       # fewer graded-relevant chunks triggers correction
    rag_max_context_chunks: int = 5
    tavily_max_results: int = 3

    # External integrations
    tavily_api_key: str = ""
    slack_webhook_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
