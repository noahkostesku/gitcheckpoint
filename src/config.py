from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str
    smallest_api_key: str
    atoms_agent_id: str = Field(default="", alias="smallest_agent_a_id")
    github_token: str = ""
    github_owner: str = ""
    github_conversations_repo: str = "gitcheckpoint-conversations"
    voice_id: str = "ashley"
    voice_model: str = "lightning-large"
    voice_sample_rate: int = 24000
    host: str = "0.0.0.0"
    port: int = 8000
    checkpoint_dir: str = ".conversations"
    # State checkpointer: "memory" (default), "postgres", or "redis"
    state_backend: str = "memory"
    # Connection string for postgres/redis (only used when state_backend != "memory")
    state_backend_uri: str = ""

    model_config = {"env_file": ".env", "populate_by_name": True}
