-- expand_only: true
-- Luuri: outbound B2B sales desk. Re-run safe (IF NOT EXISTS everywhere).

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------- users
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'sales' CHECK (role IN ('admin', 'sales')),
    password_hash TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS trg_users_updated_at ON users;
CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Machine callers (other systems reading/writing through the API).
CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    scopes TEXT[] NOT NULL DEFAULT ARRAY['read'],
    active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ
);

-- ---------------------------------------------------------------- companies
CREATE TABLE IF NOT EXISTS companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id TEXT UNIQUE,                 -- Y-tunnus, NNNNNNN-N
    name TEXT NOT NULL,
    website TEXT,
    domain TEXT,
    industry_code TEXT,                      -- TOL 2008
    industry_label TEXT,
    company_form TEXT,
    city TEXT,
    postal_code TEXT,
    street_address TEXT,
    registration_date DATE,
    status TEXT NOT NULL DEFAULT 'prospect'
        CHECK (status IN ('prospect', 'contacted', 'qualified', 'customer',
                          'disqualified', 'do_not_call')),
    source TEXT NOT NULL DEFAULT 'manual'
        CHECK (source IN ('manual', 'import', 'prh', 'agent', 'crm')),
    external_refs JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {"twenty_company_id": ..}
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_companies_status ON companies (status, updated_at);
CREATE INDEX IF NOT EXISTS idx_companies_name ON companies (lower(name));
CREATE INDEX IF NOT EXISTS idx_companies_city ON companies (lower(city));
DROP TRIGGER IF EXISTS trg_companies_updated_at ON companies;
CREATE TRIGGER trg_companies_updated_at BEFORE UPDATE ON companies
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name TEXT,
    title TEXT,
    phone TEXT,
    phone_e164 TEXT,
    email TEXT,
    is_primary BOOLEAN NOT NULL DEFAULT false,
    source TEXT NOT NULL DEFAULT 'manual'
        CHECK (source IN ('manual', 'import', 'prh', 'agent', 'crm', 'call')),
    confidence NUMERIC(3,2),                 -- 0..1 for agent-found contacts
    do_not_call BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_contacts_company ON contacts (company_id);
CREATE INDEX IF NOT EXISTS idx_contacts_phone ON contacts (phone_e164);
DROP TRIGGER IF EXISTS trg_contacts_updated_at ON contacts;
CREATE TRIGGER trg_contacts_updated_at BEFORE UPDATE ON contacts
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS do_not_call (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone_e164 TEXT NOT NULL UNIQUE,
    reason TEXT,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- campaigns
CREATE TABLE IF NOT EXISTS campaigns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    product TEXT NOT NULL,                   -- what is being sold
    script TEXT,                             -- call script shown to the caller
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('draft', 'active', 'paused', 'archived')),
    max_attempts INTEGER NOT NULL DEFAULT 4,
    retry_after_minutes INTEGER NOT NULL DEFAULT 240,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS trg_campaigns_updated_at ON campaigns;
CREATE TRIGGER trg_campaigns_updated_at BEFORE UPDATE ON campaigns
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- The call queue. One task per (campaign, company); the current contact can change.
CREATE TABLE IF NOT EXISTS call_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    contact_id UUID REFERENCES contacts(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'in_progress', 'callback', 'done', 'skipped')),
    priority INTEGER NOT NULL DEFAULT 0,
    due_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    assigned_to UUID REFERENCES users(id) ON DELETE SET NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_outcome TEXT,
    locked_by UUID REFERENCES users(id) ON DELETE SET NULL,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (campaign_id, company_id)
);
CREATE INDEX IF NOT EXISTS idx_call_tasks_queue
    ON call_tasks (campaign_id, status, due_at, priority DESC);
DROP TRIGGER IF EXISTS trg_call_tasks_updated_at ON call_tasks;
CREATE TRIGGER trg_call_tasks_updated_at BEFORE UPDATE ON call_tasks
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID REFERENCES call_tasks(id) ON DELETE SET NULL,
    campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    contact_id UUID REFERENCES contacts(id) ON DELETE SET NULL,
    user_id UUID NOT NULL REFERENCES users(id),
    phone_dialed TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ,
    duration_seconds INTEGER,
    outcome TEXT NOT NULL
        CHECK (outcome IN ('no_answer', 'busy', 'voicemail', 'gatekeeper',
                           'callback', 'not_interested', 'wrong_number',
                           'booked', 'do_not_call', 'already_customer')),
    callback_at TIMESTAMPTZ,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_calls_user_time ON calls (user_id, started_at);
CREATE INDEX IF NOT EXISTS idx_calls_company ON calls (company_id, started_at);

-- A sold booking: the thing this desk exists to produce.
CREATE TABLE IF NOT EXISTS sales_bookings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id UUID REFERENCES calls(id) ON DELETE SET NULL,
    campaign_id UUID NOT NULL REFERENCES campaigns(id),
    company_id UUID NOT NULL REFERENCES companies(id),
    contact_id UUID REFERENCES contacts(id) ON DELETE SET NULL,
    user_id UUID NOT NULL REFERENCES users(id),
    scheduled_at TIMESTAMPTZ,
    product TEXT NOT NULL,
    value_eur NUMERIC(10,2),
    status TEXT NOT NULL DEFAULT 'booked'
        CHECK (status IN ('booked', 'confirmed', 'completed', 'cancelled', 'no_show')),
    external_refs JSONB NOT NULL DEFAULT '{}'::jsonb,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sales_bookings_user ON sales_bookings (user_id, created_at);
DROP TRIGGER IF EXISTS trg_sales_bookings_updated_at ON sales_bookings;
CREATE TRIGGER trg_sales_bookings_updated_at BEFORE UPDATE ON sales_bookings
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------- prospecting
CREATE TABLE IF NOT EXISTS prospecting_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id UUID REFERENCES campaigns(id) ON DELETE SET NULL,
    criteria JSONB NOT NULL,                 -- {location, industry, max_results, ...}
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'done', 'failed')),
    requested_by UUID REFERENCES users(id) ON DELETE SET NULL,
    stats JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

-- Candidate companies found by the agent; a person approves before they enter the queue.
CREATE TABLE IF NOT EXISTS prospects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES prospecting_runs(id) ON DELETE CASCADE,
    business_id TEXT,
    name TEXT NOT NULL,
    data JSONB NOT NULL DEFAULT '{}'::jsonb, -- raw register row + enrichment
    found_contacts JSONB NOT NULL DEFAULT '[]'::jsonb,
    score NUMERIC(3,2),
    review_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'approved', 'rejected', 'duplicate')),
    reviewed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    company_id UUID REFERENCES companies(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_prospects_run ON prospects (run_id, review_status);

-- ---------------------------------------------------------------- integrations
-- Every business change writes a row here in the same transaction; the worker
-- delivers it to each enabled target. Same pattern as movingfirm-backend.
CREATE TABLE IF NOT EXISTS outbox_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id UUID NOT NULL,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'delivered', 'dead')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_until TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending
    ON outbox_events (status, next_retry_at) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS integration_targets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind TEXT NOT NULL
        CHECK (kind IN ('webhook', 'movingfirm_internal', 'twenty', 'analytics')),
    name TEXT NOT NULL,
    config JSONB NOT NULL DEFAULT '{}'::jsonb, -- url, secret_env, extra
    event_types TEXT[] NOT NULL DEFAULT ARRAY['*'],
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS trg_integration_targets_updated_at ON integration_targets;
CREATE TRIGGER trg_integration_targets_updated_at BEFORE UPDATE ON integration_targets
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS integration_deliveries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES outbox_events(id) ON DELETE CASCADE,
    target_id UUID NOT NULL REFERENCES integration_targets(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'ok', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    response_code INTEGER,
    response_body TEXT,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (event_id, target_id)
);
DROP TRIGGER IF EXISTS trg_integration_deliveries_updated_at ON integration_deliveries;
CREATE TRIGGER trg_integration_deliveries_updated_at BEFORE UPDATE ON integration_deliveries
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
