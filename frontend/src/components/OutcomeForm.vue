<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { CallLog, Contact, Outcome } from '../api/types'
import { OUTCOME_LABELS } from '../api/types'
import { apiPut, errorText } from '../api/client'
import BookingFields, { type BookingDraft, emptyBooking } from './BookingFields.vue'

const props = defineProps<{ taskId: string; contacts: Contact[]; contactId: string | null; phone: string | null; busy: boolean; initialNotes: string; recording?: boolean }>()
const consent = ref(false)
const emit = defineEmits<{ (e: 'submit', body: CallLog): void }>()

const ORDER: Outcome[] = ['no_answer', 'busy', 'voicemail', 'gatekeeper', 'callback', 'not_interested', 'already_customer', 'wrong_number', 'do_not_call', 'booked']
const outcome = ref<Outcome | null>(null)
const notes = ref(props.initialNotes || '')
const savedAt = ref<Date | null>(null)
const saving = ref(false)
const callbackAt = ref(defaultCallback())
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

function defaultCallback() {
  const d = new Date(Date.now() + 24 * 3600 * 1000)
  d.setMinutes(0, 0, 0)
  return toLocalInput(d)
}
function toLocalInput(d: Date) {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}
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
</script>

<template>
  <div>
    <div class="field">
      <label>
        Muistiinpanot puhelun aikana
        <span class="muted" style="float: right">{{ saving ? 'tallennetaan…' : savedAt ? 'tallennettu ' + savedAt.toLocaleTimeString('fi-FI', { hour: '2-digit', minute: '2-digit' }) : 'tallentuu automaattisesti' }}</span>
      </label>
      <textarea v-model="notes" style="min-height: 140px" placeholder="Kirjoita tähän sitä mukaa kun puhutte: mitä sanoi, mikä kiinnosti, kuka päättää, milloin kannattaa palata…" />
    </div>

    <h2>Lopputulos</h2>
    <div class="outcomes">
      <button v-for="o in ORDER" :key="o" :class="{ selected: outcome === o, primary: o === 'booked' && outcome === o, danger: o === 'do_not_call' && outcome === o }" @click="pick(o)">
        {{ OUTCOME_LABELS[o] }}
      </button>
    </div>

    <div v-if="outcome === 'callback'" class="field" style="margin-top: 0.75rem">
      <label>Soita uudelleen (aika)</label>
      <input v-model="callbackAt" type="datetime-local" />
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
    <button class="primary big" :disabled="!canSubmit || busy" @click="submit">Tallenna ja seuraava →</button>
  </div>
</template>
