-- expand_only: true
-- Telephony (bridged calls through a provider) and per-caller phone numbers.

-- The caller's own phone: the provider rings this first, then connects the customer.
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_e164 TEXT;

-- One row per live telephony leg. `calls` stays the outcome log a person
-- writes; a session links to the call once the outcome is saved.
CREATE TABLE IF NOT EXISTS call_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    task_id UUID REFERENCES call_tasks(id) ON DELETE SET NULL,
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    contact_id UUID REFERENCES contacts(id) ON DELETE SET NULL,
    call_id UUID REFERENCES calls(id) ON DELETE SET NULL,
    provider TEXT NOT NULL,                   -- '46elks' | 'tel'
    provider_call_id TEXT,
    from_number TEXT,                         -- caller id the customer sees
    agent_number TEXT NOT NULL,               -- the caller's own phone (rung first)
    customer_number TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'dialing_agent'
        CHECK (state IN ('dialing_agent', 'connecting', 'in_progress', 'ended', 'no_answer', 'busy', 'failed')),
    duration_seconds INTEGER,
    cost_cents INTEGER,
    recording_url TEXT,
    error TEXT,
    raw JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    answered_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_call_sessions_active
    ON call_sessions (state, updated_at) WHERE state IN ('dialing_agent', 'connecting', 'in_progress');
CREATE INDEX IF NOT EXISTS idx_call_sessions_user ON call_sessions (user_id, created_at);
DROP TRIGGER IF EXISTS trg_call_sessions_updated_at ON call_sessions;
CREATE TRIGGER trg_call_sessions_updated_at BEFORE UPDATE ON call_sessions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Which AI produced an enrichment (anthropic | mira | rules), for provenance.
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS enriched_by TEXT;
