<script setup lang="ts">
/** Bookings: the leads the desk produces, as a pipeline. KPI tiles on top,
 *  then "tulossa" grouped by day, then everything in a table with the status
 *  changeable in place. */
import { computed, onMounted, ref } from 'vue'
import { apiGet, apiPatch, errorText } from '../api/client'
import type { Booking } from '../api/types'
import { fmtDateTime, fmtEur } from '../format'

const bookings = ref<Booking[]>([])
const status = ref('')
const error = ref('')
const STATUS: Record<Booking['status'], string> = { booked: 'Bookattu', confirmed: 'Vahvistettu', completed: 'Pidetty', cancelled: 'Peruttu', no_show: 'Ei saapunut' }
const STATUS_CLASS: Record<Booking['status'], string> = { booked: 'info', confirmed: 'ok', completed: 'ok', cancelled: 'danger', no_show: 'warn' }

async function load() {
  try {
    bookings.value = await apiGet<Booking[]>('/bookings', { status: status.value, limit: 500 })
  } catch (e) {
    error.value = errorText(e)
  }
}
onMounted(load)
async function setStatus(b: Booking, s: string) {
  await apiPatch(`/bookings/${b.id}`, { status: s })
  await load()
}
const upcoming = computed(() => {
  const now = Date.now()
  const open = bookings.value.filter((b) => (b.status === 'booked' || b.status === 'confirmed') && b.scheduled_at && new Date(b.scheduled_at).getTime() >= now)
  open.sort((a, b) => (a.scheduled_at! < b.scheduled_at! ? -1 : 1))
  const groups: { day: string; items: Booking[] }[] = []
  for (const b of open) {
    const day = new Intl.DateTimeFormat('fi-FI', { weekday: 'long', day: 'numeric', month: 'numeric' }).format(new Date(b.scheduled_at!))
    const g = groups.find((x) => x.day === day) ?? (groups.push({ day, items: [] }), groups[groups.length - 1])
    g.items.push(b)
  }
  return groups
})
const kpi = computed(() => {
  const weekAgo = Date.now() - 7 * 86400e3
  const thisMonth = new Date(); thisMonth.setDate(1); thisMonth.setHours(0, 0, 0, 0)
  const all = bookings.value
  return {
    open: all.filter((b) => b.status === 'booked' || b.status === 'confirmed').length,
    week: all.filter((b) => new Date(b.created_at).getTime() >= weekAgo).length,
    month: all.filter((b) => new Date(b.created_at).getTime() >= thisMonth.getTime()).length,
    held: all.filter((b) => b.status === 'completed').length,
    lost: all.filter((b) => b.status === 'cancelled' || b.status === 'no_show').length,
    value: all.filter((b) => b.status !== 'cancelled').reduce((s, b) => s + Number(b.value_eur ?? 0), 0),
  }
})
</script>

<template>
  <div class="page-head">
    <div><h1>Bookkaukset</h1><p class="muted small">Puhelussa sovitut tapaamiset ja esittelyt. Vaihda tila tästä kun tapaaminen on pidetty tai peruttu.</p></div>
    <select v-model="status" style="width: auto" @change="load">
      <option value="">Kaikki tilat</option>
      <option v-for="(l, k) in STATUS" :key="k" :value="k">{{ l }}</option>
    </select>
  </div>
  <p v-if="error" class="error">{{ error }}</p>

  <div class="kpis" style="margin-bottom: 1rem">
    <div class="kpi"><div class="n">{{ kpi.open }}</div><div class="muted small">Avoinna</div></div>
    <div class="kpi"><div class="n">{{ kpi.week }}</div><div class="muted small">Uusia 7 pv</div></div>
    <div class="kpi"><div class="n">{{ kpi.month }}</div><div class="muted small">Tässä kuussa</div></div>
    <div class="kpi"><div class="n">{{ kpi.held }}</div><div class="muted small">Pidetty</div></div>
    <div class="kpi"><div class="n">{{ kpi.lost }}</div><div class="muted small">Peruttu / ei saapunut</div></div>
    <div class="kpi"><div class="n">{{ fmtEur(kpi.value) }}</div><div class="muted small">Sovittu arvo</div></div>
  </div>

  <div v-if="upcoming.length" class="card">
    <h2>Tulossa</h2>
    <div v-for="g in upcoming" :key="g.day" style="margin-bottom: 0.6rem">
      <h3 class="muted" style="text-transform: capitalize">{{ g.day }}</h3>
      <div v-for="b in g.items" :key="b.id" class="row" style="padding: 0.35rem 0; border-bottom: 1px solid var(--line)">
        <strong class="mono" style="width: 56px">{{ new Date(b.scheduled_at!).toLocaleTimeString('fi-FI', { hour: '2-digit', minute: '2-digit' }) }}</strong>
        <router-link :to="'/yritykset/' + b.company_id" style="font-weight: 600">{{ b.company_name }}</router-link>
        <span class="small muted">{{ b.contact_name || '' }} · {{ b.product }} · {{ b.location || '' }} · {{ b.seller_name }}</span>
        <span class="tag" :class="STATUS_CLASS[b.status]" style="margin-left: auto">{{ STATUS[b.status] }}</span>
        <a v-if="b.meeting_url" :href="b.meeting_url" target="_blank" rel="noopener" class="small">Liity</a>
        <a :href="'/api/bookings/' + b.id + '/ics'" class="small" title="Lataa kalenteritiedosto">📅</a>
      </div>
    </div>
  </div>

  <div v-if="!bookings.length" class="empty">Ei bookkauksia vielä. Bookkaus syntyy, kun puhelun lopputulokseksi valitaan ”Bookattu!”.</div>
  <div v-else class="table-wrap">
    <table>
      <thead><tr><th>Luotu</th><th>Yritys</th><th>Yhteyshenkilö</th><th>Tuote</th><th>Ajankohta</th><th>Arvo</th><th>Myyjä</th><th>Tila</th><th>Kalenteri</th></tr></thead>
      <tbody>
        <tr v-for="b in bookings" :key="b.id">
          <td class="small muted nowrap">{{ fmtDateTime(b.created_at) }}</td>
          <td><router-link :to="'/yritykset/' + b.company_id" style="font-weight: 600">{{ b.company_name }}</router-link><div v-if="b.notes" class="small muted">{{ b.notes }}</div></td>
          <td class="small">{{ b.contact_name || '' }} <span class="muted">{{ b.contact_phone || '' }}</span></td>
          <td>{{ b.product }}</td>
          <td class="nowrap">{{ fmtDateTime(b.scheduled_at) }}<span v-if="b.duration_minutes" class="muted small"> · {{ b.duration_minutes }} min</span><div class="small muted">{{ b.location }}</div></td>
          <td class="mono">{{ fmtEur(b.value_eur) }}</td>
          <td class="small">{{ b.seller_name }}</td>
          <td>
            <select :value="b.status" style="width: auto" class="small" @change="setStatus(b, ($event.target as HTMLSelectElement).value)">
              <option v-for="(l, k) in STATUS" :key="k" :value="k">{{ l }}</option>
            </select>
          </td>
          <td class="small nowrap">
            <a v-if="b.scheduled_at" :href="'/api/bookings/' + b.id + '/ics'" title="Lataa kalenteritiedosto (Outlook, Google, Apple)">📅 .ics</a>
            <a v-if="b.calendar_html_link" :href="b.calendar_html_link" target="_blank" rel="noopener" style="margin-left: 0.5rem">Google</a>
            <a v-if="b.meeting_url" :href="b.meeting_url" target="_blank" rel="noopener" style="margin-left: 0.5rem">linkki</a>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
