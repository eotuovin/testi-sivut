export interface Objection { category: string; detail_fi: string | null; quote_redacted: string | null; handled: boolean | null }

export interface CallAnalysis {
  id: string
  call_id: string
  source: 'transcript' | 'notes'
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped'
  provider: string | null
  agent: string | null
  sentiment: 'positive' | 'neutral' | 'negative' | 'mixed' | null
  interest_level: number | null
  reached_decision_maker: boolean | null
  stage_reached: string | null
  objections: Objection[]
  blockers: { category: string; detail_fi: string | null }[]
  buying_signals: { signal_fi?: string }[]
  friction: { moment_fi?: string; cause_fi?: string }[]
  next_step_fi: string | null
  summary_fi: string | null
  coaching_fi: string | null
  error: string | null
}

export interface CallAnalysisBundle {
  analyses: CallAnalysis[]
  recordings: { id: string; source: string; status: string; audio_bytes: number | null; duration_seconds: number | null; error: string | null }[]
  transcript: { text: string | null; segments: { start: number; end: number; text: string }[] | null; purged_at: string | null; purge_after: string } | null
}

export interface InsightStats {
  calls: { calls: number; conversations: number; booked: number }
  analysed: { analysed: number; from_transcripts: number; from_notes: number; avg_interest: number | null; reached_dm: number }
  objections: { category: string; label_fi: string; calls: number; mentions: number; handled_rate: number | null; booked_rate: number | null; examples: { detail_fi: string | null; quote: string | null }[] }[]
  blockers: { category: string; calls: number }[]
  sentiment: { sentiment: string | null; n: number }[]
  stages: { stage: string | null; n: number; booked: number }[]
  friction_samples: { moment_fi: string | null; cause_fi: string | null; n: number }[]
}

export interface InsightReport {
  id: string
  campaign_name: string | null
  period_start: string
  period_end: string
  status: string
  analysed: number | null
  narrative: {
    headline_fi?: string
    findings?: { title_fi: string; evidence_fi: string; impact: string }[]
    recommendations?: { action_fi: string; why_fi: string; area: string }[]
    script_changes?: { objection_category: string; suggested_reply_fi: string }[]
    data_gaps_fi?: string[]
  } | null
  error: string | null
  agent: string | null
  created_at: string
}

export interface IntelligenceStatus {
  ai: { provider: string | null; reachable?: boolean; agents?: Record<string, string> }
  stt: { configured: boolean; model: string | null; language: string }
  recording_enabled: boolean
  analyses_pending: number
  analyses_done: number
  analyses_failed: number
  transcript_retention_days: number
}

export const OBJECTION_FI: Record<string, string> = {
  price: 'Hinta', no_need: 'Ei tarvetta', timing: 'Ajoitus', already_has_solution: 'On jo ratkaisu', no_authority: 'Ei päätösvaltaa',
  send_info: 'Laita sähköpostia', trust: 'Luottamus', contract_lock: 'Sopimus voimassa', too_busy: 'Ei aikaa', bad_experience: 'Huono kokemus', other: 'Muu',
}
export const BLOCKER_FI: Record<string, string> = {
  not_decision_maker: 'Ei päättäjä', gatekeeper: 'Vaihde/sihteeri', no_budget: 'Ei budjettia', wrong_contact: 'Väärä henkilö',
  company_policy: 'Yrityksen linjaus', language: 'Kieli', other: 'Muu',
}
export const SENTIMENT_FI: Record<string, string> = { positive: 'Myönteinen', neutral: 'Neutraali', negative: 'Kielteinen', mixed: 'Ristiriitainen' }
export const STAGE_FI: Record<string, string> = {
  opening: 'Avaus', pitch: 'Esittely', discovery: 'Tarvekartoitus', objection_handling: 'Vastaväitteet', close: 'Klousaus', booked: 'Bookattu',
}
