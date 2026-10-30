<script setup lang="ts">
/** Tänään: the seller's landing page. What is waiting (queue, callbacks, tasks,
 *  meetings), how the day is going, and one big button to start calling. */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet, errorText } from '../api/client'
import type { Booking, Callback, DayStats, QueueSummary, SequenceAction } from '../api/types'
import { fmtEur, fmtMinutes } from '../format'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const queue = ref<QueueSummary | null>(null)
const day = ref<DayStats | null>(null)
const callbacks = ref<Callback[]>([])
const tasks = ref<SequenceAction[]>([])
const bookings = ref<Booking[]>([])
const error = ref('')
const now = Date.now()

onMounted(async () => {
  try {
    ;[queue.value, day.value, callbacks.value, tasks.value, bookings.value] = await Promise.all([
      apiGet<QueueSummary>('/calls/queue'), apiGet<DayStats>('/stats/day'), apiGet<Callback[]>('/calls/callbacks'),
      apiGet<SequenceAction[]>('/sequences/inbox', { status: 'open', mine: true, limit: 20 }), apiGet<Booking[]>('/bookings', { limit: 200 }),
    ])
  } catch (e) { error.value = errorText(e) }
})
const me = computed(() => day.value?.per_user.find((u) => u.user_id === day.value?.me) ?? null)
const overdue = computed(() => callbacks.value.filter((c) => new Date(c.due_at).getTime() < now))
const today = computed(() => callbacks.value.filter((c) => new Date(c.due_at).getTime() >= now && new Date(c.due_at).toDateString() === new Date().toDateString()))
const upcoming = computed(() => bookings.value
  .filter((b) => (b.status === 'booked' || b.status === 'confirmed') && b.scheduled_at && new Date(b.scheduled_at).getTime() >= now)
  .sort((a, b) => (a.scheduled_at! < b.scheduled_at! ? -1 : 1)).slice(0, 5))
const greeting = computed(() => {
  const h = new Date().getHours()
  const name = (auth.me?.name ?? '').split(' ')[0]
  return (h < 10 ? 'Huomenta' : h < 17 ? 'Päivää' : 'Iltaa') + (name ? `, ${name}` : '')
})
const nothingToDo = computed(() => queue.value && queue.value.due_now === 0 && queue.value.callbacks_due === 0 && !tasks.value.length)
function hhmm(iso: string | null | undefined) { return iso ? new Date(iso).toLocaleTimeString('fi-FI', { hour: '2-digit', minute: '2-digit' }) : '' }
function dayLabel(iso: string) {
  const d = new Date(iso); const t = new Date(); const tomorrow = new Date(); tomorrow.setDate(t.getDate() + 1)
  if (d.toDateString() === t.toDateString()) return 'tänään'
  if (d.toDateString() === tomorrow.toDateString()) return 'huomenna'
  return d.toLocaleDateString('fi-FI', { weekday: 'short', day: 'numeric', month: 'numeric' })
}
</script>

<template>
  <div class="page-head">
    <div><h1>{{ greeting }}</h1><p class="muted small">{{ new Date().toLocaleDateString('fi-FI', { weekday: 'long', day: 'numeric', month: 'long' }) }}</p></div>
    <div class="row">
      <button class="primary big" @click="router.push('/soita')">📞 Aloita soittaminen<span v-if="queue?.due_now" class="n"> · {{ queue.due_now }} jonossa</span></button>
    </div>
  </div>
  <p v-if="error" class="error">{{ error }}</p>

  <div class="kpis" style="margin-bottom: 1rem">
    <div class="kpi" :class="{ hot: overdue.length }"><div class="muted small">Erääntyneet takaisinsoitot</div><div class="n">{{ overdue.length }}</div><div class="small muted">{{ today.length }} lisää tänään</div></div>
    <div class="kpi"><div class="muted small">Jonossa nyt</div><div class="n">{{ queue?.due_now ?? '—' }}</div><div class="small muted">{{ queue?.waiting ?? 0 }} odottaa omaa aikaansa</div></div>
    <div class="kpi" :class="{ hot: tasks.length }"><div class="muted small">Tehtävät (meilit ym.)</div><div class="n">{{ tasks.length }}</div><div class="small muted"><router-link to="/tehtavat">avaa</router-link></div></div>
    <div class="kpi"><div class="muted small">Tänään soitettu</div><div class="n">{{ me?.calls ?? 0 }}</div><div class="small muted">{{ me?.conversations ?? 0 }} tavoitettu · {{ fmtMinutes(me?.talk_seconds ?? 0) }}</div></div>
    <div class="kpi" :class="{ good: (me?.booked ?? 0) > 0 }"><div class="muted small">Tänään bookattu</div><div class="n">{{ me?.booked ?? 0 }}</div><div class="small muted"><router-link to="/raportit">raportti</router-link></div></div>
  </div>

  <div v-if="nothingToDo" class="card" style="border-color: var(--ok)">
    <strong>Jono on tyhjä.</strong> Hae uusia yrityksiä <router-link to="/haku">Hausta</router-link> ja lisää ne soittojonoon, tai anna <router-link to="/prospektointi">Agentin</router-link> etsiä päättäjät valmiiksi.
  </div>

  <div class="grid2">
    <div class="card">
      <h2>Takaisinsoitot</h2>
      <div v-if="!callbacks.length" class="muted small">Ei sovittuja takaisinsoittoja. Kun asiakas sanoo ”soita ensi viikolla”, valitse puhelun lopuksi <em>Soita uudelleen</em>.</div>
      <div v-for="c in [...overdue, ...today, ...callbacks.filter((x) => !overdue.includes(x) && !today.includes(x))].slice(0, 8)" :key="c.task_id" class="row item" @click="router.push({ path: '/soita', query: { task: c.task_id } })">
        <span class="when" :class="{ error: new Date(c.due_at).getTime() < now }">{{ dayLabel(c.due_at) }} {{ hhmm(c.due_at) }}</span>
        <span style="flex: 1"><strong>{{ c.company_name }}</strong><span class="muted small"> {{ c.contact_name || '' }}</span></span>
        <button class="small primary">Soita →</button>
      </div>
    </div>
    <div>
      <div class="card">
        <h2>Tulevat tapaamiset</h2>
        <div v-if="!upcoming.length" class="muted small">Ei tulevia tapaamisia.</div>
        <div v-for="b in upcoming" :key="b.id" class="row item" @click="router.push('/yritykset/' + b.company_id)">
          <span class="when">{{ dayLabel(b.scheduled_at!) }} {{ hhmm(b.scheduled_at) }}</span>
          <span style="flex: 1"><strong>{{ b.company_name }}</strong><span class="muted small"> · {{ b.product }}<template v-if="b.location"> · {{ b.location }}</template><template v-if="b.value_eur"> · {{ fmtEur(b.value_eur) }}</template></span></span>
        </div>
      </div>
      <div class="card">
        <h2>Tehtävät</h2>
        <div v-if="!tasks.length" class="muted small">Ei odottavia tehtäviä.</div>
        <div v-for="t in tasks.slice(0, 6)" :key="t.id" class="row item" @click="router.push('/tehtavat')">
          <span class="when">{{ t.kind === 'email' ? 'Sähköposti' : 'Tehtävä' }}</span>
          <span style="flex: 1"><strong>{{ t.company_name }}</strong><span class="muted small"> · {{ t.subject || t.kind }}</span></span>
          <span v-if="t.status === 'failed'" class="tag danger">virhe</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.item { padding: 0.45rem 0; border-bottom: 1px solid var(--line); cursor: pointer; }
.item:hover { background: var(--surface-2); }
.when { width: 110px; flex: none; font-size: 0.82rem; color: var(--muted); font-variant-numeric: tabular-nums; }
.kpi.hot { border-color: var(--accent); }
.kpi.good { border-color: var(--ok); }
button.big .n { font-weight: 400; opacity: 0.85; }
</style>
