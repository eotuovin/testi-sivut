import { defineStore } from 'pinia'
import { apiGet, apiPatch, apiPost } from '../api/client'

export interface TelephonyStatus {
  enabled: boolean
  provider: string | null
  from_number: string | null
  recording: boolean
  misconfigured: boolean
  ai: { provider: string | null; reachable?: boolean; agent?: string | null; status?: string | null; model?: string; error?: string }
}

export interface CallSession {
  id: string
  state: 'dialing_agent' | 'connecting' | 'in_progress' | 'ended' | 'no_answer' | 'busy' | 'failed'
  customer_number: string
  agent_number: string
  from_number: string | null
  duration_seconds: number | null
  cost_cents: number | null
  recording_url: string | null
  error: string | null
  created_at: string
  answered_at: string | null
  ended_at: string | null
}

export const SESSION_LABELS: Record<CallSession['state'], string> = {
  dialing_agent: 'Soitetaan sinun puhelimeesi…',
  connecting: 'Yhdistetään asiakkaalle…',
  in_progress: 'Puhelu käynnissä',
  ended: 'Puhelu päättyi',
  no_answer: 'Asiakas ei vastannut',
  busy: 'Asiakkaan numero varattu',
  failed: 'Soitto ei onnistunut',
}

export const ACTIVE_STATES = new Set<CallSession['state']>(['dialing_agent', 'connecting', 'in_progress'])

export const useTelephonyStore = defineStore('telephony', {
  state: () => ({
    status: null as TelephonyStatus | null,
    myPhone: null as string | null,
    session: null as CallSession | null,
    poll: undefined as number | undefined,
  }),
  getters: {
    active: (s) => !!s.session && ACTIVE_STATES.has(s.session.state),
  },
  actions: {
    async load() {
      const [status, me] = await Promise.all([apiGet<TelephonyStatus>('/telephony/status'), apiGet<{ phone_e164: string | null }>('/me')])
      this.status = status
      this.myPhone = me.phone_e164
    },
    async saveMyPhone(phone: string) {
      const r = await apiPatch<{ phone_e164: string | null }>('/me', { phone })
      this.myPhone = r.phone_e164
    },
    async dial(body: { task_id?: string; company_id?: string; contact_id?: string | null; phone?: string | null }) {
      this.session = await apiPost<CallSession>('/telephony/dial', body)
      this.startPolling()
    },
    startPolling() {
      this.stopPolling()
      this.poll = window.setInterval(async () => {
        if (!this.session) return this.stopPolling()
        this.session = await apiGet<CallSession>(`/telephony/sessions/${this.session.id}`)
        if (!ACTIVE_STATES.has(this.session.state)) this.stopPolling()
      }, 2000)
    },
    stopPolling() {
      if (this.poll) window.clearInterval(this.poll)
      this.poll = undefined
    },
    async hangup() {
      if (!this.session) return
      this.session = await apiPost<CallSession>(`/telephony/sessions/${this.session.id}/hangup`)
      this.stopPolling()
    },
    clear() {
      this.stopPolling()
      this.session = null
    },
  },
})
