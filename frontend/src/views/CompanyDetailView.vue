<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { apiGet, apiPatch, apiPost, errorText } from '../api/client'
import type { CompanyDetail } from '../api/types'
import { OUTCOME_LABELS } from '../api/types'
import { fmtDateTime, fmtEur } from '../format'
import CallAnalysisPanel from '../components/CallAnalysisPanel.vue'

const route = useRoute()
const company = ref<CompanyDetail | null>(null)
const error = ref('')
const notes = ref('')
const openCall = ref<string | null>(null)
const nc = ref({ name: '', title: '', phone: '', email: '' })

async function load() {
  try {
    company.value = await apiGet<CompanyDetail>(`/companies/${route.params.id}`)
    notes.value = company.value.notes ?? ''
  } catch (e) {
    error.value = errorText(e)
  }
}
onMounted(load)

async function saveNotes() {
  if (!company.value) return
  await apiPatch(`/companies/${company.value.id}`, { notes: notes.value })
}
async function setStatus(status: string) {
  if (!company.value) return
  await apiPatch(`/companies/${company.value.id}`, { status })
  await load()
}
async function addContact() {
  if (!company.value) return
  try {
    await apiPost(`/companies/${company.value.id}/contacts`, { name: nc.value.name || null, title: nc.value.title || null, phone: nc.value.phone || null, email: nc.value.email || null })
    nc.value = { name: '', title: '', phone: '', email: '' }
    await load()
  } catch (e) {
    error.value = errorText(e)
  }
}
</script>

<template>
  <p v-if="error" class="error">{{ error }}</p>
  <div v-if="company">
    <router-link to="/yritykset" class="small">← Yritykset</router-link>
    <h1>{{ company.name }}</h1>
    <p class="muted small">{{ company.business_id || '' }} · {{ company.city || '—' }} · {{ company.industry_label || '—' }}
      <a v-if="company.website" :href="company.website.startsWith('http') ? company.website : 'https://' + company.website" target="_blank" rel="noopener"> · {{ company.website }}</a>
    </p>
    <div class="row" style="margin-bottom: 1rem">
      <span class="tag">{{ company.status }}</span>
      <button v-if="company.status !== 'do_not_call'" class="danger small" @click="setStatus('do_not_call')">Merkitse: ei saa soittaa</button>
      <button v-if="company.status === 'disqualified'" class="small" @click="setStatus('prospect')">Palauta prospektiksi</button>
    </div>

    <div class="grid2">
      <div class="card">
        <h2>Yhteyshenkilöt</h2>
        <table class="small">
          <tr v-for="c in company.contacts" :key="c.id">
            <td><strong>{{ c.name || '—' }}</strong><div class="muted">{{ c.title }}</div></td>
            <td><a v-if="c.phone_e164" :href="'tel:' + c.phone_e164">{{ c.phone_e164 }}</a><span v-if="c.do_not_call" class="tag danger">ei saa soittaa</span></td>
            <td><a v-if="c.email" :href="'mailto:' + c.email">{{ c.email }}</a></td>
            <td class="muted">{{ c.source }}</td>
          </tr>
        </table>
        <div class="grid2" style="margin-top: 0.5rem">
          <input v-model="nc.name" placeholder="Nimi" /><input v-model="nc.title" placeholder="Titteli" />
          <input v-model="nc.phone" placeholder="Puhelin" /><input v-model="nc.email" placeholder="Sähköposti" />
        </div>
        <button style="margin-top: 0.5rem" :disabled="!nc.phone && !nc.email && !nc.name" @click="addContact">Lisää yhteyshenkilö</button>
      </div>
      <div class="card">
        <h2>Muistiinpanot</h2>
        <textarea v-model="notes" style="min-height: 140px" />
        <button style="margin-top: 0.5rem" @click="saveNotes">Tallenna</button>
        <h2 style="margin-top: 1rem">Jonossa</h2>
        <div v-if="!company.tasks.length" class="muted small">Ei missään kampanjassa.</div>
        <div v-for="t in company.tasks" :key="t.id" class="small">{{ t.campaign_name }} · {{ t.status }} · {{ t.attempts }} yritystä · {{ fmtDateTime(t.due_at) }}</div>
      </div>
    </div>

    <div class="card">
      <h2>Bookkaukset</h2>
      <div v-if="!company.bookings.length" class="muted small">Ei bookkauksia.</div>
      <table v-else class="small">
        <tr v-for="b in company.bookings" :key="b.id">
          <td>{{ fmtDateTime(b.created_at) }}</td><td>{{ b.product }}</td><td>{{ fmtDateTime(b.scheduled_at) }}</td><td>{{ fmtEur(b.value_eur) }}</td><td><span class="tag">{{ b.status }}</span></td>
        </tr>
      </table>
    </div>

    <div class="card">
      <h2>Soittohistoria</h2>
      <div v-if="!company.calls.length" class="muted small">Ei soittoja.</div>
      <table v-else class="small">
        <tr><th>Aika</th><th>Tulos</th><th>Soittaja</th><th>Kenelle</th><th>Muistiinpanot</th></tr>
        <tr v-for="c in company.calls" :key="c.id">
          <td>{{ fmtDateTime(c.started_at) }}</td>
          <td>{{ OUTCOME_LABELS[c.outcome as keyof typeof OUTCOME_LABELS] ?? c.outcome }}<span v-if="c.callback_at" class="muted"> → {{ fmtDateTime(c.callback_at) }}</span></td>
          <td>{{ c.user_name }}</td>
          <td>{{ c.contact_name || c.phone_dialed || '' }}</td>
          <td class="muted">{{ c.notes }}
            <div style="margin-top: 0.3rem"><a href="#" @click.prevent="openCall = openCall === c.id ? null : c.id">{{ openCall === c.id ? 'Sulje analyysi' : 'Analyysi ja nauhoite' }}</a></div>
            <CallAnalysisPanel v-if="openCall === c.id" :call-id="c.id" :has-notes="!!c.notes" />
          </td>
        </tr>
      </table>
    </div>
  </div>
</template>
