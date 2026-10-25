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
    # Mira: Ilari's own agent runtime (a miragen agent container on miragen-net).
    # When set, prospecting asks Mira instead of Anthropic directly.
    MIRA_AGENT_URL: str | None = None       # e.g. http://luuri-prospector:8080
    MIRA_AGENT_TOKEN: str | None = None     # X-Miragen-Token, if the runner guards /run
    MIRA_RUN_TIMEOUT_SECONDS: float = 240.0
    MIRA_POLL_SECONDS: float = 2.5
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

    # Telephony: bridged calls. The provider rings the caller's own phone
    # (their eSIM number) first, then connects the customer. Customer sees
    # TELEPHONY_FROM_NUMBER. Unset provider = tel: links only.
    TELEPHONY_PROVIDER: str | None = None   # '46elks'
    TELEPHONY_FROM_NUMBER: str | None = None
    ELKS_API_USER: str | None = None
    ELKS_API_PASSWORD: str | None = None
    ELKS_API_BASE: str = "https://api.46elks.com/a1"
    TELEPHONY_AGENT_TIMEOUT_SECONDS: int = 25   # how long the caller's phone rings
    TELEPHONY_RECORD_CALLS: bool = False

    @field_validator(
        "BOOTSTRAP_ADMIN_EMAIL", "BOOTSTRAP_ADMIN_PASSWORD", "ANTHROPIC_API_KEY", "BRAVE_SEARCH_API_KEY",
        "MOVINGFIRM_BACKEND_URL", "MOVINGFIRM_INTERNAL_TOKEN", "TWENTY_API_URL",
        "TWENTY_API_KEY", "WEBHOOK_SIGNING_SECRET", "ANALYTICS_UX_EVENTS_URL",
        "MIRA_AGENT_URL", "MIRA_AGENT_TOKEN", "TELEPHONY_PROVIDER", "TELEPHONY_FROM_NUMBER",
        "ELKS_API_USER", "ELKS_API_PASSWORD",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


settings = Settings()
