<script setup lang="ts">
/** Sequences: list on the left, editor or detail on the right. A sequence is
 *  an ordered chain of touches (email / call / task) with a delay before each. */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet, apiPost, apiPut, errorText } from '../api/client'
import type { Campaign, Outcome, Sequence, SequenceDetail, SequenceStep, StepKind } from '../api/types'
import { OUTCOME_LABELS, STEP_LABELS } from '../api/types'
import { fmtDate, fmtDateTime } from '../format'
import { SEQUENCE_TEMPLATES, type SequenceTemplate } from '../sequenceTemplates'

const router = useRouter()
const sequences = ref<Sequence[]>([])
const campaigns = ref<Campaign[]>([])
const open = ref<SequenceDetail | null>(null)
const editing = ref(false)
const form = ref<{ name: string; description: string; campaign_id: string; status: Sequence['status']; stop_on_outcomes: string[]; steps: SequenceStep[] } | null>(null)
const error = ref('')
const notice = ref('')
const tab = ref<'steps' | 'enrollments'>('steps')
const pickingTemplate = ref(false)

const VARS = ['{{etunimi}}', '{{nimi}}', '{{yritys}}', '{{paikkakunta}}', '{{titteli}}', '{{myyja}}', '{{tuote}}']
const STOPPABLE: Outcome[] = ['booked', 'not_interested', 'do_not_call', 'already_customer', 'callback', 'wrong_number']

async function load() {
  try {
    sequences.value = await apiGet<Sequence[]>('/sequences')
    campaigns.value = (await apiGet<Campaign[]>('/campaigns')).filter((c) => c.status === 'active')
  } catch (e) { error.value = errorText(e) }
}
onMounted(async () => { await load(); if (sequences.value[0]) await show(sequences.value[0].id) })

async function show(id: string) {
  editing.value = false
  tab.value = 'steps'
  open.value = await apiGet<SequenceDetail>(`/sequences/${id}`)
}
function startNew() {
  pickingTemplate.value = true
}
function startFromTemplate(t: SequenceTemplate | null) {
  pickingTemplate.value = false
  open.value = null
  form.value = {
    name: t ? t.name : '', description: t?.description ?? '', campaign_id: campaigns.value[0]?.id ?? '', status: 'active',
    stop_on_outcomes: ['booked', 'not_interested', 'do_not_call', 'already_customer'],
    steps: t ? t.steps.map((st) => ({ ...st })) : [{ kind: 'email', delay_days: 0, delay_hours: 0, title: '', body: '' }, { kind: 'call', delay_days: 2, delay_hours: 0, title: null, body: null }],
  }
  editing.value = true
}
function startEdit() {
  if (!open.value) return
  form.value = {
    name: open.value.name, description: open.value.description ?? '', campaign_id: open.value.campaign_id ?? '', status: open.value.status,
    stop_on_outcomes: [...open.value.stop_on_outcomes], steps: open.value.steps.map((s) => ({ ...s })),
  }
  editing.value = true
}
function addStep(kind: StepKind) {
  form.value?.steps.push({ kind, delay_days: kind === 'call' ? 2 : 3, delay_hours: 0, title: kind === 'email' ? 'Re: {{yritys}}' : kind === 'task' ? 'LinkedIn-yhteys {{nimi}}' : null, body: null })
}
function move(i: number, d: number) {
  const s = form.value!.steps
  const j = i + d
  if (j < 0 || j >= s.length) return
  ;[s[i], s[j]] = [s[j], s[i]]
}
async function save() {
  if (!form.value) return
  error.value = ''
  try {
    const body = { ...form.value, campaign_id: form.value.campaign_id || null, description: form.value.description || null }
    const saved = open.value && open.value.id ? await apiPut<SequenceDetail>(`/sequences/${open.value.id}`, body) : await apiPost<SequenceDetail>('/sequences', body)
    await load()
    await show(saved.id)
    notice.value = 'Tallennettu'
  } catch (e) { error.value = errorText(e) }
}
async function stop(id: string) {
  await apiPost(`/sequences/enrollments/${id}/stop`)
  if (open.value) await show(open.value.id)
}
async function runNow() {
  await apiPost('/sequences/tick')
  if (open.value) await show(open.value.id)
  notice.value = 'Erääntyneet askeleet ajettu'
}
const totalDays = computed(() => form.value?.steps.reduce((s, x) => s + x.delay_days, 0) ?? 0)
const stepIcon = (k: StepKind) => (k === 'call' ? '📞' : k === 'email' ? '✉️' : '☑️')
const statusTag = (s: string) => ({ ok: s === 'finished', info: s === 'active', warn: s === 'stopped', danger: s === 'failed' })
const STATUS: Record<string, string> = { active: 'Käynnissä', finished: 'Valmis', stopped: 'Lopetettu', failed: 'Virhe' }
</script>

<template>
  <div class="page-head">
    <div><h1>Sekvenssit</h1><p class="muted small">Ketju kosketuksia samalle liidille: sähköposti → soitto → sähköposti → soitto. Soitot putkahtavat kampanjan jonoon, sähköpostit ja tehtävät <router-link to="/tehtavat">Tehtävät</router-link>-sivulle. Ketju pysähtyy itsestään kun puhelu päättyy esim. bookkaukseen.</p></div>
    <div class="row"><button class="small ghost" @click="runNow">Aja erääntyneet nyt</button><button class="primary" @click="startNew">+ Uusi sekvenssi</button></div>
  </div>
  <p v-if="error" class="error">{{ error }}</p>

  <div v-if="pickingTemplate" class="modal" @click.self="pickingTemplate = false">
    <div class="box" style="width: min(640px, 94vw)">
      <h2>Mistä aloitetaan?</h2>
      <p class="muted small">Valitse pohja – kaikki tekstit ja viiveet voi muokata seuraavassa näkymässä.</p>
      <div v-for="t in SEQUENCE_TEMPLATES" :key="t.id" class="tpl" @click="startFromTemplate(t)">
        <strong>{{ t.name }}</strong> <span class="muted small">· {{ t.steps.length }} askelta · {{ t.steps.reduce((a, x) => a + x.delay_days, 0) }} pv</span>
        <div class="small muted">{{ t.description }}</div>
        <div class="small">{{ t.steps.map((x) => x.kind === 'call' ? '📞' : x.kind === 'email' ? '✉️' : '☑️').join(' → ') }}</div>
      </div>
      <div class="tpl" @click="startFromTemplate(null)"><strong>Tyhjästä</strong><div class="small muted">Rakenna itse.</div></div>
      <div class="row" style="justify-content: flex-end; margin-top: 0.5rem"><button class="ghost" @click="pickingTemplate = false">Peruuta</button></div>
    </div>
  </div>

  <div class="seqgrid">
    <aside>
      <div v-if="!sequences.length" class="empty small">Ei sekvenssejä vielä.</div>
      <div v-for="s in sequences" :key="s.id" class="seqcard" :class="{ on: open?.id === s.id }" @click="show(s.id)">
        <div class="row" style="justify-content: space-between"><strong>{{ s.name }}</strong><span class="tag" :class="{ ok: s.status === 'active', warn: s.status === 'paused' }">{{ s.status === 'active' ? 'Aktiivinen' : 'Tauolla' }}</span></div>
        <div class="small muted">{{ s.step_count }} askelta · {{ s.campaign_name || 'ei kampanjaa' }}</div>
        <div class="small"><span class="tag info">{{ s.active_count }} käynnissä</span> <span class="tag ok">{{ s.booked_count }} bookattu</span> <span class="tag">{{ s.finished_count }} valmis</span></div>
      </div>
    </aside>

    <section>
      <!-- editor -->
      <div v-if="editing && form" class="card">
        <h2>{{ open ? 'Muokkaa sekvenssiä' : 'Uusi sekvenssi' }}</h2>
        <div class="grid2">
          <div class="field"><label>Nimi</label><input v-model="form.name" placeholder="esim. Ravintolat – esittelyketju" /></div>
          <div class="field"><label>Kampanja (soittoaskeleet tähän jonoon)</label><select v-model="form.campaign_id"><option value="">—</option><option v-for="c in campaigns" :key="c.id" :value="c.id">{{ c.name }}</option></select></div>
          <div class="field"><label>Kuvaus</label><input v-model="form.description" /></div>
          <div class="field"><label>Tila</label><select v-model="form.status"><option value="active">Aktiivinen</option><option value="paused">Tauolla (askeleet odottavat)</option><option value="archived">Arkistoitu</option></select></div>
        </div>
        <div class="field">
          <label>Ketju pysähtyy, kun puhelu päättyy:</label>
          <div class="row">
            <label v-for="o in STOPPABLE" :key="o" class="check" style="margin: 0; color: inherit"><input type="checkbox" :value="o" v-model="form.stop_on_outcomes" /> {{ OUTCOME_LABELS[o] }}</label>
          </div>
        </div>

        <h3 style="margin-top: 1rem">Askeleet <span class="muted small">· yhteensä {{ totalDays }} päivää</span></h3>
        <p class="muted small">Muuttujat teksteissä: <code v-for="v in VARS" :key="v" style="margin-right: 0.4rem">{{ v }}</code></p>
        <div v-for="(st, i) in form.steps" :key="i" class="step">
          <div class="stephead">
            <span class="num">{{ i + 1 }}</span>
            <select v-model="st.kind" style="width: auto"><option v-for="(l, k) in STEP_LABELS" :key="k" :value="k">{{ stepIcon(k as StepKind) }} {{ l }}</option></select>
            <span class="muted small">{{ i === 0 ? 'heti / viive aloituksesta' : 'edellisen jälkeen' }}</span>
            <input v-model.number="st.delay_days" type="number" min="0" style="width: 64px" /><span class="small">pv</span>
            <input v-model.number="st.delay_hours" type="number" min="0" max="23" style="width: 64px" /><span class="small">h</span>
            <span style="flex: 1"></span>
            <button class="ghost small" @click="move(i, -1)">↑</button><button class="ghost small" @click="move(i, 1)">↓</button><button class="ghost small" @click="form.steps.splice(i, 1)">✕</button>
          </div>
          <div v-if="st.kind === 'email'" class="stepbody">
            <input v-model="st.title" placeholder="Aihe" />
            <textarea v-model="st.body" style="min-height: 110px" placeholder="Viesti. Lyhyt, yksi kysymys, ei myyntipuhetta." />
          </div>
          <div v-else-if="st.kind === 'task'" class="stepbody">
            <input v-model="st.title" placeholder="Tehtävä, esim. LinkedIn-yhteyspyyntö" />
            <textarea v-model="st.body" style="min-height: 60px" placeholder="Ohje myyjälle" />
          </div>
          <div v-else class="stepbody muted small">Soitto menee kampanjan jonoon etusijalla. Puhelun tulos ohjaa ketjua.</div>
        </div>
        <div class="row" style="margin: 0.5rem 0 1rem">
          <button class="small" @click="addStep('email')">+ Sähköposti</button><button class="small" @click="addStep('call')">+ Soitto</button><button class="small" @click="addStep('task')">+ Tehtävä</button>
        </div>
        <div class="row"><button class="primary" :disabled="!form.name.trim() || !form.steps.length" @click="save">Tallenna</button><button class="ghost" @click="editing = false; if (!open) load()">Peruuta</button></div>
      </div>

      <!-- detail -->
      <div v-else-if="open">
        <div class="card">
          <div class="row" style="justify-content: space-between">
            <div><h2 style="margin: 0">{{ open.name }}</h2><div class="muted small">{{ open.description }} · {{ open.campaign_name || 'ei kampanjaa' }} · {{ open.owner_name }}</div></div>
            <div class="row"><span v-if="notice" class="tag ok">{{ notice }}</span><button class="small" @click="startEdit">Muokkaa</button></div>
          </div>
          <div class="kpis" style="margin-top: 0.75rem">
            <div class="kpi"><div class="n">{{ open.active_count }}</div><div class="muted small">Käynnissä</div></div>
            <div class="kpi"><div class="n">{{ open.booked_count }}</div><div class="muted small">Bookattu</div></div>
            <div class="kpi"><div class="n">{{ open.finished_count }}</div><div class="muted small">Läpi ilman tulosta</div></div>
            <div class="kpi"><div class="n">{{ open.stopped_count }}</div><div class="muted small">Pysäytetty</div></div>
          </div>
        </div>
        <div class="tabs">
          <button :class="{ on: tab === 'steps' }" @click="tab = 'steps'">Askeleet<span class="n">{{ open.steps.length }}</span></button>
          <button :class="{ on: tab === 'enrollments' }" @click="tab = 'enrollments'">Ketjussa<span class="n">{{ open.enrollments.length }}</span></button>
        </div>
        <div v-if="tab === 'steps'" class="card">
          <ol class="flow">
            <li v-for="st in open.steps" :key="st.id">
              <span class="num">{{ st.position }}</span>
              <div>
                <strong>{{ stepIcon(st.kind) }} {{ STEP_LABELS[st.kind] }}</strong>
                <span class="muted small"> · {{ st.position === 1 ? 'aloituksesta' : 'edellisestä' }} {{ st.delay_days }} pv{{ st.delay_hours ? ` ${st.delay_hours} h` : '' }}</span>
                <div v-if="st.title" class="small"><strong>{{ st.title }}</strong></div>
                <div v-if="st.body" class="small muted" style="white-space: pre-wrap">{{ st.body }}</div>
              </div>
            </li>
          </ol>
          <p class="muted small">Pysähtyy kun puhelu päättyy: {{ open.stop_on_outcomes.map((o) => OUTCOME_LABELS[o as Outcome] ?? o).join(', ') }}</p>
        </div>
        <div v-else class="table-wrap">
          <table>
            <thead><tr><th>Yritys</th><th>Henkilö</th><th>Askel</th><th>Tila</th><th>Seuraava</th><th>Aloitti</th><th></th></tr></thead>
            <tbody>
              <tr v-for="e in open.enrollments" :key="e.id" class="clickable" @click="router.push(`/yritykset/${e.company_id}`)">
                <td><strong>{{ e.company_name }}</strong><div class="small muted">{{ e.city || '' }}</div></td>
                <td class="small">{{ e.contact_name || '—' }}<div class="muted">{{ e.contact_email || '' }}</div></td>
                <td class="mono">{{ e.current_step }} / {{ open.steps.length }}</td>
                <td><span class="tag" :class="statusTag(e.status)">{{ STATUS[e.status] }}</span><div v-if="e.finished_reason" class="small muted">{{ e.finished_reason }}</div></td>
                <td class="small nowrap">{{ e.next_at ? fmtDateTime(e.next_at) : '—' }}</td>
                <td class="small muted">{{ e.started_by_name }} · {{ fmtDate(e.created_at) }}</td>
                <td @click.stop><button v-if="e.status === 'active'" class="ghost small" @click="stop(e.id)">Lopeta</button></td>
              </tr>
            </tbody>
          </table>
          <div v-if="!open.enrollments.length" class="empty">Kukaan ei ole vielä ketjussa. Rastita yrityksiä <router-link to="/haku">hausta</router-link> ja valitse ”Sekvenssiin”.</div>
        </div>
      </div>
      <div v-else class="empty">Valitse sekvenssi vasemmalta tai luo uusi.</div>
    </section>
  </div>
</template>

<style scoped>
.seqgrid { display: grid; grid-template-columns: 300px 1fr; gap: 1rem; align-items: start; }
.seqcard { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 0.7rem 0.9rem; margin-bottom: 0.5rem; cursor: pointer; }
.seqcard.on { border-color: var(--accent); box-shadow: inset 3px 0 0 var(--accent); }
.step { border: 1px solid var(--line); border-radius: 8px; padding: 0.6rem 0.8rem; margin-bottom: 0.5rem; background: var(--surface-2); }
.stephead { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.stepbody { margin-top: 0.5rem; display: flex; flex-direction: column; gap: 0.4rem; }
.num { width: 24px; height: 24px; border-radius: 50%; background: var(--accent); color: var(--accent-ink); display: inline-grid; place-items: center; font-size: 0.75rem; font-weight: 700; flex: none; }
.flow { list-style: none; padding: 0; margin: 0; }
.flow li { display: flex; gap: 0.75rem; padding: 0.6rem 0; border-left: 2px solid var(--line); margin-left: 11px; padding-left: 0.75rem; position: relative; }
.flow li .num { position: absolute; left: -13px; top: 0.6rem; }
.flow li > div { padding-left: 0.6rem; }
label.check { display: inline-flex; align-items: center; gap: 0.3rem; font-size: 0.84rem; }
.tpl { border: 1px solid var(--line); border-radius: 8px; padding: 0.6rem 0.8rem; margin-bottom: 0.5rem; cursor: pointer; }
.tpl:hover { border-color: var(--accent); background: var(--accent-soft); }
@media (max-width: 900px) { .seqgrid { grid-template-columns: 1fr; } }
</style>
