import { defineStore } from 'pinia'
import { apiGet, apiPatch, apiPost } from '../api/client'

export interface TelephonyStatus {
  enabled: boolean
  provider: string | null
  from_number: string | null
  recording: boolean
  misconfigured: boolean
  browser: boolean
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
  muted?: boolean
}

export const SESSION_LABELS: Record<CallSession['state'], string> = {
  dialing_agent: 'Soitetaan sinun puhelimeesi…',
  connecting: 'Soitetaan asiakkaalle…',
  in_progress: 'Puhelu käynnissä',
  ended: 'Puhelu päättyi',
  no_answer: 'Asiakas ei vastannut',
  busy: 'Asiakkaan numero varattu',
  failed: 'Soitto ei onnistunut',
}

export const ACTIVE_STATES = new Set<CallSession['state']>(['dialing_agent', 'connecting', 'in_progress'])

type DialBody = { task_id?: string; company_id?: string; contact_id?: string | null; phone?: string | null }

/** Browser (WebRTC) dialer: the Telnyx SDK is loaded only when the server says
 *  browser calling is on, and one client is kept for the whole tab. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type RtcClient = any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type RtcCall = any

export const useTelephonyStore = defineStore('telephony', {
  state: () => ({
    status: null as TelephonyStatus | null,
    myPhone: null as string | null,
    session: null as CallSession | null,
    poll: undefined as number | undefined,
    // browser dialer
    rtc: null as RtcClient | null,
    rtcReady: false,
    rtcError: '' as string,
    call: null as RtcCall | null,
    muted: false,
    heartbeat: undefined as number | undefined,
    micDenied: false,
  }),
  getters: {
    active: (s) => !!s.session && ACTIVE_STATES.has(s.session.state),
    browser: (s) => !!s.status?.browser,
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

    // ---------------------------------------------------------------- bridged (46elks)
    async dial(body: DialBody) {
      if (this.browser) return this.dialBrowser(body)
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
      if (this.browser) return this.hangupBrowser()
      this.session = await apiPost<CallSession>(`/telephony/sessions/${this.session.id}/hangup`)
      this.stopPolling()
    },
    clear() {
      this.stopPolling()
      this.stopHeartbeat()
      this.session = null
      this.call = null
      this.muted = false
    },

    // ---------------------------------------------------------------- browser (Telnyx WebRTC)
    /** Connect the SDK once per tab. Resolves when logged in. */
    async connectBrowser() {
      if (this.rtc && this.rtcReady) return
      this.rtcError = ''
      const { token } = await apiPost<{ token: string }>('/telephony/webrtc/token')
      const { TelnyxRTC } = await import('@telnyx/webrtc')
      const client = new TelnyxRTC({ login_token: token })
      client.remoteElement = 'luuri-remote-audio'
      await new Promise<void>((resolve, reject) => {
        const t = window.setTimeout(() => reject(new Error('Telnyx ei vastannut (yhteys)')), 15000)
        client.on('telnyx.ready', () => { window.clearTimeout(t); this.rtcReady = true; resolve() })
        client.on('telnyx.error', (e: { message?: string }) => { window.clearTimeout(t); this.rtcError = e?.message || 'Telnyx-virhe'; reject(new Error(this.rtcError)) })
        client.on('telnyx.socket.close', () => { this.rtcReady = false })
        client.on('telnyx.notification', (n: { type: string; call?: RtcCall }) => this.onNotification(n))
        client.connect()
      })
      this.rtc = client
    },
    async dialBrowser(body: DialBody) {
      await this.connectBrowser()
      // the session first: outcome, duration and recording attach to it
      this.session = await apiPost<CallSession>('/telephony/sessions', body)
      this.muted = false
      try {
        this.call = this.rtc.newCall({
          destinationNumber: this.session.customer_number,
          callerNumber: this.status?.from_number ?? undefined,
          audio: true,
          video: false,
          remoteElement: 'luuri-remote-audio',
        })
      } catch (e) {
        await this.report({ state: 'failed', error: (e as Error).message })
        throw e
      }
      this.startHeartbeat()
    },
    async onNotification(n: { type: string; call?: RtcCall }) {
      if (n.type !== 'callUpdate' || !n.call || !this.session) return
      const call = n.call
      const ids = (() => { try { return call.telnyxIDs } catch { return null } })()
      const idBody = ids ? { provider_call_id: ids.telnyxCallControlId || null, provider_session_id: ids.telnyxSessionId || null } : {}
      switch (call.state) {
        case 'requesting':
        case 'ringing':
          await this.report({ state: 'connecting', ...idBody })
          break
        case 'active':
          this.call = call
          await this.report({ state: 'in_progress', ...idBody })
          break
        case 'hangup': {
          const cause = String(call.cause || '').toUpperCase()
          const answered = !!this.session.answered_at || this.session.state === 'in_progress'
          const state = answered ? 'ended' : cause.includes('BUSY') ? 'busy' : cause.includes('NO_ANSWER') || cause.includes('TIMEOUT') || cause.includes('CANCEL') ? 'no_answer' : cause.includes('NORMAL') || cause === '' ? 'ended' : 'failed'
          await this.report({ state, error: state === 'failed' ? `${call.cause} (${call.causeCode})` : null, ...idBody })
          this.stopHeartbeat()
          this.call = null
          break
        }
        case 'destroy':
          this.stopHeartbeat()
          break
      }
    },
    async report(body: { state?: string; provider_call_id?: string | null; provider_session_id?: string | null; muted?: boolean; error?: string | null }) {
      if (!this.session) return
      try {
        this.session = await apiPost<CallSession>(`/telephony/sessions/${this.session.id}/state`, body)
      } catch { /* a missed heartbeat is fine; the next one lands */ }
    },
    startHeartbeat() {
      this.stopHeartbeat()
      this.heartbeat = window.setInterval(() => { if (this.session && ACTIVE_STATES.has(this.session.state)) this.report({}) }, 15000)
    },
    stopHeartbeat() {
      if (this.heartbeat) window.clearInterval(this.heartbeat)
      this.heartbeat = undefined
    },
    async hangupBrowser() {
      try { await this.call?.hangup() } catch { /* already gone */ }
      if (this.session && ACTIVE_STATES.has(this.session.state)) await this.report({ state: this.session.answered_at ? 'ended' : 'no_answer' })
      this.stopHeartbeat()
      this.call = null
    },
    toggleMute() {
      if (!this.call) return
      this.muted ? this.call.unmuteAudio() : this.call.muteAudio()
      this.muted = !this.muted
      this.report({ muted: this.muted })
    },
  },
})
