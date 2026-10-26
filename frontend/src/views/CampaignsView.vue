<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { apiGet, apiPatch, apiPost, errorText } from '../api/client'
import type { Campaign } from '../api/types'

const campaigns = ref<Campaign[]>([])
const error = ref('')
const editing = ref<Partial<Campaign> | null>(null)

async function load() {
  try {
    campaigns.value = await apiGet<Campaign[]>('/campaigns')
  } catch (e) {
    error.value = errorText(e)
  }
}
onMounted(load)

function startNew() {
  editing.value = { name: '', product: '', script: '', recording_notice: 'Tämä puhelu tallennetaan palvelun kehittämistä varten.', max_attempts: 4, retry_after_minutes: 240 }
}
async function save() {
  if (!editing.value) return
  error.value = ''
  try {
    const body = { name: editing.value.name, product: editing.value.product, script: editing.value.script, recording_notice: editing.value.recording_notice, max_attempts: editing.value.max_attempts, retry_after_minutes: editing.value.retry_after_minutes }
    if (editing.value.id) await apiPatch(`/campaigns/${editing.value.id}`, body)
    else await apiPost('/campaigns', body)
    editing.value = null
    await load()
  } catch (e) {
    error.value = errorText(e)
  }
}
async function setStatus(c: Campaign, status: string) {
  await apiPatch(`/campaigns/${c.id}`, { status })
  await load()
}
</script>

<template>
  <h1>Kampanjat</h1>
  <p class="muted small">Kampanja = mitä myydään + spiikki + soittosäännöt. Yritykset lisätään kampanjan jonoon Yritykset- tai Prospektointi-sivulta.</p>
  <p v-if="error" class="error">{{ error }}</p>
  <button class="primary" style="margin-bottom: 1rem" @click="startNew">+ Uusi kampanja</button>

  <div v-if="editing" class="card">
    <h2>{{ editing.id ? 'Muokkaa' : 'Uusi kampanja' }}</h2>
    <div class="grid2">
      <div class="field"><label>Nimi</label><input v-model="editing.name" /></div>
      <div class="field"><label>Tuote / palvelu jota myydään</label><input v-model="editing.product" /></div>
      <div class="field"><label>Max soittoyrityksiä per yritys</label><input v-model.number="editing.max_attempts" type="number" min="1" max="20" /></div>
      <div class="field"><label>Uusi yritys kun ei vastaa (min)</label><input v-model.number="editing.retry_after_minutes" type="number" min="5" /></div>
    </div>
    <div class="field"><label>Tallennusilmoitus (soittaja sanoo alussa, kun puhelut nauhoitetaan)</label><input v-model="editing.recording_notice" /></div>
    <div class="field"><label>Spiikki (näytetään soittajalle)</label><textarea v-model="editing.script" style="min-height: 200px" placeholder="Moi, täällä … Soitan siitä syystä että …" /></div>
    <div class="row"><button class="primary" :disabled="!editing.name || !editing.product" @click="save">Tallenna</button><button @click="editing = null">Peru</button></div>
  </div>

  <div v-if="!campaigns.length" class="empty">Ei kampanjoita. Luo ensimmäinen.</div>
  <table v-else>
    <tr><th>Nimi</th><th>Tuote</th><th>Tila</th><th>Jonossa</th><th>Soitettu</th><th>Bookattu</th><th></th></tr>
    <tr v-for="c in campaigns" :key="c.id">
      <td><strong>{{ c.name }}</strong></td>
      <td>{{ c.product }}</td>
      <td><span class="tag" :class="{ ok: c.status === 'active', warn: c.status === 'paused' }">{{ c.status }}</span></td>
      <td>{{ c.open_tasks }}</td><td>{{ c.done_tasks }}</td><td><strong>{{ c.bookings }}</strong></td>
      <td class="row">
        <button class="small" @click="editing = { ...c }">Muokkaa</button>
        <button v-if="c.status !== 'active'" class="small" @click="setStatus(c, 'active')">Aktivoi</button>
        <button v-else class="small" @click="setStatus(c, 'paused')">Tauota</button>
        <button v-if="c.status !== 'archived'" class="small" @click="setStatus(c, 'archived')">Arkistoi</button>
      </td>
    </tr>
  </table>
</template>
