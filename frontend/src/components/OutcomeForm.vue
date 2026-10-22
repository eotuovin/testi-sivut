<script setup lang="ts">
import { computed, ref } from 'vue'
import type { CallLog, Contact, Outcome } from '../api/types'
import { OUTCOME_LABELS } from '../api/types'

const props = defineProps<{ contacts: Contact[]; contactId: string | null; phone: string | null; busy: boolean }>()
const emit = defineEmits<{ (e: 'submit', body: CallLog): void }>()

const ORDER: Outcome[] = ['no_answer', 'busy', 'voicemail', 'gatekeeper', 'callback', 'not_interested', 'already_customer', 'wrong_number', 'do_not_call', 'booked']
const outcome = ref<Outcome | null>(null)
const notes = ref('')
const callbackAt = ref(defaultCallback())
const bookingAt = ref('')
const bookingValue = ref<number | null>(null)
const bookingNotes = ref('')
const addContact = ref(false)
const nc = ref({ name: '', title: '', phone: '', email: '' })
const error = ref('')

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
  return true
})
function submit() {
  if (!outcome.value) return
  const body: CallLog = { outcome: outcome.value, notes: notes.value || null, contact_id: props.contactId, phone_dialed: props.phone }
  if (outcome.value === 'callback') body.callback_at = new Date(callbackAt.value).toISOString()
  if (outcome.value === 'booked') {
    body.booking = {
      scheduled_at: bookingAt.value ? new Date(bookingAt.value).toISOString() : null,
      value_eur: bookingValue.value,
      notes: bookingNotes.value || null,
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

    <div v-if="outcome === 'booked'" class="card" style="margin-top: 0.75rem">
      <h3>Bookkaus</h3>
      <div class="grid2">
        <div class="field"><label>Sovittu ajankohta</label><input v-model="bookingAt" type="datetime-local" /></div>
        <div class="field"><label>Arvo (€, jos sovittu)</label><input v-model.number="bookingValue" type="number" min="0" step="1" /></div>
      </div>
      <div class="field"><label>Sovitut asiat</label><textarea v-model="bookingNotes" placeholder="Mitä sovittiin, kuka osallistuu, mitä lähetetään etukäteen…" /></div>
    </div>

    <div class="field" style="margin-top: 0.75rem">
      <label>Muistiinpanot</label>
      <textarea v-model="notes" placeholder="Mitä puhuttiin, kenet tavoitit, milloin kannattaa soittaa…" />
    </div>

    <div class="field">
      <label><input type="checkbox" v-model="addContact" style="width: auto; margin-right: 0.4rem" />Opin uuden yhteyshenkilön tai numeron</label>
      <div v-if="addContact" class="grid2">
        <input v-model="nc.name" placeholder="Nimi" />
        <input v-model="nc.title" placeholder="Titteli" />
        <input v-model="nc.phone" placeholder="Puhelin" />
        <input v-model="nc.email" placeholder="Sähköposti" />
      </div>
    </div>

    <p v-if="error" class="error small">{{ error }}</p>
    <button class="primary big" :disabled="!canSubmit || busy" @click="submit">Tallenna ja seuraava →</button>
  </div>
</template>
