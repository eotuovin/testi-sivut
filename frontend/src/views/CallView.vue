<script setup lang="ts">
/** The calling screen. Everything about the customer is on one screen and
 *  editable while talking: left = customer (company + people), middle = the
 *  call (number, script, notes), right = how it ended (outcome, callback,
 *  booking). Nothing here navigates away mid-call. */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useCallsStore } from '../stores/calls'
import { apiGet, apiPatch, apiPost, errorText } from '../api/client'
import type { CallLog, Contact, ManagementLevel } from '../api/types'
import { LEVEL_LABELS, OUTCOME_LABELS, STATUS_LABELS } from '../api/types'
import OutcomeForm from '../components/OutcomeForm.vue'
import DialPanel from '../components/DialPanel.vue'
import CompanyLogo from '../components/CompanyLogo.vue'
import { useTelephonyStore } from '../stores/telephony'
import { useAuthStore } from '../stores/auth'
import { fmtDateTime } from '../format'

const store = useCallsStore()
const tel = useTelephonyStore()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const intel = ref<{ recording_enabled: boolean } | null>(null)
const error = ref('')
const busy = ref(false)
const selectedContactId = ref<string | null>(null)
const now = ref(Date.now())
const editCompany = ref(false)
const cf = ref({ name: '', website: '', city: '', industry_label: '', phone: '', email: '', street_address: '' })
const companyNotes = ref('')
const showAddContact = ref(false)
const nc = ref({ name: '', title: '', management_level: '' as ManagementLevel | '', phone: '', email: '' })
const editContactId = ref<string | null>(null)
const ec = ref({ name: '', title: '', management_level: '' as ManagementLevel | '', phone: '', email: '' })
let tick: number | undefined

onMounted(async () => {
  tick = window.setInterval(() => (now.value = Date.now()), 1000)
  try {
    await Promise.all([store.loadCampaigns(), store.loadCallbacks(), store.loadQueue(), tel.load()])
    intel.value = await apiGet<{ recording_enabled: boolean }>('/intelligence/status')
    if (typeof route.query.task === 'string') {
      await claim(route.query.task)
      router.replace({ query: {} })
    } else if (!store.task && !store.queueEmpty) await next()
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
/** Script with {{etunimi}} {{nimi}} {{yritys}} {{paikkakunta}} {{myyja}} {{tuote}} filled in for this call. */
const script = computed(() => {
  const t = store.task
  if (!t?.script) return ''
  const name = contact.value?.name ?? ''
  const vars: Record<string, string> = {
    etunimi: name.split(' ')[0] || '', nimi: name, yritys: t.company_name, paikkakunta: t.city ?? '', myyja: (auth.me?.name ?? '').split(' ')[0], tuote: t.product ?? '',
  }
  return t.script.replace(/\{\{(\w+)\}\}/g, (m, k) => (k in vars ? vars[k] || m : m))
})
const site = computed(() => store.task?.website ? (store.task.website.startsWith('http') ? store.task.website : 'https://' + store.task.website) : null)

async function next() {
  error.value = ''
  selectedContactId.value = null
  editCompany.value = false
  try {
    await store.next()
    companyNotes.value = store.task?.company_notes ?? ''
  } catch (e) {
    error.value = errorText(e)
  }
}
async function claim(taskId: string) {
  error.value = ''
  selectedContactId.value = null
  editCompany.value = false
  try {
    await store.claim(taskId)
    companyNotes.value = store.task?.company_notes ?? ''
    await store.loadCallbacks()
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

// ---- in-place edits while on the call: patch, then update the task in the store
function startEditCompany() {
  const t = store.task!
  cf.value = { name: t.company_name, website: t.website ?? '', city: t.city ?? '', industry_label: t.industry_label ?? '', phone: '', email: '', street_address: '' }
  editCompany.value = true
}
async function saveCompany() {
  const t = store.task
  if (!t) return
  try {
    const f = cf.value
    await apiPatch(`/companies/${t.company_id}`, { name: f.name, website: f.website || null, city: f.city || null, industry_label: f.industry_label || null, phone: f.phone || null, email: f.email || null, street_address: f.street_address || null })
    Object.assign(t, { company_name: f.name, website: f.website || null, city: f.city || null, industry_label: f.industry_label || null })
    editCompany.value = false
  } catch (e) { error.value = errorText(e) }
}
let notesTimer: number | undefined
function onCompanyNotes() {
  window.clearTimeout(notesTimer)
  notesTimer = window.setTimeout(async () => {
    if (!store.task) return
    await apiPatch(`/companies/${store.task.company_id}`, { notes: companyNotes.value })
    store.task.company_notes = companyNotes.value
  }, 800)
}
async function setStatus(status: string) {
  if (!store.task) return
  await apiPatch(`/companies/${store.task.company_id}`, { status })
  store.task.company_status = status
}
async function addContact() {
  const t = store.task
  if (!t) return
  try {
    const c = await apiPost<Contact>(`/companies/${t.company_id}/contacts`, { ...nc.value, management_level: nc.value.management_level || null, name: nc.value.name || null, title: nc.value.title || null, phone: nc.value.phone || null, email: nc.value.email || null })
    t.contacts.push(c)
    selectedContactId.value = c.id
    nc.value = { name: '', title: '', management_level: '', phone: '', email: '' }
    showAddContact.value = false
  } catch (e) { error.value = errorText(e) }
}
function startEditContact(c: Contact) {
  editContactId.value = c.id
  ec.value = { name: c.name ?? '', title: c.title ?? '', management_level: c.management_level ?? '', phone: c.phone ?? c.phone_e164 ?? '', email: c.email ?? '' }
}
async function saveContact() {
  const t = store.task
  if (!t || !editContactId.value) return
  try {
    const u = await apiPatch<Contact>(`/contacts/${editContactId.value}`, { name: ec.value.name || null, title: ec.value.title || null, management_level: ec.value.management_level || null, phone: ec.value.phone || null, email: ec.value.email || null })
    const i = t.contacts.findIndex((c) => c.id === u.id)
    if (i >= 0) t.contacts[i] = { ...t.contacts[i], ...u }
    editContactId.value = null
  } catch (e) { error.value = errorText(e) }
}
async function verify(c: Contact) {
  const u = await apiPatch<Contact>(`/contacts/${c.id}`, { verified: true })
  Object.assign(c, u)
}
</script>

<template>
  <div class="page-head">
    <div class="row">
      <h1 style="margin: 0">Soita</h1>
      <select :value="store.campaignId" @change="store.setCampaign(($event.target as HTMLSelectElement).value)" style="width: auto">
        <option value="">Kaikki aktiiviset kampanjat</option>
        <option v-for="c in store.activeCampaigns" :key="c.id" :value="c.id">{{ c.name }} ({{ c.open_tasks }} jonossa)</option>
      </select>
      <button v-if="!store.task" class="primary" :disabled="store.loading" @click="next">Anna seuraava →</button>
      <button v-else class="ghost" @click="release">Palauta jonoon</button>
      <span v-if="store.queue" class="small muted queue-info" :title="`${store.queue.waiting} odottaa omaa aikaansa · ${store.queue.in_progress} toisella soittajalla · ${store.queue.done} tehty`">
        <strong>{{ store.queue.due_now }}</strong> jonossa nyt
        <template v-if="store.queue.callbacks_due"> · <span :class="{ error: store.queue.my_callbacks_due > 0 }">{{ store.queue.callbacks_due }} takaisinsoittoa erääntynyt</span></template>
        <template v-if="store.queue.waiting"> · {{ store.queue.waiting }} odottaa</template>
      </span>
    </div>
    <div v-if="store.task" class="row small muted">
      <span class="tag">{{ store.task.campaign_name }}</span>
      <span>Soitettu {{ store.task.attempts }}/{{ store.task.max_attempts }}</span>
      <span v-if="store.task.last_outcome">· viimeksi {{ OUTCOME_LABELS[store.task.last_outcome as keyof typeof OUTCOME_LABELS] ?? store.task.last_outcome }}</span>
      <span v-if="elapsed && !tel.session" class="timer tag accent">⏱ {{ elapsed }}</span>
    </div>
  </div>
  <p v-if="error" class="error">{{ error }}</p>

  <div v-if="store.lastBooking" class="card" style="border-color: var(--ok)">
    <strong>Bookkaus tallennettu.</strong> {{ store.lastBooking.product }}
    <span v-if="store.lastBooking.scheduled_at">· {{ fmtDateTime(store.lastBooking.scheduled_at) }}</span>
    <router-link to="/bookkaukset" class="small" style="margin-left: 0.5rem">Kaikki bookkaukset →</router-link>
  </div>

  <div v-if="store.queueEmpty && !store.task" class="empty">
    Jono on tyhjä tältä erää. Lisää yrityksiä jonoon <router-link to="/haku">hausta</router-link> tai <router-link to="/listat">listalta</router-link>, tai odota takaisinsoittoja.
  </div>

  <div v-if="store.task" class="callgrid">
    <!-- ------------------------------------------------ customer -->
    <section>
      <div class="card">
        <div class="co" style="align-items: flex-start">
          <CompanyLogo :name="store.task.company_name" :website="store.task.website" />
          <div class="t" style="flex: 1">
            <template v-if="!editCompany">
              <strong style="font-size: 1.1rem; white-space: normal; max-width: none">{{ store.task.company_name }}</strong>
              <div class="sub">{{ store.task.industry_label || '—' }} · {{ store.task.city || '—' }}<span v-if="store.task.business_id"> · {{ store.task.business_id }}</span></div>
              <div class="sub"><a v-if="site" :href="site" target="_blank" rel="noopener">{{ store.task.website }}</a><router-link :to="'/yritykset/' + store.task.company_id" style="margin-left: 0.5rem">Koko profiili ↗</router-link></div>
            </template>
            <div v-else class="grid2" style="gap: 0.4rem">
              <input v-model="cf.name" placeholder="Nimi" style="grid-column: 1 / -1" />
              <input v-model="cf.industry_label" placeholder="Toimiala" /><input v-model="cf.city" placeholder="Paikkakunta" />
              <input v-model="cf.website" placeholder="Verkkosivu" /><input v-model="cf.phone" placeholder="Vaihde" />
              <input v-model="cf.email" placeholder="Yleinen sähköposti" /><input v-model="cf.street_address" placeholder="Katuosoite" />
              <div class="row" style="grid-column: 1 / -1"><button class="primary small" @click="saveCompany">Tallenna</button><button class="ghost small" @click="editCompany = false">Peruuta</button></div>
            </div>
          </div>
          <button v-if="!editCompany" class="ghost small" title="Muokkaa yrityksen tietoja" @click="startEditCompany">✎</button>
        </div>
        <div class="row" style="margin-top: 0.6rem">
          <label style="margin: 0">Tila</label>
          <select :value="store.task.company_status" style="width: auto" class="small" @change="setStatus(($event.target as HTMLSelectElement).value)">
            <option v-for="(l, k) in STATUS_LABELS" :key="k" :value="k">{{ l }}</option>
          </select>
        </div>
        <div class="field" style="margin-top: 0.6rem">
          <label>Asiakkaan muistiinpanot (pysyvät)</label>
          <textarea v-model="companyNotes" style="min-height: 70px" placeholder="Mitä tästä asiakkaasta kannattaa muistaa seuraavalla kerralla" @input="onCompanyNotes" />
        </div>
      </div>

      <div class="card">
        <div class="row" style="justify-content: space-between"><h2 style="margin: 0">Henkilöt</h2><button class="ghost small" @click="showAddContact = !showAddContact">+ Lisää</button></div>
        <div v-if="showAddContact" class="grid2" style="gap: 0.4rem; margin: 0.5rem 0">
          <input v-model="nc.name" placeholder="Nimi" /><input v-model="nc.title" placeholder="Titteli" />
          <select v-model="nc.management_level"><option value="">Taso</option><option v-for="(l, k) in LEVEL_LABELS" :key="k" :value="k">{{ l }}</option></select>
          <input v-model="nc.phone" placeholder="Puhelin" /><input v-model="nc.email" placeholder="Sähköposti" style="grid-column: 1 / -1" />
          <div class="row" style="grid-column: 1 / -1"><button class="primary small" :disabled="!nc.name && !nc.phone" @click="addContact">Tallenna</button><button class="ghost small" @click="showAddContact = false">Peruuta</button></div>
        </div>
        <div v-if="!store.task.contacts.length" class="error small">Yrityksellä ei ole yhteystietoja — lisää numero yllä.</div>
        <div v-for="c in store.task.contacts" :key="c.id" class="person" :class="{ on: contact?.id === c.id, dnc: c.do_not_call }" @click="!c.do_not_call && (selectedContactId = c.id)">
          <template v-if="editContactId !== c.id">
            <div style="flex: 1; min-width: 0">
              <strong>{{ c.name || 'Vaihde / yleinen numero' }}</strong><span v-if="c.verified_at" class="tag ok" style="margin-left: 0.3rem">✓</span>
              <div class="small muted">{{ c.title || '' }}<span v-if="c.management_level"> · {{ LEVEL_LABELS[c.management_level] }}</span><span v-if="c.confidence !== null"> · {{ Math.round(Number(c.confidence) * 100) }} %</span></div>
              <div class="small">{{ c.phone_e164 || '—' }}<span v-if="c.email"> · {{ c.email }}</span><span v-if="c.do_not_call" class="tag danger" style="margin-left: 0.3rem">ei saa soittaa</span></div>
            </div>
            <button class="ghost small" title="Muokkaa" @click.stop="startEditContact(c)">✎</button>
          </template>
          <div v-else class="grid2" style="gap: 0.4rem; width: 100%" @click.stop>
            <input v-model="ec.name" placeholder="Nimi" /><input v-model="ec.title" placeholder="Titteli" />
            <select v-model="ec.management_level"><option value="">Taso</option><option v-for="(l, k) in LEVEL_LABELS" :key="k" :value="k">{{ l }}</option></select>
            <input v-model="ec.phone" placeholder="Puhelin" /><input v-model="ec.email" placeholder="Sähköposti" style="grid-column: 1 / -1" />
            <div class="row" style="grid-column: 1 / -1"><button class="primary small" @click="saveContact">Tallenna</button><button class="ghost small" @click="editContactId = null">Peruuta</button></div>
          </div>
        </div>
      </div>

      <div v-if="store.task.history.length" class="card">
        <h2>Aiemmat soitot</h2>
        <ul class="timeline small">
          <li v-for="h in store.task.history" :key="h.started_at">
            <div class="when">{{ fmtDateTime(h.started_at) }}</div>
            <div><strong>{{ OUTCOME_LABELS[h.outcome as keyof typeof OUTCOME_LABELS] ?? h.outcome }}</strong> <span class="muted">· {{ h.user_name }}</span><div v-if="h.notes" class="muted">{{ h.notes }}</div></div>
          </li>
        </ul>
      </div>
    </section>

    <!-- ------------------------------------------------ the call -->
    <section>
      <div class="card dialcard">
        <div v-if="contact">
          <div class="muted small">{{ contact.name || 'Vaihde / yleinen numero' }}<span v-if="contact.title"> · {{ contact.title }}</span></div>
          <a v-if="dialHref" :href="dialHref" class="phone" @click="store.startTimer()">📞 {{ contact.phone_e164 }}</a>
          <div v-else class="error">Ei puhelinnumeroa — lisää numero henkilölle tai valitse toinen.</div>
          <div v-if="contact.email" class="small"><a :href="'mailto:' + contact.email">{{ contact.email }}</a></div>
          <div class="row" style="margin-top: 0.5rem">
            <button v-if="dialHref && !contact.verified_at" class="small" @click="verify(contact)">✓ Numero toimi</button>
          </div>
          <DialPanel :task-id="store.task.id" :company-id="store.task.company_id" :contact-id="contact.id" :phone="contact.phone_e164" style="margin-top: 0.75rem" />
        </div>
        <div v-else class="error">Valitse tai lisää henkilö vasemmalta.</div>
      </div>
      <div v-if="store.task.recording_notice && intel?.recording_enabled" class="card small" style="border-color: var(--warn)">
        <strong>Kerro heti alussa:</strong> {{ store.task.recording_notice }}
      </div>
      <div v-if="store.task.script" class="card">
        <h2>Spiikki · {{ store.task.product }}</h2>
        <div class="script">{{ script }}</div>
      </div>
    </section>

    <!-- ------------------------------------------------ outcome -->
    <section>
      <div class="card">
        <OutcomeForm :key="store.task.id" :task-id="store.task.id" :initial-notes="store.task.notes_draft ?? ''" :contacts="store.task.contacts" :contact-id="contact?.id ?? null" :phone="contact?.phone_e164 ?? null" :busy="busy" :recording="!!intel?.recording_enabled && !!tel.session" @submit="submit" />
      </div>
    </section>
  </div>

  <div v-if="store.callbacks.length" class="card">
    <h2>Omat takaisinsoitot</h2>
    <table class="small">
      <tr><th>Aika</th><th>Yritys</th><th>Henkilö</th><th>Kampanja</th></tr>
      <tr v-for="c in store.callbacks" :key="c.task_id" class="clickable" :class="{ warn: new Date(c.due_at).getTime() < now }" title="Avaa tämä puhelu nyt" @click="claim(c.task_id)">
        <td :class="{ error: new Date(c.due_at).getTime() < now }">{{ fmtDateTime(c.due_at) }}<span v-if="new Date(c.due_at).getTime() < now" class="tag danger" style="margin-left: 0.3rem">erääntynyt</span></td>
        <td><strong>{{ c.company_name }}</strong> <router-link :to="'/yritykset/' + c.company_id" class="small" @click.stop>profiili</router-link></td>
        <td>{{ c.contact_name || '' }} {{ c.phone || '' }}</td>
        <td>{{ c.campaign_name }} <button class="small" style="margin-left: 0.4rem" @click.stop="claim(c.task_id)">Soita nyt →</button></td>
      </tr>
    </table>
  </div>
</template>

<style scoped>
.callgrid { display: grid; grid-template-columns: 1fr 1fr 1.1fr; gap: 1rem; align-items: start; }
.person { display: flex; gap: 0.5rem; align-items: flex-start; padding: 0.5rem 0.6rem; border: 1px solid var(--line); border-radius: 7px; margin-top: 0.4rem; cursor: pointer; }
.person.on { border-color: var(--accent); background: var(--accent-soft); }
.person.dnc { opacity: 0.55; cursor: not-allowed; }
.dialcard { background: var(--surface-2); }
@media (max-width: 1200px) { .callgrid { grid-template-columns: 1fr 1fr; } .callgrid > section:last-child { grid-column: 1 / -1; } }
@media (max-width: 800px) { .callgrid { grid-template-columns: 1fr; } }
</style>
