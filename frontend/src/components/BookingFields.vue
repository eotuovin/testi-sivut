<script lang="ts">
export interface BookingDraft {
  scheduled_at: string
  duration_minutes: number
  location: string
  meeting_url: string
  attendee_email: string
  value_eur: number | null
  notes: string
}
export function emptyBooking(email: string | null): BookingDraft {
  return { scheduled_at: '', duration_minutes: 30, location: 'Teams', meeting_url: '', attendee_email: email ?? '', value_eur: null, notes: '' }
}
</script>

<script setup lang="ts">
import { computed } from 'vue'

const model = defineModel<BookingDraft>({ required: true })

// Quick picks: next few weekdays at 9/10/13/14 — the times people actually say yes to.
const quick = computed(() => {
  const out: { label: string; value: string }[] = []
  const d = new Date()
  d.setDate(d.getDate() + 1)
  const pad = (n: number) => String(n).padStart(2, '0')
  const days = ['su', 'ma', 'ti', 'ke', 'to', 'pe', 'la']
  while (out.length < 8) {
    if (d.getDay() !== 0 && d.getDay() !== 6) {
      for (const h of [10, 14]) {
        out.push({ label: `${days[d.getDay()]} ${d.getDate()}.${d.getMonth() + 1}. klo ${h}`, value: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(h)}:00` })
      }
    }
    d.setDate(d.getDate() + 1)
  }
  return out.slice(0, 8)
})
</script>

<template>
  <div class="card">
    <h3>Tapaaminen kalenteriin</h3>
    <div class="row" style="margin-bottom: 0.5rem">
      <button v-for="q in quick" :key="q.value" class="small" :class="{ selected: model.scheduled_at === q.value }" @click="model.scheduled_at = q.value">{{ q.label }}</button>
    </div>
    <div class="grid2">
      <div class="field"><label>Ajankohta *</label><input v-model="model.scheduled_at" type="datetime-local" /></div>
      <div class="field"><label>Kesto</label>
        <select v-model.number="model.duration_minutes"><option :value="15">15 min</option><option :value="30">30 min</option><option :value="45">45 min</option><option :value="60">60 min</option></select>
      </div>
      <div class="field"><label>Missä</label>
        <select v-model="model.location"><option>Teams</option><option>Google Meet</option><option>Puhelin</option><option>Asiakkaan luona</option><option>Meillä</option></select>
      </div>
      <div class="field"><label>Linkki tai osoite</label><input v-model="model.meeting_url" placeholder="https://teams… tai katuosoite" /></div>
      <div class="field"><label>Asiakkaan sähköposti (kutsua varten)</label><input v-model="model.attendee_email" type="email" /></div>
      <div class="field"><label>Arvo (€, jos sovittu)</label><input v-model.number="model.value_eur" type="number" min="0" step="1" /></div>
    </div>
    <div class="field"><label>Sovitut asiat</label><textarea v-model="model.notes" placeholder="Kuka osallistuu, mitä näytetään, mitä lähetetään etukäteen…" /></div>
  </div>
</template>

<style scoped>
button.selected { outline: 2px solid var(--accent); }
</style>
