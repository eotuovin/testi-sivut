<script setup lang="ts">
/** Company profile: header with the key facts, then tabs — overview, people,
 *  activity (calls + bookings), notes. Facts are editable in place. */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiDelete, apiGet, apiPatch, apiPost, errorText } from '../api/client'
import type { Booking, CallRow, Campaign, CompanyDetail, CompanySequence, Contact, Facets, ManagementLevel } from '../api/types'
import { LEVEL_LABELS, OUTCOME_LABELS, STATUS_LABELS } from '../api/types'
import { fmtDate, fmtDateTime, fmtEur } from '../format'
import CallAnalysisPanel from '../components/CallAnalysisPanel.vue'
import CompanyLogo from '../components/CompanyLogo.vue'
import CampaignPicker from '../components/CampaignPicker.vue'
import AddToListModal from '../components/AddToListModal.vue'
import EnrollModal from '../components/EnrollModal.vue'

const route = useRoute()
const router = useRouter()
const company = ref<CompanyDetail | null>(null)
const facets = ref<Facets | null>(null)
const campaigns = ref<Campaign[]>([])
const error = ref('')
const notice = ref('')
const tab = ref<'overview' | 'people' | 'activity' | 'notes'>('overview')
const notes = ref('')
const openCall = ref<string | null>(null)
const showList = ref(false)
const showEnroll = ref(false)
const seqs = ref<CompanySequence[]>([])
const campaign = ref('')
const editFacts = ref(false)
const facts = ref({ employees: '', revenue_eur: '', founded_year: '', phone: '', email: '', website: '', linkedin_url: '', street_address: '', postal_code: '', city: '', industry_label: '', description: '', technologies: '' })
const nc = ref({ name: '', title: '', department: '', management_level: '' as ManagementLevel | '', phone: '', email: '', linkedin_url: '' })
const editContact = ref<string | null>(null)
const ec = ref({ name: '', title: '', department: '', management_level: '' as ManagementLevel | '', phone: '', email: '', linkedin_url: '' })

async function load() {
  try {
    const c = await apiGet<CompanyDetail>(`/companies/${route.params.id}`)
    company.value = c
    notes.value = c.notes ?? ''
    seqs.value = await apiGet<CompanySequence[]>(`/companies/${c.id}/sequences`)
    facts.value = {
      employees: c.employees?.toString() ?? '', revenue_eur: c.revenue_eur?.toString() ?? '', founded_year: c.founded_year?.toString() ?? '',
      phone: c.phone ?? '', email: c.email ?? '', website: c.website ?? '', linkedin_url: c.linkedin_url ?? '', street_address: c.street_address ?? '',
      postal_code: c.postal_code ?? '', city: c.city ?? '', industry_label: c.industry_label ?? '', description: c.description ?? '', technologies: (c.technologies ?? []).join(', '),
    }
  } catch (e) { error.value = errorText(e) }
}
onMounted(async () => {
  await load()
  if (route.query.tab) tab.value = route.query.tab as typeof tab.value
  ;[facets.value, campaigns.value] = await Promise.all([apiGet<Facets>('/search/facets'), apiGet<Campaign[]>('/campaigns').then((c) => c.filter((x) => x.status === 'active'))])
})

async function patch(body: Record<string, unknown>) {
  if (!company.value) return
  try { await apiPatch(`/companies/${company.value.id}`, body); await load() } catch (e) { error.value = errorText(e) }
}
async function saveFacts() {
  const f = facts.value
  await patch({
    employees: f.employees === '' ? null : Number(f.employees), revenue_eur: f.revenue_eur === '' ? null : Number(f.revenue_eur),
    founded_year: f.founded_year === '' ? null : Number(f.founded_year), phone: f.phone || null, email: f.email || null, website: f.website || null,
    linkedin_url: f.linkedin_url || null, street_address: f.street_address || null, postal_code: f.postal_code || null, city: f.city || null,
    industry_label: f.industry_label || null, description: f.description || null,
    technologies: f.technologies.split(',').map((t) => t.trim()).filter(Boolean),
  })
  editFacts.value = false
}
async function saveNotes() { await patch({ notes: notes.value }); notice.value = 'Muistiinpanot tallennettu' }
async function setOwner(id: string) { await patch(id ? { owner_id: id } : { clear_owner: true }) }
async function addContact() {
  if (!company.value) return
  try {
    await apiPost(`/companies/${company.value.id}/contacts`, { ...nc.value, management_level: nc.value.management_level || null, name: nc.value.name || null, title: nc.value.title || null, department: nc.value.department || null, phone: nc.value.phone || null, email: nc.value.email || null, linkedin_url: nc.value.linkedin_url || null })
    nc.value = { name: '', title: '', department: '', management_level: '', phone: '', email: '', linkedin_url: '' }
    await load()
  } catch (e) { error.value = errorText(e) }
}
function startEdit(c: Contact) {
  editContact.value = c.id
  ec.value = { name: c.name ?? '', title: c.title ?? '', department: c.department ?? '', management_level: c.management_level ?? '', phone: c.phone ?? c.phone_e164 ?? '', email: c.email ?? '', linkedin_url: c.linkedin_url ?? '' }
}
async function saveContact() {
  if (!editContact.value) return
  const b = ec.value
  try {
    await apiPatch(`/contacts/${editContact.value}`, { name: b.name || null, title: b.title || null, department: b.department || null, management_level: b.management_level || null, phone: b.phone || null, email: b.email || null, linkedin_url: b.linkedin_url || null })
    editContact.value = null
    await load()
  } catch (e) { error.value = errorText(e) }
}
async function contactAction(c: Contact, body: Record<string, unknown>) { await apiPatch(`/contacts/${c.id}`, body); await load() }
async function deleteContact(c: Contact) { if (confirm(`Poistetaanko ${c.name || 'yhteyshenkilö'}?`)) { await apiDelete(`/contacts/${c.id}`); await load() } }
async function stopSeq(id: string) { await apiPost(`/sequences/enrollments/${id}/stop`); await load() }
async function enqueue() {
  if (!company.value || !campaign.value) return
  try {
    const r = await apiPost<{ enqueued: number }>(`/campaigns/${campaign.value}/enqueue`, { company_ids: [company.value.id] })
    notice.value = r.enqueued ? 'Lisätty soittojonoon' : 'Oli jo jonossa'
    await load()
  } catch (e) { error.value = errorText(e) }
}
const site = computed(() => company.value?.website ? (company.value.website.startsWith('http') ? company.value.website : 'https://' + company.value.website) : null)
const timeline = computed(() => {
  if (!company.value) return []
  type Item = { at: string; kind: 'call'; call: CallRow; booking?: undefined } | { at: string; kind: 'booking'; booking: Booking; call?: undefined }
  const items: Item[] = [
    ...company.value.calls.map((c): Item => ({ at: c.started_at, kind: 'call', call: c })),
    ...company.value.bookings.map((b): Item => ({ at: b.created_at, kind: 'booking', booking: b })),
  ]
  return items.sort((a, b) => (a.at < b.at ? 1 : -1))
})
const statusClass = (s: string) => ({ ok: s === 'customer', danger: s === 'do_not_call', warn: s === 'disqualified', info: s === 'qualified' })
</script>

<template>
  <p v-if="error" class="error">{{ error }}</p>
  <div v-if="company">
    <a href="#" class="small" @click.prevent="router.back()">← Takaisin</a>
    <div class="card">
      <div class="profile-head">
        <CompanyLogo :name="company.name" :url="company.logo_url" :website="company.website" />
        <div>
          <h1 style="margin-bottom:0.2rem">{{ company.name }} <span class="tag" :class="statusClass(company.status)">{{ STATUS_LABELS[company.status] ?? company.status }}</span></h1>
          <div class="meta">
            <span v-if="company.business_id">Y-tunnus {{ company.business_id }}</span>
            <span v-if="company.company_form">{{ company.company_form }}</span>
            <span v-if="company.industry_label">{{ company.industry_label }}</span>
            <span v-if="company.city">{{ company.city }}</span>
            <a v-if="site" :href="site" target="_blank" rel="noopener">{{ company.website }}</a>
            <a v-if="company.linkedin_url" :href="company.linkedin_url" target="_blank" rel="noopener">LinkedIn</a>
            <a v-if="company.phone" :href="'tel:' + company.phone">{{ company.phone }}</a>
            <span v-if="company.lists.length" class="muted">Listoilla: <router-link v-for="(l, i) in company.lists" :key="l.id" :to="`/listat/${l.id}`">{{ l.name }}{{ i < company.lists.length - 1 ? ', ' : '' }}</router-link></span>
          </div>
        </div>
        <div class="actions">
          <CampaignPicker v-model="campaign" />
          <button class="primary" :disabled="!campaign || campaign === '__new'" @click="enqueue">Lisää jonoon</button>
          <button @click="showList = true">+ Listaan</button>
          <button @click="showEnroll = true">Sekvenssiin</button>
          <select :value="company.status" style="width:auto" @change="patch({ status: ($event.target as HTMLSelectElement).value })">
            <option v-for="(l, k) in STATUS_LABELS" :key="k" :value="k">{{ l }}</option>
          </select>
        </div>
      </div>
      <p v-if="notice" class="tag ok" style="margin:0.6rem 0 0">{{ notice }}</p>
    </div>

    <div class="tabs">
      <button :class="{ on: tab === 'overview' }" @click="tab = 'overview'">Yleiskatsaus</button>
      <button :class="{ on: tab === 'people' }" @click="tab = 'people'">Henkilöt<span class="n">{{ company.contacts.length }}</span></button>
      <button :class="{ on: tab === 'activity' }" @click="tab = 'activity'">Toiminta<span class="n">{{ company.calls.length + company.bookings.length }}</span></button>
      <button :class="{ on: tab === 'notes' }" @click="tab = 'notes'">Muistiinpanot</button>
    </div>

    <!-- overview -->
    <div v-if="tab === 'overview'">
      <div class="card">
        <div class="row" style="justify-content:space-between"><h2>Perustiedot</h2><button v-if="!editFacts" class="ghost small" @click="editFacts = true">Muokkaa</button><span v-else class="row"><button class="primary small" @click="saveFacts">Tallenna</button><button class="ghost small" @click="editFacts = false; load()">Peruuta</button></span></div>
        <div class="facts">
          <div class="fact"><div class="k">Henkilöstö</div><div class="v"><input v-if="editFacts" v-model="facts.employees" type="number" min="0" /><template v-else>{{ company.employees ?? '—' }}</template></div></div>
          <div class="fact"><div class="k">Liikevaihto</div><div class="v"><input v-if="editFacts" v-model="facts.revenue_eur" type="number" min="0" placeholder="€" /><template v-else>{{ company.revenue_eur !== null && company.revenue_eur !== undefined ? fmtEur(company.revenue_eur) : '—' }}</template></div></div>
          <div class="fact"><div class="k">Perustettu</div><div class="v"><input v-if="editFacts" v-model="facts.founded_year" type="number" /><template v-else>{{ company.founded_year ?? (company.registration_date ? fmtDate(company.registration_date) : '—') }}</template></div></div>
          <div class="fact"><div class="k">Toimiala</div><div class="v"><input v-if="editFacts" v-model="facts.industry_label" /><template v-else>{{ company.industry_label || '—' }}<div class="muted small">{{ company.industry_code }}</div></template></div></div>
          <div class="fact"><div class="k">Puhelin (vaihde)</div><div class="v"><input v-if="editFacts" v-model="facts.phone" /><template v-else>{{ company.phone || '—' }}</template></div></div>
          <div class="fact"><div class="k">Sähköposti</div><div class="v"><input v-if="editFacts" v-model="facts.email" /><template v-else>{{ company.email || '—' }}</template></div></div>
          <div class="fact"><div class="k">Verkkosivu</div><div class="v"><input v-if="editFacts" v-model="facts.website" /><template v-else><a v-if="site" :href="site" target="_blank" rel="noopener">{{ company.website }}</a><span v-else>—</span></template></div></div>
          <div class="fact"><div class="k">LinkedIn</div><div class="v"><input v-if="editFacts" v-model="facts.linkedin_url" /><template v-else><a v-if="company.linkedin_url" :href="company.linkedin_url" target="_blank" rel="noopener">Profiili</a><span v-else>—</span></template></div></div>
          <div class="fact" style="grid-column: span 2"><div class="k">Osoite</div><div class="v"><div v-if="editFacts" class="row"><input v-model="facts.street_address" placeholder="Katu" /><input v-model="facts.postal_code" placeholder="Postinro" style="width:90px" /><input v-model="facts.city" placeholder="Kaupunki" /></div><template v-else>{{ [company.street_address, company.postal_code, company.city].filter(Boolean).join(', ') || '—' }}</template></div></div>
          <div class="fact"><div class="k">Omistaja (myyjä)</div><div class="v"><select :value="company.owner_id ?? ''" @change="setOwner(($event.target as HTMLSelectElement).value)"><option value="">—</option><option v-for="o in facets?.owners ?? []" :key="o.id" :value="o.id">{{ o.name }}</option></select></div></div>
          <div class="fact"><div class="k">Lähde</div><div class="v">{{ company.source }}<div class="muted small">päivitetty {{ fmtDate(company.updated_at) }}</div></div></div>
        </div>
        <div style="margin-top:0.8rem">
          <div class="fact"><div class="k">Kuvaus</div><div class="v" style="font-weight:400"><textarea v-if="editFacts" v-model="facts.description" /><template v-else>{{ company.description || '—' }}</template></div></div>
        </div>
        <div style="margin-top:0.6rem">
          <div class="fact"><div class="k">Teknologiat</div><div class="v"><input v-if="editFacts" v-model="facts.technologies" placeholder="pilkuilla eroteltuna, esim. Shopify, HubSpot" /><template v-else><span v-for="t in company.technologies ?? []" :key="t" class="tag" style="margin-right:0.3rem">{{ t }}</span><span v-if="!company.technologies?.length">—</span></template></div></div>
        </div>
      </div>
      <div class="grid2">
        <div class="card">
          <h2>Päättäjät</h2>
          <div v-if="!company.contacts.length" class="muted small">Ei yhteyshenkilöitä vielä.</div>
          <div v-for="c in company.contacts.slice(0, 5)" :key="c.id" class="row" style="padding:0.35rem 0; border-bottom:1px solid var(--line)">
            <div style="flex:1"><strong>{{ c.name || 'Yleinen numero' }}</strong> <span class="muted small">{{ c.title }}</span></div>
            <a v-if="c.phone_e164" :href="'tel:' + c.phone_e164" class="small">{{ c.phone_e164 }}</a>
          </div>
          <button class="ghost small" style="margin-top:0.5rem" @click="tab = 'people'">Kaikki henkilöt →</button>
        </div>
        <div class="card">
          <h2>Tilanne</h2>
          <div class="facts" style="grid-template-columns:1fr 1fr 1fr">
            <div class="fact"><div class="k">Soittoja</div><div class="v">{{ company.calls.length }}</div></div>
            <div class="fact"><div class="k">Bookkauksia</div><div class="v">{{ company.bookings.length }}</div></div>
            <div class="fact"><div class="k">Viim. soitto</div><div class="v">{{ company.calls[0] ? fmtDate(company.calls[0].started_at) : '—' }}</div></div>
          </div>
          <h3 style="margin-top:0.8rem">Sekvenssit</h3>
          <div v-if="!seqs.length" class="muted small">Ei ketjussa.</div>
          <div v-for="s in seqs" :key="s.id" class="small row" style="gap:0.4rem">
            <router-link to="/sekvenssit">{{ s.sequence_name }}</router-link> · {{ s.current_step }}/{{ s.step_count }}
            <span class="tag" :class="{ info: s.status === 'active', ok: s.status === 'finished', warn: s.status === 'stopped', danger: s.status === 'failed' }">{{ s.status === 'active' ? (s.next_at ? 'seuraava ' + fmtDateTime(s.next_at) : 'käynnissä') : s.finished_reason }}</span>
            <button v-if="s.status === 'active'" class="ghost small" @click="stopSeq(s.id)">Lopeta</button>
          </div>
          <h3 style="margin-top:0.8rem">Soittojonossa</h3>
          <div v-if="!company.tasks.length" class="muted small">Ei missään kampanjassa.</div>
          <div v-for="t in company.tasks" :key="t.id" class="small">{{ t.campaign_name }} · <span class="tag">{{ t.status }}</span> · {{ t.attempts }} yritystä · {{ fmtDateTime(t.due_at) }}</div>
        </div>
      </div>
    </div>

    <!-- people -->
    <div v-if="tab === 'people'">
      <div class="table-wrap" style="margin-bottom:1rem">
        <table>
          <thead><tr><th>Henkilö</th><th>Titteli</th><th>Osasto</th><th>Taso</th><th>Puhelin</th><th>Sähköposti</th><th>Lähde</th><th></th></tr></thead>
          <tbody>
            <template v-for="c in company.contacts" :key="c.id">
              <tr v-if="editContact !== c.id">
                <td><strong>{{ c.name || 'Yleinen numero' }}</strong><span v-if="c.is_primary" class="tag" style="margin-left:0.3rem">ensisij.</span><span v-if="c.verified_at" class="tag ok" style="margin-left:0.3rem" :title="'Vahvistettu ' + fmtDate(c.verified_at)">✓</span><div v-if="c.linkedin_url" class="small"><a :href="c.linkedin_url" target="_blank" rel="noopener">LinkedIn</a></div></td>
                <td class="small">{{ c.title || '—' }}</td>
                <td class="small">{{ c.department || '—' }}</td>
                <td class="small">{{ c.management_level ? LEVEL_LABELS[c.management_level] : '—' }}</td>
                <td class="nowrap"><a v-if="c.phone_e164" :href="'tel:' + c.phone_e164">{{ c.phone_e164 }}</a><span v-else class="muted">—</span><span v-if="c.do_not_call" class="tag danger" style="margin-left:0.3rem">kielto</span></td>
                <td class="small"><a v-if="c.email" :href="'mailto:' + c.email">{{ c.email }}</a><span v-else class="muted">—</span></td>
                <td class="small muted">{{ c.source }}<template v-if="c.confidence !== null"> · {{ Math.round(Number(c.confidence) * 100) }} %</template></td>
                <td class="nowrap">
                  <button class="ghost small" @click="startEdit(c)">Muokkaa</button>
                  <button v-if="!c.is_primary" class="ghost small" title="Tee ensisijaiseksi" @click="contactAction(c, { is_primary: true })">★</button>
                  <button v-if="!c.verified_at" class="ghost small" title="Merkitse numero vahvistetuksi" @click="contactAction(c, { verified: true })">✓</button>
                  <button class="ghost small" @click="deleteContact(c)">✕</button>
                </td>
              </tr>
              <tr v-else>
                <td colspan="8">
                  <div class="row">
                    <input v-model="ec.name" placeholder="Nimi" style="width:160px" /><input v-model="ec.title" placeholder="Titteli" style="width:160px" />
                    <input v-model="ec.department" placeholder="Osasto" style="width:120px" />
                    <select v-model="ec.management_level" style="width:auto"><option value="">Taso</option><option v-for="(l, k) in LEVEL_LABELS" :key="k" :value="k">{{ l }}</option></select>
                    <input v-model="ec.phone" placeholder="Puhelin" style="width:140px" /><input v-model="ec.email" placeholder="Sähköposti" style="width:200px" /><input v-model="ec.linkedin_url" placeholder="LinkedIn-osoite" style="width:200px" />
                    <button class="primary small" @click="saveContact">Tallenna</button><button class="ghost small" @click="editContact = null">Peruuta</button>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
        <div v-if="!company.contacts.length" class="empty">Ei yhteyshenkilöitä. Lisää alla tai anna agentin etsiä päättäjät.</div>
      </div>
      <div class="card">
        <h2>Lisää henkilö</h2>
        <div class="row">
          <input v-model="nc.name" placeholder="Nimi" style="width:160px" /><input v-model="nc.title" placeholder="Titteli" style="width:160px" />
          <input v-model="nc.department" placeholder="Osasto" style="width:120px" />
          <select v-model="nc.management_level" style="width:auto"><option value="">Taso</option><option v-for="(l, k) in LEVEL_LABELS" :key="k" :value="k">{{ l }}</option></select>
          <input v-model="nc.phone" placeholder="Puhelin" style="width:140px" /><input v-model="nc.email" placeholder="Sähköposti" style="width:200px" />
          <button class="primary" :disabled="!nc.phone && !nc.email && !nc.name" @click="addContact">Lisää</button>
        </div>
      </div>
    </div>

    <!-- activity -->
    <div v-if="tab === 'activity'" class="card">
      <h2>Toiminta</h2>
      <div v-if="!timeline.length" class="muted small">Ei soittoja eikä bookkauksia.</div>
      <ul class="timeline">
        <li v-for="(t, i) in timeline" :key="i">
          <div class="when">{{ fmtDateTime(t.at) }}</div>
          <div v-if="t.kind === 'call' && t.call">
            <strong>{{ OUTCOME_LABELS[t.call.outcome as keyof typeof OUTCOME_LABELS] ?? t.call.outcome }}</strong>
            <span class="muted small"> · {{ t.call.user_name }}<template v-if="t.call.contact_name || t.call.phone_dialed"> → {{ t.call.contact_name || t.call.phone_dialed }}</template><template v-if="t.call.callback_at"> · soita uudelleen {{ fmtDateTime(t.call.callback_at) }}</template></span>
            <div v-if="t.call.notes" class="small" style="white-space:pre-wrap">{{ t.call.notes }}</div>
            <div class="small"><a href="#" @click.prevent="openCall = openCall === t.call.id ? null : t.call.id">{{ openCall === t.call.id ? 'Sulje analyysi' : 'Analyysi ja nauhoite' }}</a></div>
            <CallAnalysisPanel v-if="openCall === t.call.id" :call-id="t.call.id" :has-notes="!!t.call.notes" />
          </div>
          <div v-else-if="t.booking">
            <strong>Bookkaus: {{ t.booking.product }}</strong> <span class="tag" :class="{ ok: t.booking.status === 'completed' || t.booking.status === 'confirmed', danger: t.booking.status === 'cancelled' || t.booking.status === 'no_show' }">{{ t.booking.status }}</span>
            <div class="muted small">{{ fmtDateTime(t.booking.scheduled_at) }} · {{ fmtEur(t.booking.value_eur) }}<template v-if="t.booking.notes"> · {{ t.booking.notes }}</template></div>
          </div>
        </li>
      </ul>
    </div>

    <!-- notes -->
    <div v-if="tab === 'notes'" class="card">
      <h2>Muistiinpanot</h2>
      <textarea v-model="notes" style="min-height:220px" />
      <button class="primary" style="margin-top:0.5rem" @click="saveNotes">Tallenna</button>
    </div>
  </div>

  <AddToListModal v-if="showList && company" kind="company" :company-ids="[company.id]" @close="showList = false" @added="showList = false; load()" />
  <EnrollModal v-if="showEnroll && company" :company-ids="[company.id]" @close="showEnroll = false" @enrolled="(r) => { showEnroll = false; notice = r.enrolled ? `Lisätty ketjuun ”${r.sequence.name}”` : 'On jo tässä ketjussa'; load() }" />
</template>
