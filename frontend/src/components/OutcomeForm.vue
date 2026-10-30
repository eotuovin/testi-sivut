<script setup lang="ts">
/** End of call: one click on the outcome, then the fields that outcome needs.
 *  Three groups so the caller never hunts: no lead / follow-up / lead. */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { CallLog, Contact, Outcome } from '../api/types'
import { OUTCOME_LABELS } from '../api/types'
import { apiPut, errorText } from '../api/client'
import BookingFields, { type BookingDraft, emptyBooking } from './BookingFields.vue'

const props = defineProps<{ taskId: string; contacts: Contact[]; contactId: string | null; phone: string | null; busy: boolean; initialNotes: string; recording?: boolean }>()
const consent = ref(false)
const emit = defineEmits<{ (e: 'submit', body: CallLog): void }>()

const GROUPS: { title: string; hint: string; items: Outcome[] }[] = [
  { title: 'Ei tavoitettu', hint: 'Jää jonoon ja yritetään uudelleen', items: ['no_answer', 'busy', 'voicemail', 'gatekeeper', 'wrong_number'] },
  { title: 'Jatko', hint: 'Sovittu aika, jolloin palataan', items: ['callback'] },
  { title: 'Päätös', hint: 'Käsitelty loppuun', items: ['not_interested', 'already_customer', 'do_not_call'] },
  { title: 'Liidi', hint: 'Tapaaminen sovittu → bookkaus', items: ['booked'] },
]
const outcome = ref<Outcome | null>(null)
/** Keyboard: 1–9, 0 pick an outcome in display order; Ctrl/⌘+Enter saves; Esc clears. */
const ORDER: Outcome[] = GROUPS.flatMap((g) => g.items)
const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0']
const keyFor = (o: Outcome) => KEYS[ORDER.indexOf(o)] ?? ''
function onKey(e: KeyboardEvent) {
  const t = e.target as HTMLElement | null
  const typing = !!t && (t.tagName === 'TEXTAREA' || t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.isContentEditable)
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); if (canSubmit.value && !props.busy) submit(); return }
  if (typing || e.ctrlKey || e.metaKey || e.altKey) return
  if (e.key === 'Escape') { outcome.value = null; return }
  const i = KEYS.indexOf(e.key)
  if (i >= 0 && ORDER[i]) { e.preventDefault(); pick(ORDER[i]) }
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
const notes = ref(props.initialNotes || '')
const savedAt = ref<Date | null>(null)
const saving = ref(false)
const callbackAt = ref(defaultCallback(24))
const booking = ref<BookingDraft>(emptyBooking(props.contacts.find((c) => c.id === props.contactId)?.email ?? null))
const addContact = ref(false)
const nc = ref({ name: '', title: '', phone: '', email: '' })
const error = ref('')

// Autosave notes while the call is on — a reload or a crash loses nothing.
let timer: number | undefined
watch(notes, () => {
  window.clearTimeout(timer)
  timer = window.setTimeout(saveDraft, 800)
})
async function saveDraft() {
  saving.value = true
  try {
    const r = await apiPut<{ saved_at: string }>(`/calls/tasks/${props.taskId}/draft`, { notes: notes.value })
    savedAt.value = new Date(r.saved_at)
  } catch (e) {
    error.value = errorText(e)
  } finally {
    saving.value = false
  }
}

function defaultCallback(hours: number, atHour?: number) {
  const d = new Date(Date.now() + hours * 3600 * 1000)
  if (atHour !== undefined) d.setHours(atHour, 0, 0, 0)
  else d.setMinutes(0, 0, 0)
  while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() + 1)
  return toLocalInput(d)
}
function toLocalInput(d: Date) {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}
const CALLBACK_QUICK = [
  { label: '1 h', value: () => defaultCallback(1) },
  { label: 'Tänään 15:00', value: () => defaultCallback(0, 15) },
  { label: 'Huomenna 10', value: () => defaultCallback(24, 10) },
  { label: '3 pv', value: () => defaultCallback(72, 10) },
  { label: 'Ensi viikko', value: () => defaultCallback(7 * 24, 10) },
  { label: '1 kk', value: () => defaultCallback(30 * 24, 10) },
]
function pick(o: Outcome) {
  outcome.value = o
  error.value = ''
  if (o === 'gatekeeper' || o === 'wrong_number') addContact.value = true
}
const canSubmit = computed(() => {
  if (!outcome.value) return false
  if (outcome.value === 'callback' && !callbackAt.value) return false
  if (outcome.value === 'booked' && !booking.value.scheduled_at) return false
  return true
})
function submit() {
  if (!outcome.value) return
  window.clearTimeout(timer)
  const body: CallLog = { outcome: outcome.value, notes: notes.value || null, contact_id: props.contactId, phone_dialed: props.phone, recording_consent: !!props.recording && consent.value }
  if (outcome.value === 'callback') body.callback_at = new Date(callbackAt.value).toISOString()
  if (outcome.value === 'booked') {
    const b = booking.value
    body.booking = {
      scheduled_at: new Date(b.scheduled_at).toISOString(),
      duration_minutes: b.duration_minutes,
      location: b.location || null,
      meeting_url: b.meeting_url || null,
      attendee_email: b.attendee_email || null,
      value_eur: b.value_eur,
      notes: b.notes || null,
    }
  }
  if (addContact.value && (nc.value.name || nc.value.phone || nc.value.email)) {
    body.new_contact_name = nc.value.name || null
    body.new_contact_title = nc.value.title || null
    body.new_contact_phone = nc.value.phone || null
    body.new_contact_email = nc.value.email || null
  }
  emit('submit', body)
}
defineExpose({ notes })
</script>

<template>
  <div>
    <div class="field">
      <label>
        Muistiinpanot puhelun aikana
        <span class="muted" style="float: right">{{ saving ? 'tallentuu…' : savedAt ? 'tallennettu ' + savedAt.toLocaleTimeString('fi-FI', { hour: '2-digit', minute: '2-digit' }) : 'tallentuu automaattisesti' }}</span>
      </label>
      <textarea v-model="notes" style="min-height: 120px" placeholder="Kirjoita sitä mukaa kun puhutte: mitä sanoi, mikä kiinnosti, kuka päättää, milloin kannattaa palata…" />
    </div>

    <h2>Miten puhelu päättyi? <span class="muted small" style="font-weight: 400">· näppäimet 1–0, Ctrl+Enter tallentaa</span></h2>
    <div v-for="g in GROUPS" :key="g.title" class="ogroup">
      <div class="ohead"><strong>{{ g.title }}</strong><span class="muted small"> · {{ g.hint }}</span></div>
      <div class="outcomes">
        <button v-for="o in g.items" :key="o" :class="{ selected: outcome === o, primary: o === 'booked', danger: o === 'do_not_call' && outcome === o, lead: o === 'booked' }" @click="pick(o)">
          <kbd>{{ keyFor(o) }}</kbd>{{ OUTCOME_LABELS[o] }}
        </button>
      </div>
    </div>

    <div v-if="outcome === 'callback'" class="card" style="margin-top: 0.75rem">
      <h3>Milloin soitetaan uudelleen?</h3>
      <div class="row" style="margin-bottom: 0.5rem">
        <button v-for="q in CALLBACK_QUICK" :key="q.label" class="small" :class="{ selected: callbackAt === q.value() }" @click="callbackAt = q.value()">{{ q.label }}</button>
      </div>
      <input v-model="callbackAt" type="datetime-local" />
      <p class="muted small" style="margin: 0.4rem 0 0">Tehtävä palaa sinun jonoosi tähän aikaan ja näkyy ”Omat takaisinsoitot” -listassa.</p>
    </div>

    <BookingFields v-if="outcome === 'booked'" v-model="booking" style="margin-top: 0.75rem" />

    <div class="field" style="margin-top: 0.75rem">
      <label><input type="checkbox" v-model="addContact" style="width: auto; margin-right: 0.4rem" />Opin uuden yhteyshenkilön tai numeron</label>
      <div v-if="addContact" class="grid2">
        <input v-model="nc.name" placeholder="Nimi" />
        <input v-model="nc.title" placeholder="Titteli" />
        <input v-model="nc.phone" placeholder="Puhelin" />
        <input v-model="nc.email" placeholder="Sähköposti" />
      </div>
    </div>

    <div v-if="recording" class="field">
      <label><input type="checkbox" v-model="consent" style="width: auto; margin-right: 0.4rem" />Kerroin asiakkaalle, että puhelu tallennetaan (muuten nauhoitetta ei käsitellä)</label>
    </div>
    <p v-if="error" class="error small">{{ error }}</p>
    <button class="primary big" style="width: 100%; justify-content: center" :disabled="!canSubmit || busy" @click="submit">
      {{ outcome === 'booked' ? 'Tallenna bookkaus ja seuraava →' : outcome === 'callback' ? 'Tallenna takaisinsoitto ja seuraava →' : 'Tallenna ja seuraava →' }}
    </button>
  </div>
</template>

<style scoped>
.ogroup { margin-bottom: 0.6rem; }
.ohead { margin-bottom: 0.3rem; font-size: 0.86rem; }
.outcomes { grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); }
.outcomes button.lead { grid-column: 1 / -1; padding: 0.9rem; font-size: 1rem; background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
.outcomes button.lead:hover { background: #A3B3FF; border-color: #A3B3FF; }
.outcomes kbd { font: inherit; font-size: 0.7rem; opacity: 0.6; border: 1px solid currentColor; border-radius: 4px; padding: 0 0.3rem; margin-right: 0.45rem; line-height: 1.3; }
.outcomes button.selected { outline: 0; border-color: var(--accent); background: var(--accent-soft); color: #FFFFFF; }
.outcomes button.primary.selected { color: var(--accent-ink); background: #FFFFFF; border-color: #FFFFFF; }
button.small.selected { outline: 2px solid var(--accent); }
</style>
