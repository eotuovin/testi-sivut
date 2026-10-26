<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { apiGet, apiPost, errorText } from '../api/client'
import type { Campaign } from '../api/types'
import type { InsightReport, InsightStats, IntelligenceStatus } from '../api/intelligence'
import { BLOCKER_FI, SENTIMENT_FI, STAGE_FI } from '../api/intelligence'
import { fmtDate, fmtDateTime } from '../format'

const days = ref(30)
const campaignId = ref('')
const campaigns = ref<Campaign[]>([])
const stats = ref<InsightStats | null>(null)
const reports = ref<InsightReport[]>([])
const status = ref<IntelligenceStatus | null>(null)
const error = ref('')
const busy = ref(false)
let poll: number | undefined

async function load() {
  error.value = ''
  try {
    ;[stats.value, reports.value, status.value] = await Promise.all([
      apiGet<InsightStats>('/insights/summary', { days: days.value, campaign_id: campaignId.value || undefined }),
      apiGet<InsightReport[]>('/insights/reports'),
      apiGet<IntelligenceStatus>('/intelligence/status'),
    ])
  } catch (e) {
    error.value = errorText(e)
  }
}
onMounted(async () => {
  campaigns.value = await apiGet<Campaign[]>('/campaigns')
  await load()
  poll = window.setInterval(() => {
    if (reports.value.some((r) => r.status === 'pending' || r.status === 'running')) load()
  }, 5000)
})
onBeforeUnmount(() => window.clearInterval(poll))

async function generate() {
  busy.value = true
  error.value = ''
  try {
    await apiPost('/insights/reports', { days: days.value, campaign_id: campaignId.value || null })
    await load()
  } catch (e) {
    error.value = errorText(e)
  } finally {
    busy.value = false
  }
}

const maxObj = computed(() => Math.max(1, ...(stats.value?.objections.map((o) => o.calls) ?? [1])))
const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${Math.round(v * 100)} %`)
const latest = computed(() => reports.value.find((r) => r.status === 'done' && r.narrative))
</script>

<template>
  <h1>Oivallukset</h1>
  <p class="muted small">Mitä asiakkaat vastaavat, mihin puhelut jumittuvat ja mitä spiikissä kannattaa muuttaa. Luvut lasketaan puheluanalyyseistä; yhteenvedon kirjoittaa Mira pelkistä luvuista ja anonymisoiduista esimerkeistä.</p>
  <div class="row" style="margin-bottom: 1rem">
    <select v-model.number="days" style="width: auto" @change="load"><option :value="7">7 päivää</option><option :value="30">30 päivää</option><option :value="90">90 päivää</option></select>
    <select v-model="campaignId" style="width: auto" @change="load"><option value="">Kaikki kampanjat</option><option v-for="c in campaigns" :key="c.id" :value="c.id">{{ c.name }}</option></select>
    <button class="primary" :disabled="busy || !stats?.analysed.analysed" @click="generate">Pyydä Miralta yhteenveto</button>
  </div>
  <p v-if="error" class="error">{{ error }}</p>

  <div v-if="status" class="small muted" style="margin-bottom: 0.75rem">
    Tekoäly: <strong>{{ status.ai.provider === 'mirarun' ? 'Mira (mirarun)' : status.ai.provider ?? 'ei käytössä' }}</strong>
    · Puheentunnistus: <strong>{{ status.stt.configured ? status.stt.model : 'ei käytössä – analysoidaan muistiinpanot' }}</strong>
    · Analysoitu {{ status.analyses_done }}, jonossa {{ status.analyses_pending }}<span v-if="status.analyses_failed">, epäonnistui {{ status.analyses_failed }}</span>
  </div>

  <div v-if="stats && !stats.analysed.analysed" class="empty">Jaksolla ei ole vielä analysoituja puheluita. Analyysi syntyy kun soittaja kirjoittaa muistiinpanot tai puhelusta on nauhoite.</div>

  <template v-if="stats && stats.analysed.analysed">
    <div class="kpis" style="margin-bottom: 1rem">
      <div class="kpi"><div class="muted small">Analysoituja puheluita</div><div class="n">{{ stats.analysed.analysed }}</div><div class="small muted">{{ stats.analysed.from_transcripts }} nauhoitteesta · {{ stats.analysed.from_notes }} muistiinpanoista</div></div>
      <div class="kpi"><div class="muted small">Kiinnostus keskimäärin</div><div class="n">{{ stats.analysed.avg_interest ?? '—' }}<span class="small muted"> / 5</span></div></div>
      <div class="kpi"><div class="muted small">Päättäjä tavoitettu</div><div class="n">{{ stats.analysed.reached_dm }}</div><div class="small muted">{{ pct(stats.analysed.reached_dm / stats.analysed.analysed) }} analysoiduista</div></div>
      <div class="kpi"><div class="muted small">Bookattu</div><div class="n">{{ stats.calls.booked }}</div><div class="small muted">{{ stats.calls.conversations }} keskustelusta</div></div>
    </div>

    <div class="card">
      <h2>Vastaväitteet</h2>
      <table class="small">
        <tr><th>Vastaväite</th><th style="width: 30%">Puheluita</th><th>Käsitelty</th><th>Bookattiin silti</th><th>Esimerkkejä</th></tr>
        <tr v-for="o in stats.objections" :key="o.category">
          <td><strong>{{ o.label_fi }}</strong></td>
          <td><div class="row" style="gap: 0.4rem; flex-wrap: nowrap"><div class="bar" style="flex: 1"><i :style="{ width: (100 * o.calls) / maxObj + '%' }" /></div>{{ o.calls }}</div></td>
          <td>{{ pct(o.handled_rate) }}</td>
          <td>{{ pct(o.booked_rate) }}</td>
          <td class="muted">{{ o.examples.slice(0, 2).map((e) => e.quote ? '“' + e.quote + '”' : e.detail_fi).filter(Boolean).join(' · ') }}</td>
        </tr>
      </table>
    </div>

    <div class="grid2">
      <div class="card">
        <h2>Estot</h2>
        <div v-if="!stats.blockers.length" class="muted small">Ei estoja jaksolla.</div>
        <div v-for="b in stats.blockers" :key="b.category" class="small">{{ BLOCKER_FI[b.category] ?? b.category }}: <strong>{{ b.calls }}</strong></div>
        <h2 style="margin-top: 1rem">Tunnelma</h2>
        <div v-for="s in stats.sentiment" :key="String(s.sentiment)" class="small">{{ s.sentiment ? SENTIMENT_FI[s.sentiment] : 'ei tiedossa' }}: <strong>{{ s.n }}</strong></div>
      </div>
      <div class="card">
        <h2>Mihin asti puhelu eteni</h2>
        <table class="small">
          <tr v-for="s in stats.stages" :key="String(s.stage)"><td>{{ s.stage ? STAGE_FI[s.stage] ?? s.stage : 'ei tiedossa' }}</td><td>{{ s.n }}</td><td class="muted">{{ s.booked }} bookattu</td></tr>
        </table>
        <h2 style="margin-top: 1rem">Kitkakohdat</h2>
        <div v-if="!stats.friction_samples.length" class="muted small">Ei kirjattuja kitkakohtia.</div>
        <div v-for="(f, i) in stats.friction_samples.slice(0, 8)" :key="i" class="small">• {{ f.moment_fi }}<span v-if="f.cause_fi" class="muted"> – {{ f.cause_fi }}</span> <strong v-if="f.n > 1">×{{ f.n }}</strong></div>
      </div>
    </div>
  </template>

  <div v-if="latest?.narrative" class="card" style="border-color: var(--accent)">
    <h2>{{ latest.narrative.headline_fi }}</h2>
    <p class="small muted">Miran yhteenveto · {{ latest.campaign_name ?? 'kaikki kampanjat' }} · {{ fmtDate(latest.period_start) }}–{{ fmtDate(latest.period_end) }} · {{ latest.analysed }} puhelua</p>
    <div v-if="latest.narrative.findings?.length"><h3>Havainnot</h3>
      <div v-for="(f, i) in latest.narrative.findings" :key="i" class="small" style="margin-bottom: 0.4rem"><span class="tag" :class="{ danger: f.impact === 'high', warn: f.impact === 'medium' }">{{ f.impact }}</span> <strong>{{ f.title_fi }}</strong> – {{ f.evidence_fi }}</div>
    </div>
    <div v-if="latest.narrative.recommendations?.length"><h3>Suositukset</h3>
      <div v-for="(r, i) in latest.narrative.recommendations" :key="i" class="small" style="margin-bottom: 0.4rem"><strong>{{ r.action_fi }}</strong> <span class="muted">({{ r.area }}) – {{ r.why_fi }}</span></div>
    </div>
    <div v-if="latest.narrative.script_changes?.length"><h3>Repliikit spiikkiin</h3>
      <div v-for="(s, i) in latest.narrative.script_changes" :key="i" class="script small" style="margin-bottom: 0.4rem"><strong>{{ s.objection_category }}:</strong> {{ s.suggested_reply_fi }}</div>
    </div>
    <p v-if="latest.narrative.data_gaps_fi?.length" class="small muted">Rajoitteet: {{ latest.narrative.data_gaps_fi.join(' · ') }}</p>
  </div>

  <div v-if="reports.length" class="card">
    <h2>Yhteenvedot</h2>
    <table class="small">
      <tr v-for="r in reports" :key="r.id">
        <td>{{ fmtDateTime(r.created_at) }}</td><td>{{ r.campaign_name ?? 'kaikki' }}</td><td>{{ r.analysed }} puhelua</td>
        <td><span class="tag" :class="{ ok: r.status === 'done', warn: r.status === 'pending' || r.status === 'running', danger: r.status === 'failed' }">{{ r.status }}</span></td>
        <td class="muted">{{ r.narrative?.headline_fi ?? r.error }}</td>
      </tr>
    </table>
  </div>
</template>
