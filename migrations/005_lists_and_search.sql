-- expand_only: true
-- Lists, saved searches and company/contact profile fields for the
-- ZoomInfo-style search desk. Re-run safe; nothing here changes existing
-- columns or adds constraints to existing tables.

-- Profile fields shown on the company page and used as search filters.
ALTER TABLE companies ADD COLUMN IF NOT EXISTS employees INTEGER;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS revenue_eur NUMERIC(14,2);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS founded_year INTEGER;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS phone TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS linkedin_url TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS logo_url TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS technologies TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE companies ADD COLUMN IF NOT EXISTS owner_id UUID;        -- the seller who "owns" the account
CREATE INDEX IF NOT EXISTS idx_companies_industry ON companies (industry_code);
CREATE INDEX IF NOT EXISTS idx_companies_employees ON companies (employees);
CREATE INDEX IF NOT EXISTS idx_companies_owner ON companies (owner_id);

-- People: department and seniority are the two filters every B2B desk uses.
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS department TEXT;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS management_level TEXT;  -- c_level | vp | director | manager | staff | owner
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS linkedin_url TEXT;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;  -- last time a human confirmed the number works
CREATE INDEX IF NOT EXISTS idx_contacts_title ON contacts (lower(title));
CREATE INDEX IF NOT EXISTS idx_contacts_level ON contacts (management_level);

-- ---------------------------------------------------------------- lists
-- A list is a named bag of companies or people a seller builds from search
-- results and then pushes into a campaign queue or exports.
CREATE TABLE IF NOT EXISTS lists (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'company' CHECK (kind IN ('company', 'contact')),
    description TEXT,
    owner_id UUID REFERENCES users(id) ON DELETE SET NULL,
    shared BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_lists_owner ON lists (owner_id, updated_at);
DROP TRIGGER IF EXISTS trg_lists_updated_at ON lists;
CREATE TRIGGER trg_lists_updated_at BEFORE UPDATE ON lists
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS list_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    list_id UUID NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    contact_id UUID REFERENCES contacts(id) ON DELETE CASCADE,
    added_by UUID REFERENCES users(id) ON DELETE SET NULL,
    added_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_list_members_list ON list_members (list_id, added_at);
CREATE INDEX IF NOT EXISTS idx_list_members_company ON list_members (company_id);
-- one row per company (company lists) or per person (contact lists)
CREATE UNIQUE INDEX IF NOT EXISTS uq_list_members_company ON list_members (list_id, company_id) WHERE contact_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_list_members_contact ON list_members (list_id, contact_id) WHERE contact_id IS NOT NULL;

-- ---------------------------------------------------------------- saved searches
CREATE TABLE IF NOT EXISTS saved_searches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'company' CHECK (scope IN ('company', 'contact')),
    criteria JSONB NOT NULL DEFAULT '{}'::jsonb,
    owner_id UUID REFERENCES users(id) ON DELETE SET NULL,
    last_run_at TIMESTAMPTZ,
    last_result_count INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_saved_searches_owner ON saved_searches (owner_id, updated_at);
DROP TRIGGER IF EXISTS trg_saved_searches_updated_at ON saved_searches;
CREATE TRIGGER trg_saved_searches_updated_at BEFORE UPDATE ON saved_searches
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
