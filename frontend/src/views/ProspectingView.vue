<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { apiGet, apiPost, errorText } from '../api/client'
import type { Campaign, Prospect, ProspectingRun } from '../api/types'
import { fmtDateTime } from '../format'

const runs = ref<ProspectingRun[]>([])
const campaigns = ref<Campaign[]>([])
const prospects = ref<Prospect[]>([])
const activeRun = ref<string | null>(null)
const error = ref('')
const selected = ref<Set<string>>(new Set())
const enqueueCampaign = ref('')
const form = ref({ campaign_id: '', location: 'Jyväskylä', industry: '', name: '', company_form: '', max_results: 50, enrich: true })
let poll: number | undefined

const pendingRuns = computed(() => runs.value.filter((r) => r.status === 'queued' || r.status === 'running'))

async function load() {
  try {
    runs.value = await apiGet<ProspectingRun[]>('/prospecting/runs')
    if (activeRun.value) prospects.value = await apiGet<Prospect[]>('/prospecting/prospects', { run_id: activeRun.value })
  } catch (e) {
    error.value = errorText(e)
  }
}
onMounted(async () => {
  campaigns.value = (await apiGet<Campaign[]>('/campaigns')).filter((c) => c.status === 'active')
  await load()
  poll = window.setInterval(() => { if (pendingRuns.value.length) load() }, 4000)
})
onBeforeUnmount(() => window.clearInterval(poll))

async function startRun() {
  error.value = ''
  try {
    const body: Record<string, unknown> = { max_results: form.value.max_results, enrich: form.value.enrich }
    for (const k of ['campaign_id', 'location', 'industry', 'name', 'company_form'] as const) if (form.value[k]) body[k] = form.value[k]
    const r = await apiPost<ProspectingRun>('/prospecting/runs', body)
    activeRun.value = r.id
    await load()
  } catch (e) {
    error.value = errorText(e)
  }
}
async function openRun(id: string) {
  activeRun.value = id
  selected.value = new Set()
  const run = runs.value.find((r) => r.id === id)
  enqueueCampaign.value = run?.campaign_id ?? ''
  await load()
}
function toggle(id: string) {
  const s = new Set(selected.value)
  s.has(id) ? s.delete(id) : s.add(id)
  selected.value = s
}
function selectAllWithPhone() {
  selected.value = new Set(prospects.value.filter((p) => hasPhone(p)).map((p) => p.id))
}
function hasPhone(p: Prospect) {
  return p.found_contacts.some((c) => c.phone) || (p.data.enrichment?.phones?.length ?? 0) > 0
}
async function review(approve: boolean) {
  if (!selected.value.size) return
  error.value = ''
  try {
    const ids = [...selected.value]
    await apiPost('/prospecting/review', approve ? { approve: ids, enqueue_campaign_id: enqueueCampaign.value || null } : { reject: ids })
    selected.value = new Set()
    await load()
  } catch (e) {
    error.value = errorText(e)
  }
}
function bestContact(p: Prospect) {
  return p.found_contacts.find((c) => c.phone) ?? p.found_contacts[0] ?? null
}
</script>

<template>
  <h1>Prospektointi</h1>
  <p class="muted small">Agentti hakee yritykset PRH:n avoimesta datasta, lukee niiden verkkosivut ja ehdottaa päättäjän yhteystiedot. Mitään ei soiteta ennen kuin ihminen hyväksyy.</p>
  <p v-if="error" class="error">{{ error }}</p>

  <div class="card">
    <h2>Uusi haku</h2>
    <div class="grid2">
      <div class="field"><label>Paikkakunta</label><input v-model="form.location" placeholder="esim. Jyväskylä" /></div>
      <div class="field"><label>Toimiala (TOL-koodi tai sana)</label><input v-model="form.industry" placeholder="esim. 62010 tai 'ravintola'" /></div>
      <div class="field"><label>Nimi sisältää</label><input v-model="form.name" /></div>
      <div class="field"><label>Yhtiömuoto</label>
        <select v-model="form.company_form"><option value="">Kaikki</option><option>OY</option><option>OYJ</option><option>KY</option><option>AY</option><option>TMI</option></select>
      </div>
      <div class="field"><label>Kampanja (jonoon hyväksynnän jälkeen)</label>
        <select v-model="form.campaign_id"><option value="">—</option><option v-for="c in campaigns" :key="c.id" :value="c.id">{{ c.name }}</option></select>
      </div>
      <div class="field"><label>Max tuloksia</label><input v-model.number="form.max_results" type="number" min="1" max="500" /></div>
    </div>
    <label><input type="checkbox" v-model="form.enrich" style="width: auto; margin-right: 0.4rem" />Lue verkkosivut ja etsi yhteystiedot (hitaampi, mutta löytää numerot)</label>
    <button class="primary" style="margin-top: 0.5rem" @click="startRun">Käynnistä haku</button>
  </div>

  <div class="grid2">
    <div class="card">
      <h2>Haut</h2>
      <div v-if="!runs.length" class="muted small">Ei hakuja vielä.</div>
      <table v-else class="small">
        <tr><th>Aika</th><th>Kriteerit</th><th>Tila</th><th>Uusia</th><th>Odottaa</th></tr>
        <tr v-for="r in runs" :key="r.id" class="clickable" :style="r.id === activeRun ? 'font-weight:600' : ''" @click="openRun(r.id)">
          <td>{{ fmtDateTime(r.created_at) }}</td>
          <td>{{ Object.entries(r.criteria).filter(([k]) => !['max_results', 'enrich'].includes(k)).map(([, v]) => v).join(' · ') }}</td>
          <td><span class="tag" :class="{ ok: r.status === 'done', warn: r.status === 'running', danger: r.status === 'failed' }">{{ r.status }}</span><div v-if="r.error" class="error">{{ r.error }}</div></td>
          <td>{{ r.stats?.new ?? '—' }}<span v-if="r.stats?.register_total" class="muted"> / {{ r.stats.register_total }} rek.</span></td>
          <td>{{ r.pending }}</td>
        </tr>
      </table>
    </div>

    <div class="card" v-if="activeRun">
      <div class="row" style="justify-content: space-between">
        <h2>Tarkistettavat ({{ prospects.length }})</h2>
        <button class="small" @click="selectAllWithPhone">Valitse kaikki joilla numero</button>
      </div>
      <div v-if="!prospects.length" class="muted small">Ei odottavia prospekteja tässä haussa.</div>
      <div v-for="p in prospects" :key="p.id" class="card" style="padding: 0.6rem 0.8rem">
        <div class="row" style="justify-content: space-between">
          <label style="margin: 0; color: inherit"><input type="checkbox" :checked="selected.has(p.id)" style="width: auto; margin-right: 0.4rem" @change="toggle(p.id)" /><strong>{{ p.name }}</strong></label>
          <span v-if="p.score !== null" class="tag" :class="{ ok: p.score >= 0.6 }">sopivuus {{ Math.round(p.score * 100) }}%</span>
        </div>
        <div class="small muted">{{ p.data.register?.industry_label }} · {{ p.data.register?.city }} · {{ p.business_id }}
          <a v-if="p.data.register?.website" :href="'https://' + String(p.data.register.website).replace(/^https?:\/\//, '')" target="_blank" rel="noopener"> · {{ p.data.register.website }}</a>
        </div>
        <div v-if="p.data.enrichment?.summary" class="small">{{ p.data.enrichment.summary }}</div>
        <div v-if="p.data.enrichment?.fit_reason" class="small muted">{{ p.data.enrichment.fit_reason }}</div>
        <div v-if="bestContact(p)" class="small">
          👤 {{ bestContact(p)!.name || 'yleinen numero' }}<span v-if="bestContact(p)!.title"> · {{ bestContact(p)!.title }}</span>
          <span v-if="bestContact(p)!.phone"> · {{ bestContact(p)!.phone }}</span><span v-if="bestContact(p)!.email"> · {{ bestContact(p)!.email }}</span>
          <span v-if="p.found_contacts.length > 1" class="muted"> (+{{ p.found_contacts.length - 1 }})</span>
        </div>
        <div v-else class="small error">Ei yhteystietoja löytynyt — hyväksy vain jos lisäät numeron käsin.<span v-if="p.data.enrichment?.fetch_errors?.length" class="muted"> Sivua ei saatu haettua: {{ p.data.enrichment.fetch_errors[0] }}</span></div>
      </div>
      <div v-if="prospects.length" class="row" style="margin-top: 0.5rem">
        <select v-model="enqueueCampaign" style="width: auto"><option value="">Älä lisää jonoon</option><option v-for="c in campaigns" :key="c.id" :value="c.id">Jonoon: {{ c.name }}</option></select>
        <button class="primary" :disabled="!selected.size" @click="review(true)">Hyväksy {{ selected.size }}</button>
        <button :disabled="!selected.size" @click="review(false)">Hylkää {{ selected.size }}</button>
      </div>
    </div>
  </div>
</template>
