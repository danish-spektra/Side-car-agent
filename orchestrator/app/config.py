from functools import lru_cache
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_chat_deployment: str = "gpt-4o"
    storage_backend: str = "local"          # "local" | "blob"
    data_dir: str = "./data"
    azure_storage_connection_string: str = ""

@lru_cache
def get_settings() -> Settings:
    return Settings()
