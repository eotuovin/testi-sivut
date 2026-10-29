<script setup lang="ts">
/** The search desk: filter rail on the left, Yritykset / Henkilöt tabs on the
 *  right, bulk actions over the selection. Company results merge Luuri's own
 *  companies with live register hits; person results come from Luuri's contacts. */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiDelete, apiGet, apiPost, errorText } from '../api/client'
import type { Campaign, CompanyHit, CompanySearchResult, ContactHit, Facets, List, SavedSearch, Sequence } from '../api/types'
import { LEVEL_LABELS, STATUS_LABELS } from '../api/types'
import { fmtDate, fmtEur } from '../format'
import { useAuthStore } from '../stores/auth'
import AddToListModal from '../components/AddToListModal.vue'
import EnrollModal from '../components/EnrollModal.vue'
import CompanyLogo from '../components/CompanyLogo.vue'
import CampaignPicker from '../components/CampaignPicker.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

type Scope = 'company' | 'contact'
const scope = ref<Scope>((route.query.scope as Scope) || 'company')

/** Every filter in one object so saving / restoring a search is a copy. */
const f = reactive({
  q: '', location: '', industry: '', company_form: '', status: '', registered_after: '', registered_before: '',
  employees_min: '', employees_max: '', revenue_min: '', revenue_max: '',
  has_phone: false, has_email: false, not_called: false, owner_id: '', list_id: '', include_register: true,
  // people
  person: '', title: '', department: '', management_level: '', exclude_dnc: true,
})
const page = ref(1)
const companies = ref<CompanySearchResult | null>(null)
const contacts = ref<ContactHit[]>([])
const facets = ref<Facets | null>(null)
const campaigns = ref<Campaign[]>([])
const lists = ref<List[]>([])
const saved = ref<SavedSearch[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')
const selected = ref<Set<string>>(new Set())
const showList = ref(false)
const showEnroll = ref(false)
const filtersCollapsed = ref(window.innerWidth < 1000)
const bulkStatus = ref('')
async function applyBulkStatus() {
  const ids = selectedCompanies.value.filter((h) => h.id).map((h) => h.id as string)
  if (!ids.length || !bulkStatus.value) return
  try {
    const r = await apiPost<{ updated: number }>('/companies/bulk-status', { company_ids: ids, status: bulkStatus.value })
    notice.value = `${r.updated} yrityksen tila: ${STATUS_LABELS[bulkStatus.value]}`
    bulkStatus.value = ''
    selected.value = new Set()
    await search()
  } catch (e) { error.value = errorText(e) }
}
async function saveRegisterHits() {
  const reg = selectedCompanies.value.filter((h) => !h.id)
  if (!reg.length) return
  try {
    const r = await apiPost<{ created: number }>('/companies/from-register', { companies: reg.map((h) => ({
      business_id: h.business_id, name: h.name, company_form: h.company_form, industry_code: h.industry_code, industry_label: h.industry_label,
      website: h.website, city: h.city, postal_code: h.postal_code, street_address: h.street_address, registration_date: h.registration_date,
    })) })
    notice.value = `${r.created} yritystä tallennettu Luuriin`
    selected.value = new Set()
    await search()
  } catch (e) { error.value = errorText(e) }
}
const showSave = ref(false)
const saveName = ref('')
const enqueueCampaign = ref('')
const drawer = ref<CompanyHit | ContactHit | null>(null)

function key(h: CompanyHit) { return h.id ?? `reg:${h.business_id}` }
const selectedCompanies = computed(() => (companies.value?.items ?? []).filter((h) => selected.value.has(key(h))))
const selectedContacts = computed(() => contacts.value.filter((c) => selected.value.has(c.id)))
const activeFilterCount = computed(() => {
  let n = 0
  for (const [k, v] of Object.entries(f)) {
    if (['include_register', 'exclude_dnc', 'q'].includes(k)) continue
    if (v !== '' && v !== false) n++
  }
  return n
})

function params(): Record<string, unknown> {
  const p: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(f)) if (v !== '' && v !== false && v !== null) p[k] = v
  if (scope.value === 'company') { p.page = page.value; delete p.title; delete p.department; delete p.management_level; delete p.exclude_dnc }
  else {
    delete p.include_register; delete p.not_called; delete p.registered_after; delete p.registered_before; delete p.employees_min; delete p.employees_max; delete p.revenue_min; delete p.revenue_max; delete p.status; delete p.owner_id
    p.exclude_dnc = !!f.exclude_dnc
    if (p.q) { p.company = f.q; delete p.q }
    if (f.person) p.q = f.person
    delete p.person
  }
  if (scope.value === 'company') delete p.person
  return p
}

let seq = 0
async function search() {
  const my = ++seq
  loading.value = true
  error.value = ''
  try {
    if (scope.value === 'company') {
      const r = await apiGet<CompanySearchResult>('/search/companies', params())
      if (my === seq) companies.value = r
    } else {
      const r = await apiGet<{ items: ContactHit[] }>('/search/contacts', { ...params(), limit: 200 })
      if (my === seq) contacts.value = r.items
    }
  } catch (e) {
    error.value = errorText(e)
  } finally {
    if (my === seq) loading.value = false
  }
}
let timer: number | undefined
function debounced() {
  window.clearTimeout(timer)
  timer = window.setTimeout(() => { page.value = 1; selected.value = new Set(); search() }, 350)
}
watch(f, debounced)
watch(scope, () => { selected.value = new Set(); search() })
watch(() => route.query.q, (q) => { if (typeof q === 'string') f.q = q })

onMounted(async () => {
  if (typeof route.query.q === 'string') f.q = route.query.q
  if (typeof route.query.list_id === 'string') f.list_id = route.query.list_id
  const [fc, cp, ls, ss] = await Promise.all([
    apiGet<Facets>('/search/facets'), apiGet<Campaign[]>('/campaigns'), apiGet<List[]>('/lists'), apiGet<SavedSearch[]>('/saved-searches'),
  ])
  facets.value = fc
  campaigns.value = cp.filter((c) => c.status === 'active')
  lists.value = ls
  saved.value = ss
  await search()
})

function reset() {
  for (const k of Object.keys(f) as (keyof typeof f)[]) {
    const v = f[k]
    if (typeof v === 'boolean') (f as Record<string, unknown>)[k] = k === 'include_register' || k === 'exclude_dnc'
    else (f as Record<string, unknown>)[k] = ''
  }
}
function toggle(id: string) {
  const s = new Set(selected.value)
  s.has(id) ? s.delete(id) : s.add(id)
  selected.value = s
}
function toggleAll() {
  const ids = scope.value === 'company' ? (companies.value?.items ?? []).map(key) : contacts.value.map((c) => c.id)
  selected.value = selected.value.size === ids.length ? new Set() : new Set(ids)
}
function openCompany(h: CompanyHit) {
  if (h.id) router.push(`/yritykset/${h.id}`)
  else drawer.value = h
}
async function saveToLuuri(h: CompanyHit) {
  const r = await apiPost<{ companies: { id: string }[] }>('/companies/from-register', { companies: [{
    business_id: h.business_id, name: h.name, company_form: h.company_form, industry_code: h.industry_code, industry_label: h.industry_label,
    website: h.website, city: h.city, postal_code: h.postal_code, street_address: h.street_address, registration_date: h.registration_date,
  }] })
  router.push(`/yritykset/${r.companies[0].id}`)
}
async function enqueue() {
  if (!enqueueCampaign.value) return
  error.value = ''
  try {
    let ids = selectedCompanies.value.filter((h) => h.id).map((h) => h.id as string)
    const reg = selectedCompanies.value.filter((h) => !h.id)
    if (scope.value === 'contact') ids = [...new Set(selectedContacts.value.map((c) => c.company_id))]
    if (reg.length) {
      const r = await apiPost<{ companies: { id: string }[] }>('/companies/from-register', { companies: reg.map((h) => ({
        business_id: h.business_id, name: h.name, company_form: h.company_form, industry_code: h.industry_code, industry_label: h.industry_label,
        website: h.website, city: h.city, postal_code: h.postal_code, street_address: h.street_address, registration_date: h.registration_date,
      })) })
      ids.push(...r.companies.map((c) => c.id))
    }
    const r = await apiPost<{ enqueued: number }>(`/campaigns/${enqueueCampaign.value}/enqueue`, { company_ids: ids })
    notice.value = `${r.enqueued} yritystä lisätty soittojonoon`
    selected.value = new Set()
    await search()
  } catch (e) {
    error.value = errorText(e)
  }
}
function onEnrolled(r: { sequence: Sequence; enrolled: number; skipped: number }) {
  showEnroll.value = false
  notice.value = `${r.enrolled} lisätty ketjuun ”${r.sequence.name}”` + (r.skipped ? ` (${r.skipped} oli jo)` : '')
  selected.value = new Set()
}
function onAdded(r: { list: List; added: number }) {
  showList.value = false
  notice.value = `${r.added} lisätty listaan ”${r.list.name}”`
  selected.value = new Set()
  apiGet<List[]>('/lists').then((l) => (lists.value = l))
}
function exportCsv() {
  const rows = scope.value === 'company'
    ? [['name', 'business_id', 'city', 'industry', 'company_form', 'website', 'status', 'employees', 'contacts_with_phone'],
       ...selectedCompanies.value.map((h) => [h.name, h.business_id, h.city, h.industry_label, h.company_form, h.website, h.status, h.employees, h.phone_count])]
    : [['name', 'title', 'department', 'level', 'phone', 'email', 'company', 'business_id', 'city'],
       ...selectedContacts.value.map((c) => [c.name, c.title, c.department, c.management_level, c.phone_e164, c.email, c.company_name, c.business_id, c.city])]
  const csv = rows.map((r) => r.map((v) => `"${String(v ?? '').replace(/"/g, '""')}"`).join(',')).join('\n')
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' }))
  a.download = `luuri-${scope.value === 'company' ? 'yritykset' : 'henkilot'}.csv`
  a.click()
}
async function saveSearch() {
  try {
    const s = await apiPost<SavedSearch>('/saved-searches', { name: saveName.value, scope: scope.value, criteria: { ...f } })
    saved.value = [s, ...saved.value]
    showSave.value = false
    saveName.value = ''
    notice.value = `Haku ”${s.name}” tallennettu`
  } catch (e) {
    error.value = errorText(e)
  }
}
function applySaved(s: SavedSearch) {
  reset()
  scope.value = s.scope
  for (const [k, v] of Object.entries(s.criteria)) if (k in f) (f as Record<string, unknown>)[k] = v
}
async function deleteSaved(s: SavedSearch) {
  await apiDelete(`/saved-searches/${s.id}`)
  saved.value = saved.value.filter((x) => x.id !== s.id)
}
const statusClass = (s: string | null) => ({ ok: s === 'customer', danger: s === 'do_not_call', warn: s === 'disqualified', info: s === 'qualified' })
function fmtEmployees(n: number | null) { return n === null ? '—' : n >= 1000 ? `${(n / 1000).toFixed(1)} k` : String(n) }
function fmtRev(v: number | string | null) { if (v === null) return '—'; const n = Number(v); return n >= 1e6 ? `${(n / 1e6).toFixed(1)} M€` : fmtEur(n) }
</script>

<template>
  <div class="page-head">
    <div>
      <h1>Haku</h1>
      <p class="muted small">Yksi haku Luurin omista yrityksistä ja koko kaupparekisteristä. Rastita, lisää listaan tai suoraan soittojonoon.</p>
    </div>
    <div v-if="saved.length" class="row small">
      <span class="muted">Tallennetut haut:</span>
      <span v-for="s in saved" :key="s.id" class="chip" :title="`${s.scope === 'company' ? 'Yritykset' : 'Henkilöt'} · ${s.owner_name ?? ''}`" @click="applySaved(s)">
        {{ s.name }} <span class="muted" style="margin-left:0.2rem" @click.stop="deleteSaved(s)" title="Poista">×</span>
      </span>
    </div>
  </div>

  <div class="desk">
    <!-- ------------------------------------------------ filter rail -->
    <aside class="filters" :class="{ collapsed: filtersCollapsed }">
      <div class="fhead">
        <span>Suodattimet <span v-if="activeFilterCount" class="tag accent">{{ activeFilterCount }}</span></span>
        <span class="row" style="gap: 0.3rem">
          <button class="ghost small" @click="reset">Tyhjennä</button>
          <button class="ghost small toggle" @click="filtersCollapsed = !filtersCollapsed">{{ filtersCollapsed ? 'Näytä' : 'Piilota' }}</button>
        </span>
      </div>
      <details open>
        <summary>{{ scope === 'company' ? 'Yrityksen nimi' : 'Henkilön nimi' }}</summary>
        <div class="fbody">
          <input v-if="scope === 'company'" v-model="f.q" placeholder="Nimi tai Y-tunnus" />
          <template v-else>
            <input v-model="f.person" placeholder="Henkilön nimi" />
            <input v-model="f.q" placeholder="Yritys tai Y-tunnus" />
          </template>
        </div>
      </details>
      <details v-if="scope === 'contact'" open>
        <summary>Titteli ja taso<span v-if="f.title || f.management_level || f.department" class="count">●</span></summary>
        <div class="fbody">
          <input v-model="f.title" placeholder="Titteli, esim. toimitusjohtaja" list="titles" />
          <datalist id="titles"><option v-for="t in facets?.titles ?? []" :key="t.title" :value="t.title" /></datalist>
          <select v-model="f.management_level">
            <option value="">Kaikki tasot</option>
            <option v-for="l in facets?.management_levels ?? []" :key="l" :value="l">{{ LEVEL_LABELS[l] }}</option>
          </select>
          <input v-model="f.department" placeholder="Osasto, esim. myynti" list="depts" />
          <datalist id="depts"><option v-for="d in facets?.departments ?? []" :key="d.department" :value="d.department" /></datalist>
        </div>
      </details>
      <details open>
        <summary>Toimiala<span v-if="f.industry" class="count">1</span></summary>
        <div class="fbody">
          <input v-model="f.industry" placeholder="TOL-koodi tai sana, esim. 56 tai ravintola" list="industries" />
          <datalist id="industries"><option v-for="i in facets?.industries ?? []" :key="i.industry_label" :value="i.industry_code ?? i.industry_label">{{ i.industry_label }}</option></datalist>
          <div class="chips">
            <span v-for="i in (facets?.industries ?? []).slice(0, 6)" :key="i.industry_label" class="chip" :class="{ on: f.industry === (i.industry_code ?? i.industry_label) }" @click="f.industry = f.industry === (i.industry_code ?? i.industry_label) ? '' : (i.industry_code ?? i.industry_label)">{{ i.industry_label.slice(0, 22) }}</span>
          </div>
        </div>
      </details>
      <details open>
        <summary>Sijainti<span v-if="f.location" class="count">1</span></summary>
        <div class="fbody">
          <input v-model="f.location" placeholder="Paikkakunta tai postinumero" list="cities" />
          <datalist id="cities"><option v-for="c in facets?.cities ?? []" :key="c.city" :value="c.city" /></datalist>
          <div class="chips">
            <span v-for="c in ['Jyväskylä', 'Tampere', 'Helsinki', 'Kuopio', 'Oulu', 'Turku']" :key="c" class="chip" :class="{ on: f.location === c }" @click="f.location = f.location === c ? '' : c">{{ c }}</span>
          </div>
        </div>
      </details>
      <details v-if="scope === 'company'">
        <summary>Koko<span v-if="f.employees_min || f.employees_max || f.revenue_min || f.revenue_max" class="count">●</span></summary>
        <div class="fbody">
          <label>Henkilöstö</label>
          <div class="range"><input v-model="f.employees_min" type="number" min="0" placeholder="min" /><span>–</span><input v-model="f.employees_max" type="number" min="0" placeholder="max" /></div>
          <div class="chips">
            <span v-for="[a, b, l] in [[1, 9, '1–9'], [10, 49, '10–49'], [50, 249, '50–249'], [250, '', '250+']] as const" :key="l" class="chip" :class="{ on: String(f.employees_min) === String(a) && String(f.employees_max) === String(b) }" @click="f.employees_min = String(a); f.employees_max = String(b)">{{ l }}</span>
          </div>
          <label>Liikevaihto (€)</label>
          <div class="range"><input v-model="f.revenue_min" type="number" min="0" placeholder="min" /><span>–</span><input v-model="f.revenue_max" type="number" min="0" placeholder="max" /></div>
          <p class="muted small" style="margin:0">Koko tunnetaan vain Luuriin tallennetuista yrityksistä.</p>
        </div>
      </details>
      <details v-if="scope === 'company'">
        <summary>Yhtiömuoto ja ikä<span v-if="f.company_form || f.registered_after || f.registered_before" class="count">●</span></summary>
        <div class="fbody">
          <select v-model="f.company_form"><option value="">Kaikki yhtiömuodot</option><option v-for="cf in facets?.company_forms ?? []" :key="cf" :value="cf">{{ cf }}</option></select>
          <label>Rekisteröity</label>
          <div class="range"><input v-model="f.registered_after" type="date" /><span>–</span><input v-model="f.registered_before" type="date" /></div>
        </div>
      </details>
      <details>
        <summary>Yhteystiedot<span v-if="f.has_phone || f.has_email" class="count">●</span></summary>
        <div class="fbody">
          <label class="check"><input v-model="f.has_phone" type="checkbox" /> Puhelinnumero tiedossa</label>
          <label class="check"><input v-model="f.has_email" type="checkbox" /> Sähköposti tiedossa</label>
          <label v-if="scope === 'contact'" class="check"><input v-model="f.exclude_dnc" type="checkbox" /> Piilota soittokiellot</label>
        </div>
      </details>
      <details v-if="scope === 'company'">
        <summary>Tila Luurissa<span v-if="f.status || f.not_called || f.owner_id || f.list_id" class="count">●</span></summary>
        <div class="fbody">
          <select v-model="f.status"><option value="">Kaikki tilat</option><option v-for="(l, k) in STATUS_LABELS" :key="k" :value="k">{{ l }}</option></select>
          <label class="check"><input v-model="f.not_called" type="checkbox" /> Ei vielä soitettu</label>
          <select v-model="f.owner_id"><option value="">Kuka tahansa omistaja</option><option v-for="o in facets?.owners ?? []" :key="o.id" :value="o.id">{{ o.name }}</option></select>
          <select v-model="f.list_id"><option value="">Ei listarajausta</option><option v-for="l in lists" :key="l.id" :value="l.id">Lista: {{ l.name }}</option></select>
          <label class="check"><input v-model="f.include_register" type="checkbox" /> Näytä myös rekisterin yritykset</label>
        </div>
      </details>
      <details v-else>
        <summary>Lista<span v-if="f.list_id" class="count">1</span></summary>
        <div class="fbody">
          <select v-model="f.list_id"><option value="">Ei listarajausta</option><option v-for="l in lists" :key="l.id" :value="l.id">{{ l.name }}</option></select>
        </div>
      </details>
    </aside>

    <!-- ------------------------------------------------ results -->
    <section class="results">
      <div class="tabs">
        <button :class="{ on: scope === 'company' }" @click="scope = 'company'">Yritykset<span v-if="companies" class="n">{{ companies.items.length }}<template v-if="companies.register_total"> / {{ companies.local_count }} omaa + {{ companies.register_total.toLocaleString('fi-FI') }} rek.</template></span></button>
        <button :class="{ on: scope === 'contact' }" @click="scope = 'contact'">Henkilöt<span class="n">{{ scope === 'contact' ? contacts.length : '' }}</span></button>
      </div>

      <div class="toolbar">
        <template v-if="selected.size">
          <label class="check" style="margin:0"><input type="checkbox" :checked="true" @change="toggleAll" /></label>
          <span class="sel">{{ selected.size }} valittu</span>
          <button class="small" @click="showList = true">+ Lisää listaan</button>
          <button class="small" @click="showEnroll = true">Sekvenssiin</button>
          <CampaignPicker v-model="enqueueCampaign" />
          <button class="small primary" :disabled="!enqueueCampaign || enqueueCampaign === '__new'" @click="enqueue">Lisää jonoon</button>
          <button class="small" @click="exportCsv">Vie CSV</button>
          <template v-if="scope === 'company'">
            <select v-model="bulkStatus" class="small" style="width:auto"><option value="">Merkitse tila…</option><option v-for="(l, k) in STATUS_LABELS" :key="k" :value="k">{{ l }}</option></select>
            <button class="small" :disabled="!bulkStatus" @click="applyBulkStatus">OK</button>
            <button v-if="selectedCompanies.some((h) => !h.id)" class="small" @click="saveRegisterHits">Tallenna Luuriin ({{ selectedCompanies.filter((h) => !h.id).length }})</button>
          </template>
          <button class="ghost small" @click="selected = new Set()">Tyhjennä valinta</button>
        </template>
        <template v-else>
          <button class="small" @click="showSave = true">Tallenna haku</button>
          <span v-if="loading" class="muted small">Haetaan…</span>
          <span v-else-if="companies?.register_error && scope === 'company'" class="small error">{{ companies.register_error }}</span>
        </template>
        <span v-if="notice" class="small tag ok" style="margin-left:auto">{{ notice }}</span>
      </div>
      <p v-if="error" class="error small">{{ error }}</p>

      <!-- companies -->
      <div v-if="scope === 'company'" class="table-wrap">
        <table>
          <thead><tr>
            <th style="width:32px"><input type="checkbox" :checked="!!companies?.items.length && selected.size === companies?.items.length" @change="toggleAll" /></th>
            <th>Yritys</th><th>Toimiala</th><th>Sijainti</th><th class="nowrap">Henk.</th><th class="nowrap">Liikevaihto</th><th>Yhteystiedot</th><th>Tila</th><th>Viim. soitto</th>
          </tr></thead>
          <tbody>
            <tr v-for="h in companies?.items ?? []" :key="key(h)" class="clickable" @click="openCompany(h)">
              <td @click.stop><input type="checkbox" :checked="selected.has(key(h))" @change="toggle(key(h))" /></td>
              <td>
                <div class="co">
                  <CompanyLogo :name="h.name" :website="h.website" />
                  <div class="t">
                    <strong>{{ h.name }}</strong>
                    <div class="sub">{{ h.business_id || '' }}<template v-if="h.company_form"> · {{ h.company_form }}</template><template v-if="h.website"> · {{ h.website.replace(/^https?:\/\//, '') }}</template></div>
                  </div>
                </div>
              </td>
              <td class="small">{{ h.industry_label || '—' }}<div v-if="h.industry_code" class="muted">{{ h.industry_code }}</div></td>
              <td class="small">{{ h.city || '—' }}</td>
              <td class="mono">{{ fmtEmployees(h.employees) }}</td>
              <td class="mono nowrap">{{ fmtRev(h.revenue_eur) }}</td>
              <td class="small nowrap">
                <span :class="{ dot: true, ok: h.phone_count > 0 }"></span>{{ h.phone_count }} puh · {{ h.email_count }} email
              </td>
              <td>
                <span v-if="h.in_db" class="tag" :class="statusClass(h.status)">{{ STATUS_LABELS[h.status ?? ''] ?? h.status }}</span>
                <span v-else class="tag info" title="Kaupparekisterissä, ei vielä Luurissa">Rekisteri</span>
              </td>
              <td class="small muted nowrap">{{ h.last_call_at ? fmtDate(h.last_call_at) : '—' }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="companies && !companies.items.length && !loading" class="empty">Ei osumia. Kokeile väljempiä suodattimia — rekisterihaku tarvitsee nimen, paikkakunnan tai toimialan.</div>
        <div v-if="companies?.register_total" class="pager">
          <span>Rekisterisivu {{ page }} · {{ companies.register_total.toLocaleString('fi-FI') }} osumaa rekisterissä</span>
          <span class="row">
            <button class="small" :disabled="page <= 1" @click="page--; search()">‹ Edellinen</button>
            <button class="small" :disabled="page * 50 >= companies.register_total" @click="page++; search()">Seuraava ›</button>
          </span>
        </div>
      </div>

      <!-- people -->
      <div v-else class="table-wrap">
        <table>
          <thead><tr>
            <th style="width:32px"><input type="checkbox" :checked="!!contacts.length && selected.size === contacts.length" @change="toggleAll" /></th>
            <th>Henkilö</th><th>Titteli</th><th>Taso</th><th>Yritys</th><th>Puhelin</th><th>Sähköposti</th><th>Lähde</th>
          </tr></thead>
          <tbody>
            <tr v-for="c in contacts" :key="c.id" class="clickable" @click="router.push(`/yritykset/${c.company_id}`)">
              <td @click.stop><input type="checkbox" :checked="selected.has(c.id)" @change="toggle(c.id)" /></td>
              <td><strong>{{ c.name || 'Yleinen numero' }}</strong><span v-if="c.is_primary" class="tag" style="margin-left:0.3rem">ensisij.</span><span v-if="c.verified_at" class="tag ok" style="margin-left:0.3rem" title="Numero vahvistettu puhelussa">✓</span></td>
              <td class="small">{{ c.title || '—' }}<div v-if="c.department" class="muted">{{ c.department }}</div></td>
              <td class="small">{{ c.management_level ? LEVEL_LABELS[c.management_level] : '—' }}</td>
              <td class="small">{{ c.company_name }}<div class="muted">{{ c.city || '' }}<template v-if="c.industry_label"> · {{ c.industry_label.slice(0, 30) }}</template></div></td>
              <td class="nowrap" @click.stop><a v-if="c.phone_e164" :href="'tel:' + c.phone_e164">{{ c.phone_e164 }}</a><span v-else class="muted">—</span><span v-if="c.do_not_call" class="tag danger" style="margin-left:0.3rem">kielto</span></td>
              <td class="small" @click.stop><a v-if="c.email" :href="'mailto:' + c.email">{{ c.email }}</a><span v-else class="muted">—</span></td>
              <td class="small muted">{{ c.source }}<template v-if="c.confidence !== null"> · {{ Math.round(Number(c.confidence) * 100) }} %</template></td>
            </tr>
          </tbody>
        </table>
        <div v-if="!contacts.length && !loading" class="empty">Ei henkilöitä. Henkilöhaku kattaa Luuriin tallennetut yhteyshenkilöt — hae ensin yritykset ja anna agentin etsiä päättäjät.</div>
      </div>
    </section>
  </div>

  <AddToListModal v-if="showList" :kind="scope" :company-ids="scope === 'company' ? selectedCompanies.filter((h) => h.id).map((h) => h.id as string) : []"
    :register="scope === 'company' ? selectedCompanies.filter((h) => !h.id) : []" :contact-ids="scope === 'contact' ? selectedContacts.map((c) => c.id) : []"
    @close="showList = false" @added="onAdded" />

  <EnrollModal v-if="showEnroll" :company-ids="scope === 'company' ? selectedCompanies.filter((h) => h.id).map((h) => h.id as string) : []"
    :register="scope === 'company' ? selectedCompanies.filter((h) => !h.id) : []" :contact-ids="scope === 'contact' ? selectedContacts.map((c) => c.id) : []"
    @close="showEnroll = false" @enrolled="onEnrolled" />

  <div v-if="showSave" class="modal" @click.self="showSave = false">
    <div class="box">
      <h2>Tallenna haku</h2>
      <p class="muted small">Tallennettu haku näkyy kaikille myyjille sivun yläreunassa.</p>
      <div class="field"><label>Nimi</label><input v-model="saveName" placeholder="esim. JKL ravintolat ilman soittoa" @keyup.enter="saveSearch" /></div>
      <div class="row" style="justify-content:flex-end"><button class="ghost" @click="showSave = false">Peruuta</button><button class="primary" :disabled="!saveName.trim()" @click="saveSearch">Tallenna</button></div>
    </div>
  </div>

  <template v-if="drawer && 'in_db' in drawer">
    <div class="drawer-bg" @click="drawer = null"></div>
    <div class="drawer">
      <div class="row" style="justify-content:space-between"><h2 style="margin:0">{{ drawer.name }}</h2><button class="ghost" @click="drawer = null">✕</button></div>
      <p class="muted small">Kaupparekisterin tiedot. Yritys ei ole vielä Luurissa — tallenna, niin saat profiilisivun, yhteyshenkilöt ja soittohistorian.</p>
      <div class="facts" style="grid-template-columns:1fr 1fr">
        <div class="fact"><div class="k">Y-tunnus</div><div class="v">{{ drawer.business_id }}</div></div>
        <div class="fact"><div class="k">Yhtiömuoto</div><div class="v">{{ drawer.company_form || '—' }}</div></div>
        <div class="fact"><div class="k">Toimiala</div><div class="v">{{ drawer.industry_label || '—' }}<div class="muted small">{{ drawer.industry_code }}</div></div></div>
        <div class="fact"><div class="k">Rekisteröity</div><div class="v">{{ fmtDate(drawer.registration_date) }}</div></div>
        <div class="fact"><div class="k">Osoite</div><div class="v">{{ [drawer.street_address, drawer.postal_code, drawer.city].filter(Boolean).join(', ') || '—' }}</div></div>
        <div class="fact"><div class="k">Verkkosivu</div><div class="v"><a v-if="drawer.website" :href="'https://' + drawer.website.replace(/^https?:\/\//, '')" target="_blank" rel="noopener">{{ drawer.website }}</a><span v-else>—</span></div></div>
      </div>
      <div class="row" style="margin-top:1rem">
        <button class="primary" @click="saveToLuuri(drawer)">Tallenna Luuriin ja avaa</button>
        <button @click="selected = new Set([key(drawer)]); showList = true; drawer = null">Lisää listaan</button>
      </div>
      <p class="muted small" style="margin-top:1rem">{{ auth.me?.name }}, vinkki: rastita rekisteriosumat ja lisää ne suoraan soittojonoon — ne tallentuvat samalla.</p>
    </div>
  </template>
</template>
