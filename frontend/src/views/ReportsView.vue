<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { apiGet, errorText } from '../api/client'
import type { Stats } from '../api/types'
import { OUTCOME_LABELS } from '../api/types'
import { fmtDate, fmtMinutes } from '../format'

const stats = ref<Stats | null>(null)
const days = ref(7)
const error = ref('')

async function load() {
  try {
    stats.value = await apiGet<Stats>('/stats/overview', { days: days.value })
  } catch (e) {
    error.value = errorText(e)
  }
}
onMounted(load)

const totals = computed(() => {
  if (!stats.value) return null
  const t = { calls: 0, conversations: 0, booked: 0, callbacks: 0 }
  for (const u of stats.value.per_user) { t.calls += u.calls; t.conversations += u.conversations; t.booked += u.booked; t.callbacks += u.callbacks }
  return t
})
const maxDaily = computed(() => Math.max(1, ...(stats.value?.daily.map((d) => d.calls) ?? [1])))
function pct(a: number, b: number) {
  return b ? `${Math.round((100 * a) / b)} %` : '—'
}
</script>

<template>
  <h1>Raportit</h1>
  <div class="row" style="margin-bottom: 1rem">
    <select v-model.number="days" style="width: auto" @change="load">
      <option :value="1">Tänään</option><option :value="7">7 päivää</option><option :value="30">30 päivää</option><option :value="90">90 päivää</option>
    </select>
  </div>
  <p v-if="error" class="error">{{ error }}</p>

  <div v-if="stats && totals">
    <div class="kpis" style="margin-bottom: 1rem">
      <div class="kpi"><div class="muted small">Soittoja</div><div class="n">{{ totals.calls }}</div></div>
      <div class="kpi"><div class="muted small">Keskusteluja</div><div class="n">{{ totals.conversations }}</div><div class="small muted">{{ pct(totals.conversations, totals.calls) }} soitoista</div></div>
      <div class="kpi"><div class="muted small">Bookkauksia</div><div class="n">{{ totals.booked }}</div><div class="small muted">{{ pct(totals.booked, totals.conversations) }} keskusteluista</div></div>
      <div class="kpi"><div class="muted small">Takaisinsoittoja</div><div class="n">{{ totals.callbacks }}</div></div>
      <div class="kpi"><div class="muted small">Jonossa nyt</div><div class="n">{{ (stats.queue.queued ?? 0) + (stats.queue.callback ?? 0) }}</div><div class="small muted">{{ stats.queue.done ?? 0 }} valmiina</div></div>
    </div>

    <div class="grid2">
      <div class="card">
        <h2>Soittajat</h2>
        <div v-if="!totals.calls" class="muted small">Ei soittoja jaksolla.</div>
        <table v-else class="small">
          <tr><th>Soittaja</th><th>Soittoja</th><th>Keskust.</th><th>Bookattu</th><th>Osuma</th><th>Puheaika</th></tr>
          <tr v-for="u in stats.per_user" :key="u.user_id">
            <td>{{ u.name }}</td><td>{{ u.calls }}</td><td>{{ u.conversations }}</td><td><strong>{{ u.booked }}</strong></td>
            <td>{{ pct(u.booked, u.conversations) }}</td><td>{{ fmtMinutes(u.talk_seconds) }}</td>
          </tr>
        </table>
      </div>
      <div class="card">
        <h2>Lopputulokset</h2>
        <div v-if="!stats.outcomes.length" class="muted small">Ei soittoja jaksolla.</div>
        <table v-else class="small">
          <tr v-for="o in stats.outcomes" :key="o.outcome">
            <td>{{ OUTCOME_LABELS[o.outcome as keyof typeof OUTCOME_LABELS] ?? o.outcome }}</td>
            <td style="width: 40%"><div class="bar"><i :style="{ width: (100 * o.n) / totals.calls + '%' }" /></div></td>
            <td>{{ o.n }}</td>
          </tr>
        </table>
      </div>
    </div>

    <div class="card" v-if="stats.daily.length">
      <h2>Päivittäin</h2>
      <table class="small">
        <tr v-for="d in stats.daily" :key="d.day">
          <td style="width: 90px">{{ fmtDate(d.day) }}</td>
          <td><div class="bar"><i :style="{ width: (100 * d.calls) / maxDaily + '%' }" /></div></td>
          <td style="width: 160px">{{ d.calls }} soittoa · {{ d.booked }} bookattu</td>
        </tr>
      </table>
    </div>
  </div>
</template>
