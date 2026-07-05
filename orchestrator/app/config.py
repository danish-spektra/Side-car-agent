from functools import lru_cache
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_chat_deployment: str = "gpt-4o"
    azure_openai_checker_deployment: str = ""  # empty = reuse chat deployment
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
