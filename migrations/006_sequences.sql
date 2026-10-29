-- expand_only: true
-- Sequences: an ordered chain of touches (call, email, task) that a company or
-- a person is enrolled in, Apollo/LeadDesk-style. The worker materialises each
-- step when its time comes: a call step becomes a call_task in the sequence's
-- campaign queue, an email step is sent (SMTP) or left for the seller to send,
-- a task step is a to-do. Re-run safe; nothing here touches existing tables.

CREATE TABLE IF NOT EXISTS sequences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    campaign_id UUID REFERENCES campaigns(id) ON DELETE SET NULL,   -- call steps go into this queue
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'archived')),
    stop_on_outcomes TEXT[] NOT NULL DEFAULT ARRAY['booked', 'not_interested', 'do_not_call', 'already_customer'],
    owner_id UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS trg_sequences_updated_at ON sequences;
CREATE TRIGGER trg_sequences_updated_at BEFORE UPDATE ON sequences
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS sequence_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sequence_id UUID NOT NULL REFERENCES sequences(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('call', 'email', 'task')),
    delay_days INTEGER NOT NULL DEFAULT 0,      -- after the previous step (step 1: after enrolment)
    delay_hours INTEGER NOT NULL DEFAULT 0,
    title TEXT,                                 -- task label / email subject
    body TEXT,                                  -- email body or task instructions; {{yritys}} {{nimi}} {{etunimi}} {{myyja}} {{tuote}}
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sequence_steps_seq ON sequence_steps (sequence_id, position);

CREATE TABLE IF NOT EXISTS sequence_enrollments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sequence_id UUID NOT NULL REFERENCES sequences(id) ON DELETE CASCADE,
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    contact_id UUID REFERENCES contacts(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'finished', 'stopped', 'failed')),
    current_step INTEGER NOT NULL DEFAULT 0,     -- steps materialised so far
    next_at TIMESTAMPTZ,                         -- when the next step is due; NULL when not active
    finished_reason TEXT,
    started_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sequence_enrollments_due ON sequence_enrollments (status, next_at);
CREATE INDEX IF NOT EXISTS idx_sequence_enrollments_company ON sequence_enrollments (company_id);
-- one active run per sequence and company
CREATE UNIQUE INDEX IF NOT EXISTS uq_sequence_enrollments_active ON sequence_enrollments (sequence_id, company_id) WHERE status = 'active';
DROP TRIGGER IF EXISTS trg_sequence_enrollments_updated_at ON sequence_enrollments;
CREATE TRIGGER trg_sequence_enrollments_updated_at BEFORE UPDATE ON sequence_enrollments
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS sequence_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    enrollment_id UUID NOT NULL REFERENCES sequence_enrollments(id) ON DELETE CASCADE,
    step_id UUID REFERENCES sequence_steps(id) ON DELETE SET NULL,
    position INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('call', 'email', 'task')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'skipped', 'failed')),
    due_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    done_at TIMESTAMPTZ,
    done_by UUID REFERENCES users(id) ON DELETE SET NULL,
    task_id UUID REFERENCES call_tasks(id) ON DELETE SET NULL,  -- the call_task a call step created
    email_to TEXT,
    subject TEXT,
    body TEXT,
    sent_via TEXT,                               -- smtp | manual
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sequence_actions_inbox ON sequence_actions (status, due_at);
CREATE INDEX IF NOT EXISTS idx_sequence_actions_enrollment ON sequence_actions (enrollment_id, position);
CREATE INDEX IF NOT EXISTS idx_sequence_actions_task ON sequence_actions (task_id);
