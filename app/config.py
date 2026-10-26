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
    # The mirarun hub (preferred): agent sessions API, mirarun ADR-035.
    MIRARUN_URL: str | None = None             # e.g. http://10.8.0.4:8083
    MIRARUN_SESSION_TOKEN: str | None = None   # Luuri's entry in MIRARUN_SESSION_CLIENT_TOKENS
    MIRA_PROSPECTOR_AGENT: str = "luuri-prospector"
    MIRA_CALL_ANALYST_AGENT: str = "sales-call-analyst"
    MIRA_FUNNEL_ANALYST_AGENT: str = "sales-funnel-analyst"

    # Call intelligence — speech-to-text. Never in-process (docs/adr/0008):
    # an STT service on the Kubernetes cluster, reached over HTTP.
    STT_PROVIDER: str = "none"                # remote | none
    STT_MODEL: str = "large-v3-turbo"         # passed through to the STT service
    STT_LANGUAGE: str = "fi"
    STT_BASE_URL: str | None = None           # the cluster STT service, e.g. http://stt.<ns>.svc:8000/v1
    STT_API_KEY: str | None = None
    STT_TIMEOUT_SECONDS: float = 600.0
    ANALYZE_NOTES: bool = True                 # analyse the caller's notes when there is no transcript
    ANALYZE_MIN_NOTES_CHARS: int = 40
    TRANSCRIPT_RETENTION_DAYS: int = 180       # transcript text is deleted after this; the analysis stays
    RECORDING_MAX_BYTES: int = 100 * 1024 * 1024
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
    TELEPHONY_RECORDING_WEBHOOK: str = "https://luuri.invalid/recording"  # placeholder, see elks.py

    @field_validator(
        "BOOTSTRAP_ADMIN_EMAIL", "BOOTSTRAP_ADMIN_PASSWORD", "ANTHROPIC_API_KEY", "BRAVE_SEARCH_API_KEY",
        "MOVINGFIRM_BACKEND_URL", "MOVINGFIRM_INTERNAL_TOKEN", "TWENTY_API_URL",
        "TWENTY_API_KEY", "WEBHOOK_SIGNING_SECRET", "ANALYTICS_UX_EVENTS_URL",
        "MIRA_AGENT_URL", "MIRA_AGENT_TOKEN", "TELEPHONY_PROVIDER", "TELEPHONY_FROM_NUMBER",
        "ELKS_API_USER", "ELKS_API_PASSWORD", "MIRARUN_URL", "MIRARUN_SESSION_TOKEN",
        "STT_BASE_URL", "STT_API_KEY",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


settings = Settings()
