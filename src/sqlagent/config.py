from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Make .env values (API keys, LANGSMITH_*) visible to the SDKs, which read os.environ directly.
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    # --- warehouse -------------------------------------------------------------------------
    warehouse_dsn: str = "postgresql://analyst_ro:analyst_ro@localhost:5432/warehouse"
    statement_timeout_ms: int = 15_000
    max_rows: int = Field(1000, description="Rows fetched from the warehouse per query.")

    # --- LLM -------------------------------------------------------------------------------
    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    llm_model: str = Field("", description="Chat model id; required, see .env.example.")
    llm_temperature: float = 0.0
    llm_max_tokens: int = 2048

    # --- agent behaviour -------------------------------------------------------------------
    max_sql_retries: int = Field(3, description="Self-correction attempts after the first draft.")
    require_approval: bool = True
    approval_cost_threshold: float = Field(
        20_000.0, description="Planner cost (EXPLAIN total cost) above which a human must approve."
    )
    as_of_date: date | None = Field(
        None, description="Treat this date as 'today' in prompts (useful for static demo data)."
    )

    # --- retrieval -------------------------------------------------------------------------
    docs_dir: Path = Path("docs/tables")
    glossary_path: Path = Path("docs/glossary.md")
    retrieval_backend: Literal["tfidf", "embeddings"] = "tfidf"
    retrieval_top_k: int = 3
    embedding_model: str = "text-embedding-3-small"

    # --- API -------------------------------------------------------------------------------
    api_key: str = Field("", description="If set, clients must send it in the X-API-Key header.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
