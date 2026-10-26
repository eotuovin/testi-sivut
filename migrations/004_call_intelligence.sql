-- expand_only: true
-- Call intelligence: recordings → transcripts → structured analysis → insight reports.
-- Audio is held only until it is transcribed; transcript text is purged after
-- TRANSCRIPT_RETENTION_DAYS; the structured analysis (with redacted quotes) stays.

-- Recording needs the customer told at the start of the call.
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS recording_notice TEXT;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS recording_consent BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS recording_consent BOOLEAN NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS call_recordings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id UUID REFERENCES calls(id) ON DELETE CASCADE,
    session_id UUID REFERENCES call_sessions(id) ON DELETE SET NULL,
    source TEXT NOT NULL CHECK (source IN ('46elks', 'upload')),
    provider_recording_id TEXT,
    content_type TEXT,
    audio BYTEA,                       -- nulled as soon as it is transcribed
    audio_bytes INTEGER,
    duration_seconds INTEGER,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('awaiting_provider', 'pending', 'transcribing', 'transcribed', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    uploaded_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_call_recordings_status ON call_recordings (status, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_call_recordings_provider ON call_recordings (source, provider_recording_id)
    WHERE provider_recording_id IS NOT NULL;
DROP TRIGGER IF EXISTS trg_call_recordings_updated_at ON call_recordings;
CREATE TRIGGER trg_call_recordings_updated_at BEFORE UPDATE ON call_recordings
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS call_transcripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recording_id UUID NOT NULL UNIQUE REFERENCES call_recordings(id) ON DELETE CASCADE,
    call_id UUID REFERENCES calls(id) ON DELETE CASCADE,
    language TEXT,
    text TEXT,                         -- NULL after purge
    segments JSONB,
    provider TEXT NOT NULL,
    model TEXT,
    purge_after TIMESTAMPTZ NOT NULL,
    purged_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_call_transcripts_purge ON call_transcripts (purge_after) WHERE purged_at IS NULL;

-- One analysis per (call, source). Re-running replaces it.
CREATE TABLE IF NOT EXISTS call_analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id UUID NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    source TEXT NOT NULL CHECK (source IN ('transcript', 'notes')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'done', 'failed', 'skipped')),
    attempts INTEGER NOT NULL DEFAULT 0,
    provider TEXT,                     -- mirarun | miragen | anthropic
    agent TEXT,
    model TEXT,
    sentiment TEXT CHECK (sentiment IN ('positive', 'neutral', 'negative', 'mixed')),
    interest_level SMALLINT CHECK (interest_level BETWEEN 0 AND 5),
    reached_decision_maker BOOLEAN,
    stage_reached TEXT,                -- opening | pitch | discovery | objection | close | booked
    objections JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [{category, detail_fi, quote_redacted, handled}]
    blockers JSONB NOT NULL DEFAULT '[]'::jsonb,     -- [{category, detail_fi}]
    buying_signals JSONB NOT NULL DEFAULT '[]'::jsonb,
    friction JSONB NOT NULL DEFAULT '[]'::jsonb,     -- moments where the call stalled, [{moment_fi, cause_fi}]
    next_step_fi TEXT,
    summary_fi TEXT,
    coaching_fi TEXT,
    raw JSONB,
    error TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (call_id, source)
);
CREATE INDEX IF NOT EXISTS idx_call_analyses_status ON call_analyses (status, created_at);
DROP TRIGGER IF EXISTS trg_call_analyses_updated_at ON call_analyses;
CREATE TRIGGER trg_call_analyses_updated_at BEFORE UPDATE ON call_analyses
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS insight_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id UUID REFERENCES campaigns(id) ON DELETE SET NULL,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    stats JSONB NOT NULL,              -- the measured aggregates the narrative was written from
    narrative JSONB,                   -- {headline_fi, findings[], recommendations[], script_changes[]}
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'done', 'failed')),
    provider TEXT,
    agent TEXT,
    error TEXT,
    requested_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);
