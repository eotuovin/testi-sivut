<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet, apiPost, errorText } from '../api/client'
import type { Campaign, Company } from '../api/types'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const companies = ref<Company[]>([])
const campaigns = ref<Campaign[]>([])
const q = ref('')
const status = ref('')
const error = ref('')
const selected = ref<Set<string>>(new Set())
const enqueueCampaign = ref('')
const showNew = ref(false)
const form = ref({ name: '', business_id: '', website: '', city: '', phone: '', contact_name: '', email: '' })
const importResult = ref('')

const STATUS: Record<string, string> = {
  prospect: 'Prospekti', contacted: 'Kontaktoitu', qualified: 'Kvalifioitu', customer: 'Asiakas',
  disqualified: 'Ei sovi', do_not_call: 'Ei saa soittaa',
}

async function load() {
  error.value = ''
  try {
    companies.value = await apiGet<Company[]>('/companies', { q: q.value, status: status.value, limit: 200 })
  } catch (e) {
    error.value = errorText(e)
  }
}
onMounted(async () => {
  await load()
  campaigns.value = (await apiGet<Campaign[]>('/campaigns')).filter((c) => c.status === 'active')
})

function toggle(id: string) {
  const s = new Set(selected.value)
  s.has(id) ? s.delete(id) : s.add(id)
  selected.value = s
}
async function enqueue() {
  if (!enqueueCampaign.value || !selected.value.size) return
  try {
    const r = await apiPost<{ enqueued: number }>(`/campaigns/${enqueueCampaign.value}/enqueue`, { company_ids: [...selected.value] })
    importResult.value = `${r.enqueued} yritystä lisätty jonoon`
    selected.value = new Set()
  } catch (e) {
    error.value = errorText(e)
  }
}
async function create() {
  try {
    const c = await apiPost<Company>('/companies', {
      name: form.value.name, business_id: form.value.business_id || null, website: form.value.website || null, city: form.value.city || null,
    })
    if (form.value.phone || form.value.email) {
      await apiPost(`/companies/${c.id}/contacts`, { name: form.value.contact_name || null, phone: form.value.phone || null, email: form.value.email || null, is_primary: true })
    }
    showNew.value = false
    form.value = { name: '', business_id: '', website: '', city: '', phone: '', contact_name: '', email: '' }
    await load()
  } catch (e) {
    error.value = errorText(e)
  }
}
async function importCsv(ev: Event) {
  const file = (ev.target as HTMLInputElement).files?.[0]
  if (!file) return
  const fd = new FormData()
  fd.append('file', file)
  try {
    const r = await apiPost<{ created: number; skipped: number }>('/companies/import', fd)
    importResult.value = `Tuotu ${r.created}, ohitettu ${r.skipped}`
    await load()
  } catch (e) {
    error.value = errorText(e)
  }
}
</script>

<template>
  <h1>Yritykset</h1>
  <div class="row" style="margin-bottom: 1rem">
    <input v-model="q" placeholder="Hae nimellä tai Y-tunnuksella" style="width: 260px" @keyup.enter="load" />
    <select v-model="status" style="width: auto" @change="load">
      <option value="">Kaikki tilat</option>
      <option v-for="(label, k) in STATUS" :key="k" :value="k">{{ label }}</option>
    </select>
    <button @click="load">Hae</button>
    <button @click="showNew = !showNew">+ Lisää yritys</button>
    <label class="btn" style="display: inline-block; margin: 0">Tuo CSV <input type="file" accept=".csv" style="display: none" @change="importCsv" /></label>
    <span v-if="importResult" class="small muted">{{ importResult }}</span>
  </div>
  <p v-if="error" class="error">{{ error }}</p>

  <div v-if="showNew" class="card">
    <div class="grid2">
      <input v-model="form.name" placeholder="Yrityksen nimi *" />
      <input v-model="form.business_id" placeholder="Y-tunnus" />
      <input v-model="form.website" placeholder="Verkkosivu" />
      <input v-model="form.city" placeholder="Paikkakunta" />
      <input v-model="form.contact_name" placeholder="Yhteyshenkilö" />
      <input v-model="form.phone" placeholder="Puhelin" />
      <input v-model="form.email" placeholder="Sähköposti" />
    </div>
    <button class="primary" style="margin-top: 0.5rem" :disabled="!form.name" @click="create">Tallenna</button>
    <p class="small muted">CSV-tuonnin sarakkeet: name, business_id, website, city, phone, contact_name, email, industry_label</p>
  </div>

  <div v-if="selected.size && auth.me" class="card row">
    <span>{{ selected.size }} valittu</span>
    <select v-model="enqueueCampaign" style="width: auto">
      <option value="">Valitse kampanja</option>
      <option v-for="c in campaigns" :key="c.id" :value="c.id">{{ c.name }}</option>
    </select>
    <button class="primary" :disabled="!enqueueCampaign" @click="enqueue">Lisää soittojonoon</button>
  </div>

  <div v-if="!companies.length" class="empty">Ei yrityksiä. Lisää käsin, tuo CSV tai aja prospektointi.</div>
  <table v-else>
    <tr><th></th><th>Nimi</th><th>Paikkakunta</th><th>Toimiala</th><th>Tila</th><th>Lähde</th><th>Yhteystiedot</th></tr>
    <tr v-for="c in companies" :key="c.id" class="clickable">
      <td><input type="checkbox" :checked="selected.has(c.id)" style="width: auto" @click.stop="toggle(c.id)" /></td>
      <td @click="router.push('/yritykset/' + c.id)"><strong>{{ c.name }}</strong><div class="small muted">{{ c.business_id }}</div></td>
      <td @click="router.push('/yritykset/' + c.id)">{{ c.city || '—' }}</td>
      <td @click="router.push('/yritykset/' + c.id)" class="small">{{ c.industry_label || '—' }}</td>
      <td><span class="tag" :class="{ ok: c.status === 'customer', danger: c.status === 'do_not_call' }">{{ STATUS[c.status] ?? c.status }}</span></td>
      <td class="small muted">{{ c.source }}</td>
      <td>{{ c.contact_count ?? '—' }}</td>
    </tr>
  </table>
</template>
