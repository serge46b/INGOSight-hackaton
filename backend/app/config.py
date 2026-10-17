from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ollama_url: str = "http://ollama:11434"
    model_name: str = "qwen2.5:7b-instruct"
    embed_model: str = "nomic-embed-text"
    imap_mode: str = "mock"
    imap_host: str = ""
    imap_port: int = 993
    imap_ssl: bool = True
    imap_user: str = ""
    imap_password: str = ""
    sync_days: int = 30
    digest_hours: int = 24
    digest_hour: int = 8
    context_chunk_tokens: int = 500
    context_overlap_tokens: int = 50
    rag_top_k: int = 5
    chroma_host: str = "chromadb"
    chroma_port: int = 8000
    database_path: str = "/data/mail.db"
    fixtures_dir: str = "/fixtures/emails"
    secret_key: str = "dev-change-me"
    max_output_chars: int = 8000
    context_char_limit: int = 24000


settings = Settings()
