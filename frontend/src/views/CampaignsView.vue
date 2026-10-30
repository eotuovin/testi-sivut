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

const AVORA_SCRIPT = `AVAUS (rauhallisesti, kuin tutulle)
"Moi, {{myyja}} täällä Jyväskylästä. ... Onko {{etunimi}} puhelimessa?"
"Mä soitan täysin kylmää puhelua, me ei olla ikinä juteltu. Saanko kertoa parillakymmenellä sekunnilla miks soitin, ja sä päätät sitten jatketaanko?"

SYY SOITTOON (yksi lause)
"Huomasin että {{yritys}} on perustettu hiljattain, ja tässä vaiheessa moni pyörittää varauksia, asiakastietoja ja laskutusta vähän siellä täällä – WhatsApp, kalenteri, Excel. Me tehdään täällä Jyväskylässä sitä, että ne laitetaan yhteen paikkaan ja pystytetään asiakkaan puolesta."

YKSI KYSYMYS – ja sitten hiljaa
"Mitä sä tällä hetkellä käytät, kun asiakas haluaa varata ajan tai pyytää tarjouksen?"

PEILAUS (asiakkaan omat sanat takaisin)
"Eli ... ja ... Kuulostaa siltä että se toimii, mutta vie sun aikaa."

PYYNTÖ (pieni, kaksi aikaa)
"Mä en osaa vielä sanoa sopiiko tää teille. Otetaan 15 minuuttia Teamsissa, mä näytän miltä se näyttäis just teidän varauksilla, ja sä sanot suoraan onko siinä järkeä. Sopisko torstaina aamupäivästä vai iltapäivästä?"

VAHVISTUS
"Laitan kalenterikutsun. Ei tarvitse asentaa mitään. Jos tulee este, vastaa kutsuun niin siirretään."

JOS "EI KIINNOSTA": "Selvä, kiitos että sanoit suoraan. Onko se niin että homma toimii jo, vai että ajankohta on huono?"
HINTA JOS KYSYY: "149 €/kk, ei aloitusmaksua – ja me laitetaan se pystyyn teidän puolesta."

ÄLÄ: kysy "onko hetki", nosta ääntä, puhu päälle, väitä vastaan, sano "loistava".`

function startNew() {
  editing.value = { name: '', product: '', script: '', recording_notice: 'Tämä puhelu tallennetaan palvelun kehittämistä varten.', max_attempts: 4, retry_after_minutes: 240 }
}
function startAvora() {
  editing.value = { name: 'Avora – ensikontakti', product: 'Avora Kasvu (149 €/kk)', script: AVORA_SCRIPT, recording_notice: 'Tämä puhelu tallennetaan palvelun kehittämistä varten.', max_attempts: 3, retry_after_minutes: 1440 }
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
async function clearQueue(c: Campaign) {
  if (!confirm(`Tyhjennetäänkö kampanjan ”${c.name}” jono? ${c.queued_tasks ?? 0} odottavaa soittoa merkitään ohitetuiksi. Takaisinsoitot säilyvät.`)) return
  await apiPost(`/campaigns/${c.id}/clear-queue`)
  await load()
}
async function setStatus(c: Campaign, status: string) {
  await apiPatch(`/campaigns/${c.id}`, { status })
  await load()
}
</script>

<template>
  <h1>Kampanjat</h1>
  <p class="muted small">Kampanja = mitä myydään + spiikki + soittosäännöt. Yritykset lisätään kampanjan jonoon Hausta, listalta, sekvenssistä tai Agentin ehdotuksista.</p>
  <p v-if="error" class="error">{{ error }}</p>
  <div class="row" style="margin-bottom: 1rem"><button class="primary" @click="startNew">+ Uusi kampanja</button><button @click="startAvora">+ Avora-kampanja (valmis spiikki)</button></div>

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
    <tr><th>Nimi</th><th>Tuote</th><th>Tila</th><th>Jonossa</th><th>Takaisinsoitot</th><th>Soitettu</th><th>Ohitettu</th><th>Bookattu</th><th></th></tr>
    <tr v-for="c in campaigns" :key="c.id">
      <td><strong>{{ c.name }}</strong></td>
      <td>{{ c.product }}</td>
      <td><span class="tag" :class="{ ok: c.status === 'active', warn: c.status === 'paused' }">{{ c.status }}</span></td>
      <td class="mono">{{ c.queued_tasks ?? c.open_tasks }}<span v-if="c.in_progress_tasks" class="muted small"> (+{{ c.in_progress_tasks }} kesken)</span></td>
      <td class="mono">{{ c.callback_tasks ?? 0 }}</td><td class="mono">{{ c.done_tasks }}</td><td class="mono muted">{{ c.skipped_tasks ?? 0 }}</td><td><strong>{{ c.bookings }}</strong></td>
      <td class="row">
        <button class="small" @click="editing = { ...c }">Muokkaa</button>
        <button v-if="c.status !== 'active'" class="small" @click="setStatus(c, 'active')">Aktivoi</button>
        <button v-else class="small" @click="setStatus(c, 'paused')">Tauota</button>
        <button v-if="c.status !== 'archived'" class="small" @click="setStatus(c, 'archived')">Arkistoi</button>
        <button v-if="(c.queued_tasks ?? 0) > 0" class="small danger" @click="clearQueue(c)">Tyhjennä jono</button>
      </td>
    </tr>
  </table>
</template>
