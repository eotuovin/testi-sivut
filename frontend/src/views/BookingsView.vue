<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { apiGet, apiPatch, errorText } from '../api/client'
import type { Booking } from '../api/types'
import { fmtDateTime, fmtEur } from '../format'

const bookings = ref<Booking[]>([])
const status = ref('')
const error = ref('')
const STATUS: Record<Booking['status'], string> = { booked: 'Bookattu', confirmed: 'Vahvistettu', completed: 'Pidetty', cancelled: 'Peruttu', no_show: 'Ei saapunut' }

async function load() {
  try {
    bookings.value = await apiGet<Booking[]>('/bookings', { status: status.value })
  } catch (e) {
    error.value = errorText(e)
  }
}
onMounted(load)
async function setStatus(b: Booking, s: string) {
  await apiPatch(`/bookings/${b.id}`, { status: s })
  await load()
}
</script>

<template>
  <h1>Bookkaukset</h1>
  <div class="row" style="margin-bottom: 1rem">
    <select v-model="status" style="width: auto" @change="load">
      <option value="">Kaikki</option>
      <option v-for="(l, k) in STATUS" :key="k" :value="k">{{ l }}</option>
    </select>
  </div>
  <p v-if="error" class="error">{{ error }}</p>
  <div v-if="!bookings.length" class="empty">Ei bookkauksia vielä.</div>
  <table v-else>
    <tr><th>Luotu</th><th>Yritys</th><th>Yhteyshenkilö</th><th>Tuote</th><th>Ajankohta</th><th>Arvo</th><th>Myyjä</th><th>Tila</th><th>Kalenteri</th></tr>
    <tr v-for="b in bookings" :key="b.id">
      <td class="small">{{ fmtDateTime(b.created_at) }}</td>
      <td><router-link :to="'/yritykset/' + b.company_id">{{ b.company_name }}</router-link></td>
      <td class="small">{{ b.contact_name || '' }} <span class="muted">{{ b.contact_phone || '' }}</span></td>
      <td>{{ b.product }}</td>
      <td>{{ fmtDateTime(b.scheduled_at) }}<span v-if="b.duration_minutes" class="muted small"> · {{ b.duration_minutes }} min</span></td>
      <td>{{ fmtEur(b.value_eur) }}</td>
      <td>{{ b.seller_name }}</td>
      <td>
        <select :value="b.status" style="width: auto" @change="setStatus(b, ($event.target as HTMLSelectElement).value)">
          <option v-for="(l, k) in STATUS" :key="k" :value="k">{{ l }}</option>
        </select>
      </td>
      <td class="small">
        <a v-if="b.scheduled_at" :href="'/api/bookings/' + b.id + '/ics'" title="Lataa kalenteritiedosto (Outlook, Google, Apple)">📅 .ics</a>
        <a v-if="b.calendar_html_link" :href="b.calendar_html_link" target="_blank" rel="noopener" style="margin-left: 0.5rem">Google</a>
        <div v-if="b.location || b.meeting_url" class="muted">{{ b.location }} <a v-if="b.meeting_url" :href="b.meeting_url" target="_blank" rel="noopener">linkki</a></div>
      </td>
    </tr>
  </table>
</template>
