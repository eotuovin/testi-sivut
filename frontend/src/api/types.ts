export interface Me {
  id: string | null
  name: string
  role: 'admin' | 'sales' | 'api'
}

export interface Contact {
  id: string
  name: string | null
  title: string | null
  department?: string | null
  management_level?: ManagementLevel | null
  linkedin_url?: string | null
  verified_at?: string | null
  phone: string | null
  phone_e164: string | null
  email: string | null
  is_primary: boolean
  do_not_call: boolean
  confidence: number | null
  source?: string
}

export interface Company {
  id: string
  business_id: string | null
  name: string
  website: string | null
  city: string | null
  industry_label: string | null
  industry_code?: string | null
  company_form?: string | null
  postal_code?: string | null
  street_address?: string | null
  registration_date?: string | null
  status: string
  source: string
  notes: string | null
  contact_count?: number
  updated_at: string
  // profile
  employees?: number | null
  revenue_eur?: number | string | null
  founded_year?: number | null
  description?: string | null
  phone?: string | null
  email?: string | null
  linkedin_url?: string | null
  logo_url?: string | null
  technologies?: string[]
  owner_id?: string | null
  owner_name?: string | null
}

export interface CompanyDetail extends Company {
  contacts: Contact[]
  calls: CallRow[]
  bookings: Booking[]
  tasks: { id: string; campaign_name: string; status: string; attempts: number; due_at: string }[]
  lists: { id: string; name: string; kind: string }[]
}

export type ManagementLevel = 'owner' | 'c_level' | 'vp' | 'director' | 'manager' | 'staff'
export const LEVEL_LABELS: Record<ManagementLevel, string> = {
  owner: 'Omistaja / yrittäjä', c_level: 'Johtoryhmä (C-taso)', vp: 'Varatoimitusjohtaja', director: 'Johtaja', manager: 'Päällikkö', staff: 'Asiantuntija',
}

/** One row of GET /search/companies: a company Luuri knows (in_db) or a register hit. */
export interface CompanyHit {
  id: string | null
  in_db: boolean
  business_id: string | null
  name: string
  website: string | null
  city: string | null
  postal_code?: string | null
  street_address?: string | null
  industry_code: string | null
  industry_label: string | null
  company_form: string | null
  registration_date: string | null
  status: string | null
  source: string
  employees: number | null
  revenue_eur: number | string | null
  contact_count: number
  phone_count: number
  email_count: number
  last_call_at?: string | null
  booking_count?: number
  owner_name?: string | null
  phone?: string | null
}

export interface CompanySearchResult {
  items: CompanyHit[]
  local_count: number
  register_total: number
  register_error: string | null
  page: number
}

export interface ContactHit {
  id: string
  company_id: string
  name: string | null
  title: string | null
  department: string | null
  management_level: ManagementLevel | null
  phone: string | null
  phone_e164: string | null
  email: string | null
  linkedin_url: string | null
  is_primary: boolean
  do_not_call: boolean
  confidence: number | null
  source: string
  verified_at: string | null
  company_name: string
  business_id: string | null
  city: string | null
  industry_label: string | null
  company_status: string
  website: string | null
  last_call_at: string | null
}

export interface Facets {
  cities: { city: string; n: number }[]
  industries: { industry_code: string | null; industry_label: string; n: number }[]
  titles: { title: string; n: number }[]
  departments: { department: string; n: number }[]
  owners: { id: string; name: string }[]
  management_levels: ManagementLevel[]
  company_forms: string[]
}

export interface List {
  id: string
  name: string
  kind: 'company' | 'contact'
  description: string | null
  owner_id: string | null
  owner_name: string | null
  shared: boolean
  member_count: number
  company_count: number
  phone_count: number
  created_at: string
  updated_at: string
}

export interface ListMember {
  id: string
  company_id: string
  contact_id: string | null
  added_at: string
  added_by_name: string | null
  company_name: string
  business_id: string | null
  city: string | null
  industry_label: string | null
  company_status: string
  website: string | null
  employees: number | null
  contact_name: string | null
  title: string | null
  phone_e164: string | null
  email: string | null
  do_not_call: boolean | null
  phone_count: number
  last_call_at: string | null
}

export interface ListDetail extends List {
  members: ListMember[]
}

export interface SavedSearch {
  id: string
  name: string
  scope: 'company' | 'contact'
  criteria: Record<string, unknown>
  owner_name: string | null
  last_run_at: string | null
  last_result_count: number | null
  created_at: string
}

export const STATUS_LABELS: Record<string, string> = {
  prospect: 'Prospekti', contacted: 'Kontaktoitu', qualified: 'Kvalifioitu', customer: 'Asiakas',
  disqualified: 'Ei sovi', do_not_call: 'Ei saa soittaa',
}

export interface Campaign {
  id: string
  name: string
  product: string
  script: string | null
  recording_notice?: string | null
  status: 'draft' | 'active' | 'paused' | 'archived'
  max_attempts: number
  retry_after_minutes: number
  open_tasks?: number
  done_tasks?: number
  bookings?: number
}

export interface CallHistory {
  started_at: string
  outcome: string
  notes: string | null
  callback_at: string | null
  user_name: string
}

export interface Task {
  id: string
  status: string
  attempts: number
  last_outcome: string | null
  campaign_id: string
  campaign_name: string
  product: string
  script: string | null
  recording_notice?: string | null
  max_attempts: number
  company_id: string
  company_name: string
  business_id: string | null
  website: string | null
  city: string | null
  industry_label: string | null
  company_status: string
  company_notes: string | null
  contact_id: string | null
  contact_name: string | null
  contact_title: string | null
  contact_phone: string | null
  phone_e164: string | null
  contact_email: string | null
  contacts: Contact[]
  history: CallHistory[]
  notes_draft?: string
}

export type Outcome =
  | 'no_answer' | 'busy' | 'voicemail' | 'gatekeeper' | 'callback'
  | 'not_interested' | 'wrong_number' | 'booked' | 'do_not_call' | 'already_customer'

export interface CallLog {
  session_id?: string
  task_id?: string
  company_id?: string
  contact_id?: string | null
  phone_dialed?: string | null
  outcome: Outcome
  duration_seconds?: number
  callback_at?: string | null
  notes?: string | null
  booking?: { scheduled_at?: string | null; duration_minutes?: number; location?: string | null; meeting_url?: string | null; attendee_email?: string | null; value_eur?: number | null; notes?: string | null }
  new_contact_name?: string | null
  new_contact_title?: string | null
  new_contact_phone?: string | null
  new_contact_email?: string | null
  recording_consent?: boolean
}

export interface CallRow {
  id: string
  started_at: string
  duration_seconds: number | null
  outcome: string
  callback_at: string | null
  notes: string | null
  user_name: string
  contact_name?: string | null
  phone_dialed?: string | null
  company_name?: string
  company_id?: string
  campaign_name?: string
}

export interface Booking {
  id: string
  company_id: string
  company_name?: string
  seller_name?: string
  contact_name?: string | null
  contact_phone?: string | null
  scheduled_at: string | null
  duration_minutes?: number
  location?: string | null
  meeting_url?: string | null
  attendee_email?: string | null
  calendar_html_link?: string | null
  product: string
  value_eur: number | null
  status: 'booked' | 'confirmed' | 'completed' | 'cancelled' | 'no_show'
  notes: string | null
  created_at: string
}

export interface Callback {
  task_id: string
  due_at: string
  company_name: string
  company_id: string
  campaign_name: string
  contact_name: string | null
  phone: string | null
}

export interface Stats {
  days: number
  per_user: { user_id: string; name: string; calls: number; conversations: number; booked: number; callbacks: number; talk_seconds: number | null }[]
  outcomes: { outcome: string; n: number }[]
  daily: { day: string; calls: number; booked: number }[]
  queue: Record<string, number>
}

export interface ProspectingRun {
  id: string
  campaign_id: string | null
  campaign_name: string | null
  criteria: Record<string, unknown>
  status: 'queued' | 'running' | 'done' | 'failed'
  stats: Record<string, number>
  error: string | null
  pending: number
  created_at: string
  requested_by_name: string | null
}

export interface ProspectContact {
  name: string | null
  title: string | null
  phone: string | null
  email: string | null
  confidence: number
}

export interface Prospect {
  id: string
  run_id: string
  campaign_id: string | null
  business_id: string | null
  name: string
  data: { register?: Record<string, string | null>; enrichment?: { summary?: string | null; fit_reason?: string | null; phones?: string[]; emails?: string[]; fetch_errors?: string[]; error?: string | null } | null }
  found_contacts: ProspectContact[]
  score: number | null
  review_status: string
}

export interface IntegrationTarget {
  id: string
  kind: string
  name: string
  config: Record<string, unknown>
  event_types: string[]
  enabled: boolean
  failed: number
  last_ok_at: string | null
}

export interface OutboxEvent {
  id: string
  event_type: string
  aggregate_type: string
  status: string
  attempts: number
  last_error: string | null
  created_at: string
}

export interface User {
  id: string
  email: string
  name: string
  role: 'admin' | 'sales'
  active: boolean
}

export const OUTCOME_LABELS: Record<Outcome, string> = {
  no_answer: 'Ei vastausta',
  busy: 'Varattu',
  voicemail: 'Vastaaja',
  gatekeeper: 'Vaihde / ei päättäjää',
  callback: 'Soita uudelleen',
  not_interested: 'Ei kiinnosta',
  wrong_number: 'Väärä numero',
  booked: 'Bookattu!',
  do_not_call: 'Ei saa soittaa',
  already_customer: 'On jo asiakas',
}

// ---------------------------------------------------------------- sequences
export type StepKind = 'call' | 'email' | 'task'
export const STEP_LABELS: Record<StepKind, string> = { call: 'Soitto', email: 'Sähköposti', task: 'Tehtävä' }

export interface SequenceStep {
  id?: string
  position?: number
  kind: StepKind
  delay_days: number
  delay_hours: number
  title: string | null
  body: string | null
}

export interface Sequence {
  id: string
  name: string
  description: string | null
  campaign_id: string | null
  campaign_name: string | null
  status: 'active' | 'paused' | 'archived'
  stop_on_outcomes: string[]
  owner_name: string | null
  step_count: number
  active_count: number
  finished_count: number
  stopped_count: number
  booked_count: number
  created_at: string
  updated_at: string
}

export interface SequenceEnrollment {
  id: string
  sequence_id: string
  company_id: string
  contact_id: string | null
  status: 'active' | 'finished' | 'stopped' | 'failed'
  current_step: number
  next_at: string | null
  finished_reason: string | null
  created_at: string
  company_name: string
  business_id: string | null
  city: string | null
  contact_name: string | null
  contact_title: string | null
  contact_email: string | null
  started_by_name: string | null
  done_steps: number
}

export interface SequenceDetail extends Sequence {
  steps: SequenceStep[]
  enrollments: SequenceEnrollment[]
}

export interface SequenceAction {
  id: string
  enrollment_id: string
  position: number
  kind: StepKind
  status: 'pending' | 'done' | 'skipped' | 'failed'
  due_at: string
  done_at: string | null
  email_to: string | null
  subject: string | null
  body: string | null
  sent_via: string | null
  error: string | null
  sequence_id: string
  sequence_name: string
  company_id: string
  company_name: string
  website: string | null
  contact_id: string | null
  contact_name: string | null
  contact_title: string | null
  phone_e164: string | null
  contact_email: string | null
  started_by_name: string | null
}

export interface CompanySequence {
  id: string
  status: SequenceEnrollment['status']
  current_step: number
  next_at: string | null
  finished_reason: string | null
  created_at: string
  sequence_id: string
  sequence_name: string
  step_count: number
  contact_name: string | null
}
