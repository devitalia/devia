import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    name: str
    instructions_path: str
    db_dsn: str | None
    laravel_base_url: str | None
    laravel_tool_token: str | None


def get_settings() -> Settings:
    return Settings(
        name=os.getenv("DEVIA_NAME", "DevIA"),
        instructions_path=os.getenv("DEVIA_INSTRUCTIONS_PATH", "/instructions"),
        db_dsn=os.getenv("DEVIA_DB_DSN"),
        laravel_base_url=os.getenv("DEVIA_LARAVEL_BASE_URL"),
        laravel_tool_token=os.getenv("DEVIA_LARAVEL_TOOL_TOKEN"),
    )
