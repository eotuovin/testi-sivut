<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { apiDelete, apiGet, apiPatch, apiPost, errorText } from '../api/client'
import type { IntegrationTarget, OutboxEvent } from '../api/types'
import { fmtDateTime } from '../format'

const targets = ref<IntegrationTarget[]>([])
const events = ref<OutboxEvent[]>([])
const catalog = ref<{ kinds: string[]; event_types: string[] }>({ kinds: [], event_types: [] })
const error = ref('')
const form = ref({ kind: 'webhook', name: '', url: '', secret_env: '', base_url: '', path: '', event_types: '*' })
const deliveries = ref<Record<string, unknown>[]>([])
const openTarget = ref<string | null>(null)

const KIND_HELP: Record<string, string> = {
  webhook: 'Yleinen allekirjoitettu JSON POST mihin tahansa URL:iin (X-Luuri-Signature). Salaisuus env-muuttujassa.',
  movingfirm_internal: 'Vie bookkaukset movingfirm-backendin sisäiseen API:in (MOVINGFIRM_BACKEND_URL + INTERNAL token envistä).',
  twenty: 'Peilaa yritykset ja bookkaukset Twenty CRM:ään (TWENTY_API_URL + avain envistä).',
  analytics: 'Kirjaa myyntitapahtumat olemassa olevaan ux_events-trackeriin (ANALYTICS_UX_EVENTS_URL).',
}

async function load() {
  try {
    ;[targets.value, events.value, catalog.value] = await Promise.all([
      apiGet<IntegrationTarget[]>('/integrations/targets'),
      apiGet<OutboxEvent[]>('/integrations/events', { limit: 50 }),
      apiGet<{ kinds: string[]; event_types: string[] }>('/integrations/catalog'),
    ])
  } catch (e) {
    error.value = errorText(e)
  }
}
onMounted(load)

async function create() {
  error.value = ''
  const config: Record<string, string> = {}
  for (const k of ['url', 'secret_env', 'base_url', 'path'] as const) if (form.value[k]) config[k] = form.value[k]
  try {
    await apiPost('/integrations/targets', {
      kind: form.value.kind, name: form.value.name, config,
      event_types: form.value.event_types.split(',').map((s) => s.trim()).filter(Boolean),
    })
    form.value = { kind: 'webhook', name: '', url: '', secret_env: '', base_url: '', path: '', event_types: '*' }
    await load()
  } catch (e) {
    error.value = errorText(e)
  }
}
async function toggle(t: IntegrationTarget) {
  await apiPatch(`/integrations/targets/${t.id}`, { enabled: !t.enabled })
  await load()
}
async function remove(t: IntegrationTarget) {
  if (!confirm(`Poistetaanko ${t.name}?`)) return
  await apiDelete(`/integrations/targets/${t.id}`)
  await load()
}
async function showDeliveries(t: IntegrationTarget) {
  openTarget.value = t.id
  deliveries.value = await apiGet(`/integrations/targets/${t.id}/deliveries`)
}
async function retry(e: OutboxEvent) {
  await apiPost(`/integrations/events/${e.id}/retry`)
  await load()
}
</script>

<template>
  <h1>Integraatiot</h1>
  <p class="muted small">Jokainen muutos (yritys, soitto, bookkaus…) kirjataan outboxiin ja toimitetaan kaikille päällä oleville kohteille. Salaisuudet eivät koskaan mene tietokantaan — viittaa env-muuttujaan.</p>
  <p v-if="error" class="error">{{ error }}</p>

  <div class="card">
    <h2>Uusi kohde</h2>
    <div class="grid2">
      <div class="field"><label>Tyyppi</label>
        <select v-model="form.kind"><option v-for="k in catalog.kinds" :key="k" :value="k">{{ k }}</option></select>
        <div class="small muted">{{ KIND_HELP[form.kind] }}</div>
      </div>
      <div class="field"><label>Nimi</label><input v-model="form.name" placeholder="esim. CRM-webhook" /></div>
      <div v-if="form.kind === 'webhook' || form.kind === 'analytics'" class="field"><label>URL</label><input v-model="form.url" placeholder="https://…" /></div>
      <div v-if="form.kind === 'movingfirm_internal' || form.kind === 'twenty'" class="field"><label>Base URL (tyhjä = env)</label><input v-model="form.base_url" /></div>
      <div v-if="form.kind === 'movingfirm_internal'" class="field"><label>Polku</label><input v-model="form.path" placeholder="/api/internal/crm/sales-bookings" /></div>
      <div class="field"><label>Salaisuuden env-muuttuja (tyhjä = oletus)</label><input v-model="form.secret_env" placeholder="esim. CRM_WEBHOOK_SECRET" /></div>
      <div class="field"><label>Tapahtumat (pilkuilla; * = kaikki, booking.* = kaikki bookkaukset)</label><input v-model="form.event_types" /><div class="small muted">{{ catalog.event_types.join(', ') }}</div></div>
    </div>
    <button class="primary" :disabled="!form.name" @click="create">Lisää</button>
  </div>

  <div class="card">
    <h2>Kohteet</h2>
    <div v-if="!targets.length" class="muted small">Ei kohteita vielä. Tapahtumat jäävät outboxiin ja lähtevät kun kohde lisätään.</div>
    <table v-else class="small">
      <tr><th>Nimi</th><th>Tyyppi</th><th>Tapahtumat</th><th>Päällä</th><th>Viimeisin ok</th><th>Epäonnistuneita</th><th></th></tr>
      <tr v-for="t in targets" :key="t.id">
        <td><strong>{{ t.name }}</strong><div class="muted">{{ JSON.stringify(t.config) }}</div></td>
        <td>{{ t.kind }}</td><td>{{ t.event_types.join(', ') }}</td>
        <td><span class="tag" :class="t.enabled ? 'ok' : ''">{{ t.enabled ? 'kyllä' : 'ei' }}</span></td>
        <td>{{ t.last_ok_at ? fmtDateTime(t.last_ok_at) : 'ei vielä' }}</td>
        <td><span v-if="t.failed" class="tag danger">{{ t.failed }}</span><span v-else>0</span></td>
        <td class="row"><button class="small" @click="toggle(t)">{{ t.enabled ? 'Pois' : 'Päälle' }}</button><button class="small" @click="showDeliveries(t)">Toimitukset</button><button class="small danger" @click="remove(t)">Poista</button></td>
      </tr>
    </table>
    <div v-if="openTarget" style="margin-top: 0.75rem">
      <h3>Toimitukset</h3>
      <div v-if="!deliveries.length" class="muted small">Ei toimituksia vielä.</div>
      <table v-else class="small">
        <tr v-for="d in deliveries" :key="String(d.id)">
          <td>{{ fmtDateTime(String(d.updated_at)) }}</td><td>{{ d.event_type }}</td>
          <td><span class="tag" :class="d.status === 'ok' ? 'ok' : 'danger'">{{ d.status }}</span> {{ d.response_code ?? '' }}</td>
          <td class="muted">{{ d.last_error || d.response_body }}</td>
        </tr>
      </table>
    </div>
  </div>

  <div class="card">
    <h2>Viimeisimmät tapahtumat</h2>
    <table class="small">
      <tr><th>Aika</th><th>Tapahtuma</th><th>Tila</th><th>Yrityksiä</th><th>Virhe</th><th></th></tr>
      <tr v-for="e in events" :key="e.id">
        <td>{{ fmtDateTime(e.created_at) }}</td><td>{{ e.event_type }}</td>
        <td><span class="tag" :class="{ ok: e.status === 'delivered', danger: e.status === 'dead', warn: e.status === 'pending' }">{{ e.status }}</span></td>
        <td>{{ e.attempts }}</td><td class="muted">{{ e.last_error }}</td>
        <td><button v-if="e.status === 'dead'" class="small" @click="retry(e)">Yritä uudelleen</button></td>
      </tr>
    </table>
  </div>
</template>
