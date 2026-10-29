<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { apiGet, errorText } from '../api/client'
import type { DayStats, Stats } from '../api/types'
import { OUTCOME_LABELS } from '../api/types'
import { fmtDate, fmtEur, fmtMinutes } from '../format'

const stats = ref<Stats | null>(null)
const days = ref(7)
const error = ref('')
const tab = ref<'day' | 'period'>('day')
const day = ref<DayStats | null>(null)
const date = ref(new Date().toLocaleDateString('sv-SE'))  // yyyy-mm-dd in local time
const who = ref<string>('')

async function load() {
  try {
    stats.value = await apiGet<Stats>('/stats/overview', { days: days.value })
  } catch (e) {
    error.value = errorText(e)
  }
}
async function loadDay() {
  try {
    day.value = await apiGet<DayStats>('/stats/day', { date: date.value })
    if (!who.value) who.value = day.value.me ?? day.value.per_user[0]?.user_id ?? ''
  } catch (e) {
    error.value = errorText(e)
  }
}
onMounted(() => { loadDay(); load() })
function shiftDay(n: number) {
  const d = new Date(date.value); d.setDate(d.getDate() + n)
  date.value = d.toLocaleDateString('sv-SE')
  loadDay()
}
const mine = computed(() => day.value?.per_user.find((u) => u.user_id === who.value) ?? null)
const hours = computed(() => {
  const out: { hour: number; calls: number; conversations: number; booked: number }[] = []
  for (let h = 8; h <= 18; h++) {
    const row = day.value?.hourly.find((x) => x.user_id === who.value && x.hour === h)
    out.push({ hour: h, calls: row?.calls ?? 0, conversations: row?.conversations ?? 0, booked: row?.booked ?? 0 })
  }
  return out
})
const maxHour = computed(() => Math.max(1, ...hours.value.map((h) => h.calls)))
const myOutcomes = computed(() => (day.value?.outcomes.filter((o) => o.user_id === who.value) ?? []).sort((a, b) => b.n - a.n))
const myBookings = computed(() => day.value?.bookings.filter((b) => b.user_id === who.value) ?? [])
const baseline = computed(() => {
  const u = mine.value
  if (!u || !u.prev_days) return null
  return { calls: Math.round(u.prev_calls / u.prev_days), booked: (u.prev_booked / u.prev_days).toFixed(1) }
})
function delta(now: number, base: number | null) {
  if (base === null || base === undefined) return ''
  const d = now - base
  return d === 0 ? '± 0' : d > 0 ? `+${d}` : `${d}`
}
function hhmm(iso: string | null) { return iso ? new Date(iso).toLocaleTimeString('fi-FI', { hour: '2-digit', minute: '2-digit' }) : '—' }

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
  <div class="tabs">
    <button :class="{ on: tab === 'day' }" @click="tab = 'day'">Päivä</button>
    <button :class="{ on: tab === 'period' }" @click="tab = 'period'">Jakso</button>
  </div>
  <p v-if="error" class="error">{{ error }}</p>

  <!-- ------------------------------------------------ seller day -->
  <div v-if="tab === 'day'">
    <div class="row" style="margin-bottom: 1rem">
      <button class="small" @click="shiftDay(-1)">‹</button>
      <input v-model="date" type="date" style="width: auto" @change="loadDay" />
      <button class="small" :disabled="date >= new Date().toLocaleDateString('sv-SE')" @click="shiftDay(1)">›</button>
      <select v-model="who" style="width: auto">
        <option v-for="u in day?.per_user ?? []" :key="u.user_id" :value="u.user_id">{{ u.name }}{{ u.user_id === day?.me ? ' (minä)' : '' }}</option>
      </select>
      <span v-if="mine?.first_call_at" class="small muted">Ensimmäinen soitto {{ hhmm(mine.first_call_at) }} · viimeinen {{ hhmm(mine.last_call_at) }}</span>
    </div>

    <div v-if="mine" class="kpis" style="margin-bottom: 1rem">
      <div class="kpi"><div class="muted small">Soittoja</div><div class="n">{{ mine.calls }}</div><div class="small muted" v-if="baseline">{{ delta(mine.calls, baseline.calls) }} vs. 7 pv ka {{ baseline.calls }}</div></div>
      <div class="kpi"><div class="muted small">Tavoitettu</div><div class="n">{{ mine.conversations }}</div><div class="small muted">{{ pct(mine.conversations, mine.calls) }} soitoista</div></div>
      <div class="kpi"><div class="muted small">Bookattu</div><div class="n">{{ mine.booked }}</div><div class="small muted" v-if="baseline">7 pv ka {{ baseline.booked }} / pv</div></div>
      <div class="kpi"><div class="muted small">Soita uudelleen</div><div class="n">{{ mine.callbacks }}</div><div class="small muted">{{ day?.callbacks_due[who] ?? 0 }} erääntynyttä jonossa</div></div>
      <div class="kpi"><div class="muted small">Ei kiinnosta</div><div class="n">{{ mine.not_interested }}</div><div class="small muted">{{ pct(mine.not_interested, mine.conversations) }} tavoitetuista</div></div>
      <div class="kpi"><div class="muted small">Puheaika</div><div class="n">{{ fmtMinutes(mine.talk_seconds) }}</div><div class="small muted">{{ mine.conversations ? Math.round(mine.talk_seconds / mine.conversations / 60 * 10) / 10 + ' min / keskustelu' : '' }}</div></div>
    </div>
    <div v-else class="empty">Ei soittajia.</div>

    <div class="grid2">
      <div class="card">
        <h2>Tunneittain</h2>
        <table class="small">
          <tr v-for="h in hours" :key="h.hour">
            <td style="width: 60px" class="mono">{{ String(h.hour).padStart(2, '0') }}–{{ String(h.hour + 1).padStart(2, '0') }}</td>
            <td><div class="bar"><i :style="{ width: (100 * h.calls) / maxHour + '%' }" /></div></td>
            <td style="width: 190px" class="muted">{{ h.calls }} soittoa<template v-if="h.conversations"> · {{ h.conversations }} tavoitettu</template><strong v-if="h.booked"> · {{ h.booked }} bookattu</strong></td>
          </tr>
        </table>
      </div>
      <div>
        <div class="card">
          <h2>Lopputulokset</h2>
          <div v-if="!myOutcomes.length" class="muted small">Ei soittoja tänä päivänä.</div>
          <table v-else class="small">
            <tr v-for="o in myOutcomes" :key="o.outcome">
              <td>{{ OUTCOME_LABELS[o.outcome as keyof typeof OUTCOME_LABELS] ?? o.outcome }}</td>
              <td style="width: 40%"><div class="bar"><i :style="{ width: (100 * o.n) / (mine?.calls || 1) + '%' }" /></div></td>
              <td class="mono">{{ o.n }}</td>
            </tr>
          </table>
        </div>
        <div class="card">
          <h2>Päivän bookkaukset</h2>
          <div v-if="!myBookings.length" class="muted small">Ei bookkauksia vielä.</div>
          <div v-for="b in myBookings" :key="b.id" class="small" style="padding: 0.3rem 0; border-bottom: 1px solid var(--line)">
            <strong>{{ hhmm(b.created_at) }}</strong> <router-link :to="'/yritykset/' + b.company_id">{{ b.company_name }}</router-link> · {{ b.product }} · tapaaminen {{ b.scheduled_at ? fmtDate(b.scheduled_at) : '—' }}<template v-if="b.value_eur"> · {{ fmtEur(b.value_eur) }}</template>
          </div>
        </div>
      </div>
    </div>

    <div v-if="day && day.per_user.length > 1" class="card">
      <h2>Kaikki soittajat tänään</h2>
      <table class="small">
        <tr><th>Soittaja</th><th>Soittoja</th><th>Tavoitettu</th><th>Bookattu</th><th>Osuma</th><th>Puheaika</th><th>Ensimmäinen</th><th>Viimeinen</th></tr>
        <tr v-for="u in day.per_user" :key="u.user_id" class="clickable" @click="who = u.user_id">
          <td>{{ u.name }}</td><td class="mono">{{ u.calls }}</td><td class="mono">{{ u.conversations }}</td><td class="mono"><strong>{{ u.booked }}</strong></td>
          <td>{{ pct(u.booked, u.conversations) }}</td><td>{{ fmtMinutes(u.talk_seconds) }}</td><td>{{ hhmm(u.first_call_at) }}</td><td>{{ hhmm(u.last_call_at) }}</td>
        </tr>
      </table>
    </div>
  </div>

  <!-- ------------------------------------------------ period -->
  <div v-if="tab === 'period'" class="row" style="margin-bottom: 1rem">
    <select v-model.number="days" style="width: auto" @change="load">
      <option :value="1">Tänään</option><option :value="7">7 päivää</option><option :value="30">30 päivää</option><option :value="90">90 päivää</option>
    </select>
  </div>
  <div v-if="tab === 'period' && stats && totals">
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
