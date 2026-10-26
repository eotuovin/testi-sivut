<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useCallsStore } from '../stores/calls'
import { apiGet, errorText } from '../api/client'
import type { CallLog, Contact } from '../api/types'
import { OUTCOME_LABELS } from '../api/types'
import OutcomeForm from '../components/OutcomeForm.vue'
import DialPanel from '../components/DialPanel.vue'
import { useTelephonyStore } from '../stores/telephony'
import { fmtDateTime } from '../format'

const store = useCallsStore()
const tel = useTelephonyStore()
const intel = ref<{ recording_enabled: boolean } | null>(null)
const error = ref('')
const busy = ref(false)
const selectedContactId = ref<string | null>(null)
const now = ref(Date.now())
let tick: number | undefined

onMounted(async () => {
  tick = window.setInterval(() => (now.value = Date.now()), 1000)
  try {
    await Promise.all([store.loadCampaigns(), store.loadCallbacks(), tel.load()])
    intel.value = await apiGet<{ recording_enabled: boolean }>('/intelligence/status')
  } catch (e) {
    error.value = errorText(e)
  }
})
onBeforeUnmount(() => window.clearInterval(tick))

const contact = computed<Contact | null>(() => {
  if (!store.task) return null
  const id = selectedContactId.value ?? store.task.contact_id
  return store.task.contacts.find((c) => c.id === id) ?? store.task.contacts[0] ?? null
})
const dialHref = computed(() => (contact.value?.phone_e164 ? `tel:${contact.value.phone_e164}` : null))
const elapsed = computed(() => {
  if (!store.callStartedAt) return null
  const s = Math.floor((now.value - store.callStartedAt) / 1000)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
})

async function next() {
  error.value = ''
  selectedContactId.value = null
  try {
    await store.next()
  } catch (e) {
    error.value = errorText(e)
  }
}
async function submit(body: CallLog) {
  busy.value = true
  error.value = ''
  try {
    await store.log({ ...body, contact_id: contact.value?.id ?? null, phone_dialed: contact.value?.phone_e164 ?? null, session_id: tel.session?.id ?? undefined })
    tel.clear()
    await next()
  } catch (e) {
    error.value = errorText(e)
  } finally {
    busy.value = false
  }
}
async function release() {
  tel.clear()
  await store.release()
}
</script>

<template>
  <h1>Soita</h1>
  <div class="row" style="margin-bottom: 1rem">
    <select :value="store.campaignId" @change="store.setCampaign(($event.target as HTMLSelectElement).value)" style="width: auto">
      <option value="">Kaikki aktiiviset kampanjat</option>
      <option v-for="c in store.activeCampaigns" :key="c.id" :value="c.id">{{ c.name }} ({{ c.open_tasks }} jonossa)</option>
    </select>
    <button v-if="!store.task" class="primary big" :disabled="store.loading" @click="next">Anna seuraava →</button>
    <button v-else @click="release">Palauta jonoon</button>
  </div>
  <p v-if="error" class="error">{{ error }}</p>

  <div v-if="store.lastBooking" class="card" style="border-color: var(--ok)">
    <strong>Bookkaus tallennettu.</strong> {{ store.lastBooking.product }}
    <span v-if="store.lastBooking.scheduled_at">· {{ fmtDateTime(store.lastBooking.scheduled_at) }}</span>
  </div>

  <div v-if="store.queueEmpty && !store.task" class="empty">
    Jono on tyhjä tältä erää. Seuraavat soitot tulevat jonoon kun niiden aika koittaa tai kun prospekteja hyväksytään.
  </div>

  <div v-if="store.task" class="grid2">
    <div>
      <div class="card">
        <div class="row" style="justify-content: space-between">
          <h2 style="margin: 0">{{ store.task.company_name }}</h2>
          <span class="tag">{{ store.task.campaign_name }}</span>
        </div>
        <p class="muted small">
          {{ store.task.industry_label || '—' }} · {{ store.task.city || '—' }}
          <span v-if="store.task.business_id"> · {{ store.task.business_id }}</span>
          <a v-if="store.task.website" :href="store.task.website.startsWith('http') ? store.task.website : 'https://' + store.task.website" target="_blank" rel="noopener"> · {{ store.task.website }}</a>
        </p>
        <p v-if="store.task.company_notes" class="small">{{ store.task.company_notes }}</p>
        <p class="small muted">Soitettu {{ store.task.attempts }}/{{ store.task.max_attempts }} kertaa<span v-if="store.task.last_outcome"> · viimeksi: {{ OUTCOME_LABELS[store.task.last_outcome as keyof typeof OUTCOME_LABELS] ?? store.task.last_outcome }}</span></p>

        <div v-if="contact" style="margin: 1rem 0">
          <div class="muted small">{{ contact.name || 'Vaihde / yleinen numero' }}<span v-if="contact.title"> · {{ contact.title }}</span><span v-if="contact.confidence !== null"> · luotettavuus {{ Math.round(contact.confidence * 100) }}%</span></div>
          <a v-if="dialHref" :href="dialHref" class="phone" @click="store.startTimer()">📞 {{ contact.phone_e164 }}</a>
          <div v-else class="error">Ei puhelinnumeroa — lisää numero alla tai ohita.</div>
          <div v-if="contact.email" class="small"><a :href="'mailto:' + contact.email">{{ contact.email }}</a></div>
          <div v-if="elapsed && !tel.session" class="timer muted small">Puhelu käynnissä {{ elapsed }}</div>
          <DialPanel :task-id="store.task.id" :company-id="store.task.company_id" :contact-id="contact.id" :phone="contact.phone_e164" style="margin-top: 0.75rem" />
        </div>
        <div v-else class="error">Yrityksellä ei ole yhteystietoja.</div>

        <div v-if="store.task.contacts.length > 1" class="small">
          <label>Muut yhteyshenkilöt</label>
          <div v-for="c in store.task.contacts" :key="c.id">
            <button class="small" :disabled="c.do_not_call" @click="selectedContactId = c.id">{{ c.name || c.phone || c.email }}<span v-if="c.title"> · {{ c.title }}</span><span v-if="c.do_not_call"> · ei saa soittaa</span></button>
          </div>
        </div>
      </div>

      <div v-if="store.task.recording_notice && intel?.recording_enabled" class="card small" style="border-color: var(--warn)">
        <strong>Kerro heti alussa:</strong> {{ store.task.recording_notice }}
      </div>
      <div v-if="store.task.script" class="card">
        <h2>Spiikki · {{ store.task.product }}</h2>
        <div class="script">{{ store.task.script }}</div>
      </div>

      <div v-if="store.task.history.length" class="card">
        <h2>Aiemmat soitot</h2>
        <table class="small">
          <tr v-for="h in store.task.history" :key="h.started_at">
            <td>{{ fmtDateTime(h.started_at) }}</td>
            <td>{{ OUTCOME_LABELS[h.outcome as keyof typeof OUTCOME_LABELS] ?? h.outcome }}</td>
            <td>{{ h.user_name }}</td>
            <td class="muted">{{ h.notes }}</td>
          </tr>
        </table>
      </div>
    </div>

    <div class="card">
      <OutcomeForm :key="store.task.id" :task-id="store.task.id" :initial-notes="store.task.notes_draft ?? ''" :contacts="store.task.contacts" :contact-id="contact?.id ?? null" :phone="contact?.phone_e164 ?? null" :busy="busy" :recording="!!intel?.recording_enabled && !!tel.session" @submit="submit" />
    </div>
  </div>

  <div v-if="store.callbacks.length" class="card">
    <h2>Omat takaisinsoitot</h2>
    <table class="small">
      <tr><th>Aika</th><th>Yritys</th><th>Henkilö</th><th>Kampanja</th></tr>
      <tr v-for="c in store.callbacks" :key="c.task_id" :class="{ warn: new Date(c.due_at).getTime() < now }">
        <td>{{ fmtDateTime(c.due_at) }}</td>
        <td><router-link :to="'/yritykset/' + c.company_id">{{ c.company_name }}</router-link></td>
        <td>{{ c.contact_name || '' }} {{ c.phone || '' }}</td>
        <td>{{ c.campaign_name }}</td>
      </tr>
    </table>
  </div>
</template>
