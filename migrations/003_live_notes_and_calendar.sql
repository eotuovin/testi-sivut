-- expand_only: true
-- Notes typed during a call (autosaved, survive a reload) and meeting details
-- on bookings so they can go into a calendar.

CREATE TABLE IF NOT EXISTS call_drafts (
    task_id UUID NOT NULL REFERENCES call_tasks(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    notes TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (task_id, user_id)
);

ALTER TABLE sales_bookings ADD COLUMN IF NOT EXISTS duration_minutes INTEGER NOT NULL DEFAULT 30;
ALTER TABLE sales_bookings ADD COLUMN IF NOT EXISTS location TEXT;          -- 'Teams', 'puhelin', osoite…
ALTER TABLE sales_bookings ADD COLUMN IF NOT EXISTS meeting_url TEXT;
ALTER TABLE sales_bookings ADD COLUMN IF NOT EXISTS attendee_email TEXT;    -- customer's email for the invite
ALTER TABLE sales_bookings ADD COLUMN IF NOT EXISTS calendar_event_id TEXT; -- set by the google_calendar target
ALTER TABLE sales_bookings ADD COLUMN IF NOT EXISTS calendar_html_link TEXT;

-- New integration target kind. Same drop/re-add pattern as movingfirm-backend
-- migration 022 (re-run safe).
ALTER TABLE integration_targets DROP CONSTRAINT IF EXISTS integration_targets_kind_check;
ALTER TABLE integration_targets ADD CONSTRAINT integration_targets_kind_check
    CHECK (kind IN ('webhook', 'movingfirm_internal', 'twenty', 'analytics', 'google_calendar'));
