export interface Me {
  id: string | null
  name: string
  role: 'admin' | 'sales' | 'api'
}

export interface Contact {
  id: string
  name: string | null
  title: string | null
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
  status: string
  source: string
  notes: string | null
  contact_count?: number
  updated_at: string
}

export interface CompanyDetail extends Company {
  contacts: Contact[]
  calls: CallRow[]
  bookings: Booking[]
  tasks: { id: string; campaign_name: string; status: string; attempts: number; due_at: string }[]
}

export interface Campaign {
  id: string
  name: string
  product: string
  script: string | null
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
