-- expand_only: true
-- Browser (WebRTC) calls through Telnyx: the caller talks in the browser with
-- a headset, so no agent phone is rung. Re-run safe; only new nullable columns.

-- One Telnyx credential per user (created on first call, JWTs minted from it).
ALTER TABLE users ADD COLUMN IF NOT EXISTS telnyx_credential_id TEXT;

-- Browser-driven sessions: the client reports state, the worker only times
-- them out. provider_session_id is the operator's own session id when the
-- browser SDK exposes it; recordings are matched by it, else by number + time.
ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS provider_session_id TEXT;
ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS client_seen_at TIMESTAMPTZ;
ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS muted BOOLEAN NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS idx_call_sessions_provider_session ON call_sessions (provider_session_id);

-- Which operator a fetched recording came from. `source` keeps its original
-- CHECK ('46elks' | 'upload'); operator recordings other than 46elks are
-- stored as source='upload' with provider set. Widening the CHECK is a
-- contract step for a later migration.
ALTER TABLE call_recordings ADD COLUMN IF NOT EXISTS provider TEXT;
