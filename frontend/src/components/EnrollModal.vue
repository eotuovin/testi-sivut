<script setup lang="ts">
/** "Lisää sekvenssiin": pick a sequence, enrol the selection. Register hits
 *  are saved into Luuri first so they have an id to enrol. */
import { onMounted, ref } from 'vue'
import { apiGet, apiPost, errorText } from '../api/client'
import type { CompanyHit, Sequence } from '../api/types'
import { STEP_LABELS } from '../api/types'

const props = defineProps<{ companyIds?: string[]; contactIds?: string[]; listId?: string; register?: CompanyHit[] }>()
const emit = defineEmits<{ close: []; enrolled: [{ sequence: Sequence; enrolled: number; skipped: number }] }>()

const sequences = ref<Sequence[]>([])
const chosen = ref('')
const error = ref('')
const busy = ref(false)
const startAt = ref('')

onMounted(async () => {
  sequences.value = (await apiGet<Sequence[]>('/sequences')).filter((s) => s.status === 'active' && s.step_count > 0)
  chosen.value = sequences.value[0]?.id ?? ''
})

async function submit() {
  busy.value = true
  error.value = ''
  try {
    const companyIds = [...(props.companyIds ?? [])]
    if (props.register?.length) {
      const r = await apiPost<{ companies: { id: string }[] }>('/companies/from-register', { companies: props.register.map((h) => ({
        business_id: h.business_id, name: h.name, company_form: h.company_form, industry_code: h.industry_code, industry_label: h.industry_label,
        website: h.website, city: h.city, postal_code: h.postal_code, street_address: h.street_address, registration_date: h.registration_date,
      })) })
      companyIds.push(...r.companies.map((c) => c.id))
    }
    const r = await apiPost<{ enrolled: number; skipped: number }>(`/sequences/${chosen.value}/enroll`, {
      company_ids: companyIds, contact_ids: props.contactIds ?? [], list_id: props.listId ?? null,
      start_at: startAt.value ? new Date(startAt.value).toISOString() : null,
    })
    emit('enrolled', { sequence: sequences.value.find((s) => s.id === chosen.value)!, ...r })
  } catch (e) {
    error.value = errorText(e)
  } finally {
    busy.value = false
  }
}
const total = () => (props.companyIds?.length ?? 0) + (props.contactIds?.length ?? 0) + (props.register?.length ?? 0)
</script>

<template>
  <div class="modal" @click.self="emit('close')">
    <div class="box">
      <h2>Lisää sekvenssiin</h2>
      <p class="muted small">{{ listId ? 'Koko lista' : total() + ' valittua' }} lähtee ketjuun. Jo ketjussa olevat ohitetaan.</p>
      <div v-if="!sequences.length" class="empty">Ei aktiivisia sekvenssejä. <router-link to="/sekvenssit">Luo ensimmäinen →</router-link></div>
      <template v-else>
        <div class="field">
          <label>Sekvenssi</label>
          <select v-model="chosen">
            <option v-for="s in sequences" :key="s.id" :value="s.id">{{ s.name }} · {{ s.step_count }} askelta<template v-if="s.campaign_name"> · {{ s.campaign_name }}</template></option>
          </select>
        </div>
        <div class="field">
          <label>Aloitus (tyhjä = heti)</label>
          <input v-model="startAt" type="datetime-local" />
        </div>
        <p class="muted small">Askeleet: {{ Object.values(STEP_LABELS).join(' / ') }} — soitot menevät sekvenssin kampanjan jonoon, sähköpostit ja tehtävät <router-link to="/tehtavat">Tehtävät</router-link>-sivulle.</p>
      </template>
      <p v-if="error" class="error small">{{ error }}</p>
      <div class="row" style="justify-content: flex-end">
        <button class="ghost" @click="emit('close')">Peruuta</button>
        <button class="primary" :disabled="busy || !chosen" @click="submit">Lisää ketjuun</button>
      </div>
    </div>
  </div>
</template>
