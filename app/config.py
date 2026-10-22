from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from the environment (UPPER_SNAKE), like the
    movingfirm services. Blank credential values become None so a half-set
    .env does not look configured."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    SESSION_SECRET: str  # signs the session cookie
    SESSION_TTL_HOURS: int = 12
    BOOTSTRAP_ADMIN_EMAIL: str | None = None
    BOOTSTRAP_ADMIN_PASSWORD: str | None = None

    # Prospecting
    PRH_API_BASE: str = "https://avoindata.prh.fi/opendata-ytj-api/v3"
    ANTHROPIC_API_KEY: str | None = None
    ANTHROPIC_MODEL: str = "claude-sonnet-4-5"
    BRAVE_SEARCH_API_KEY: str | None = None  # web search for companies without a website in the register
    ENRICH_FETCH_WEBSITES: bool = True
    ENRICH_TIMEOUT_SECONDS: float = 8.0

    # Integrations (targets are rows in integration_targets; secrets stay in env)
    MOVINGFIRM_BACKEND_URL: str | None = None
    MOVINGFIRM_INTERNAL_TOKEN: str | None = None
    TWENTY_API_URL: str | None = None
    TWENTY_API_KEY: str | None = None
    WEBHOOK_SIGNING_SECRET: str | None = None

    # Analytics continuity: sales events are sent to the existing ux_events tracker.
    ANALYTICS_UX_EVENTS_URL: str | None = None  # e.g. https://api.muutto365.fi/api/ux-events

    WORKER_POLL_SECONDS: float = 2.0

    @field_validator(
        "BOOTSTRAP_ADMIN_EMAIL", "BOOTSTRAP_ADMIN_PASSWORD", "ANTHROPIC_API_KEY", "BRAVE_SEARCH_API_KEY",
        "MOVINGFIRM_BACKEND_URL", "MOVINGFIRM_INTERNAL_TOKEN", "TWENTY_API_URL",
        "TWENTY_API_KEY", "WEBHOOK_SIGNING_SECRET", "ANALYTICS_UX_EVENTS_URL",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


settings = Settings()
