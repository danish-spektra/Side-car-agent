from functools import lru_cache
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_chat_deployment: str = "gpt-5.2"  # reasoning model (gpt-4o is deprecated)
    azure_openai_checker_deployment: str = ""  # empty = reuse chat deployment
    azure_openai_api_version: str = "2025-04-01-preview"  # gpt-5.x params need a recent version
    # max_completion_tokens includes hidden reasoning tokens, so budgets are
    # far above the old max_tokens values
    answer_max_completion_tokens: int = 4000
    storage_backend: str = "local"          # "local" | "blob"
    data_dir: str = "./data"
    azure_storage_connection_string: str = ""
    instructor_key: str = ""                # empty = event creation open (local dev)
    rate_limit_questions: int = 10          # per learner per window
    rate_limit_window_seconds: int = 600
    event_token_budget: int = 2_000_000     # tokens_in + tokens_out per event

@lru_cache
def get_settings() -> Settings:
    return Settings()
