<script setup lang="ts">
/** Tehtävät: the seller's inbox from sequences — e-mails to send by hand (when
 *  SMTP is not set up) and to-dos. Each row opens the ready-made message; one
 *  click opens it in the mail app, another marks it done. */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet, apiPost, errorText } from '../api/client'
import type { SequenceAction } from '../api/types'
import { STEP_LABELS } from '../api/types'
import { fmtDateTime } from '../format'

const router = useRouter()
const actions = ref<SequenceAction[]>([])
const status = ref<'open' | 'pending' | 'done' | 'failed' | 'all'>('open')
const mine = ref(false)
const open = ref<SequenceAction | null>(null)
const error = ref('')
const copied = ref(false)

async function load() {
  try {
    actions.value = await apiGet<SequenceAction[]>('/sequences/inbox', { status: status.value, mine: mine.value || undefined })
  } catch (e) { error.value = errorText(e) }
}
onMounted(load)

async function done(a: SequenceAction, st: 'done' | 'skipped') {
  try {
    await apiPost(`/sequences/actions/${a.id}/done`, { status: st })
    open.value = null
    await load()
  } catch (e) { error.value = errorText(e) }
}
function mailto(a: SequenceAction) {
  return `mailto:${encodeURIComponent(a.email_to ?? '')}?subject=${encodeURIComponent(a.subject ?? '')}&body=${encodeURIComponent(a.body ?? '')}`
}
async function copy(a: SequenceAction) {
  try { await navigator.clipboard.writeText(`${a.subject}\n\n${a.body}`); copied.value = true; setTimeout(() => (copied.value = false), 1500) } catch { /* clipboard blocked */ }
}
const overdue = computed(() => actions.value.filter((a) => a.status === 'pending' && new Date(a.due_at).getTime() < Date.now() - 3600e3).length)
const stepIcon = (k: string) => (k === 'call' ? '📞' : k === 'email' ? '✉️' : '☑️')
const STATUS: Record<string, string> = { pending: 'Odottaa', done: 'Tehty', skipped: 'Ohitettu', failed: 'Virhe' }
</script>

<template>
  <div class="page-head">
    <div><h1>Tehtävät</h1><p class="muted small">Sekvenssien sähköpostit ja tehtävät, jotka odottavat sinua. Soitot eivät näy tässä — ne ovat <router-link to="/soita">Soita</router-link>-jonossa.</p></div>
    <div class="row">
      <label class="check" style="margin: 0; display: inline-flex; gap: 0.3rem; align-items: center"><input v-model="mine" type="checkbox" @change="load" /> Vain omat</label>
      <select v-model="status" style="width: auto" @change="load"><option value="open">Odottavat ja virheet</option><option value="pending">Vain odottavat</option><option value="done">Tehdyt</option><option value="failed">Virheet</option><option value="all">Kaikki</option></select>
    </div>
  </div>
  <p v-if="error" class="error">{{ error }}</p>
  <p v-if="overdue" class="tag warn">{{ overdue }} tehtävää yli tunnin myöhässä</p>

  <div v-if="!actions.length" class="empty">Ei tehtäviä. Kun sekvenssin sähköposti- tai tehtäväaskel erääntyy, se ilmestyy tähän.</div>
  <div v-else class="table-wrap">
    <table>
      <thead><tr><th>Erääntyy</th><th>Tehtävä</th><th>Yritys</th><th>Henkilö</th><th>Sekvenssi</th><th>Tila</th><th></th></tr></thead>
      <tbody>
        <tr v-for="a in actions" :key="a.id" class="clickable" :class="{ overdue: a.status === 'pending' && new Date(a.due_at).getTime() < Date.now() - 3600e3 }" @click="open = a">
          <td class="small nowrap">{{ fmtDateTime(a.due_at) }}</td>
          <td><strong>{{ stepIcon(a.kind) }} {{ a.subject || STEP_LABELS[a.kind] }}</strong><div class="small muted">askel {{ a.position }}<template v-if="a.kind === 'email'"> · {{ a.email_to || 'ei osoitetta' }}</template></div></td>
          <td class="small"><router-link :to="`/yritykset/${a.company_id}`" @click.stop>{{ a.company_name }}</router-link></td>
          <td class="small">{{ a.contact_name || '—' }}<div class="muted">{{ a.contact_title || '' }}</div></td>
          <td class="small muted">{{ a.sequence_name }}</td>
          <td><span class="tag" :class="{ info: a.status === 'pending', ok: a.status === 'done', danger: a.status === 'failed' }">{{ STATUS[a.status] }}</span><div v-if="a.error" class="small error">{{ a.error }}</div><div v-if="a.sent_via" class="small muted">{{ a.sent_via === 'smtp' ? 'lähetetty automaattisesti' : 'lähetetty käsin' }}</div></td>
          <td @click.stop><button v-if="a.status === 'pending'" class="primary small" @click="open = a">Avaa</button><router-link v-else-if="a.status === 'failed'" class="btn small" :to="`/yritykset/${a.company_id}?tab=people`">Lisää sähköposti</router-link></td>
        </tr>
      </tbody>
    </table>
  </div>

  <template v-if="open">
    <div class="drawer-bg" @click="open = null"></div>
    <div class="drawer">
      <div class="row" style="justify-content: space-between"><h2 style="margin: 0">{{ stepIcon(open.kind) }} {{ STEP_LABELS[open.kind] }} · askel {{ open.position }}</h2><button class="ghost" @click="open = null">✕</button></div>
      <p class="small"><a href="#" @click.prevent="router.push(`/yritykset/${open.company_id}`)">{{ open.company_name }}</a><template v-if="open.contact_name"> · {{ open.contact_name }}<span class="muted"> {{ open.contact_title }}</span></template><br /><span class="muted">{{ open.sequence_name }} · erääntyy {{ fmtDateTime(open.due_at) }}</span></p>
      <template v-if="open.kind === 'email'">
        <div class="field"><label>Vastaanottaja</label><div>{{ open.email_to || '—' }}</div></div>
        <div class="field"><label>Aihe</label><div><strong>{{ open.subject }}</strong></div></div>
        <div class="field"><label>Viesti</label><div class="script">{{ open.body }}</div></div>
        <div v-if="open.status === 'failed'" class="card small" style="border-color: var(--danger)">
          <strong>Ei lähtenyt:</strong> {{ open.error }}. Lisää henkilölle sähköposti yritysprofiilissa ja lähetä viesti käsin, tai ohita askel.
          <div class="row" style="margin-top: 0.5rem"><router-link class="btn small" :to="`/yritykset/${open.company_id}?tab=people`">Avaa yritys</router-link><button class="ghost small" @click="done(open, 'skipped')">Ohita askel</button></div>
        </div>
        <div class="row" v-if="open.status === 'pending'">
          <a class="btn primary" :href="mailto(open)" style="background: var(--accent); color: #fff; border-color: var(--accent)">Avaa sähköpostissa</a>
          <button @click="copy(open)">{{ copied ? 'Kopioitu' : 'Kopioi teksti' }}</button>
          <button class="small" @click="done(open, 'done')">✓ Lähetin sen</button>
          <button class="ghost small" @click="done(open, 'skipped')">Ohita</button>
        </div>
      </template>
      <template v-else>
        <div class="field"><label>Tehtävä</label><div><strong>{{ open.subject }}</strong></div></div>
        <div v-if="open.body" class="field"><label>Ohje</label><div class="script">{{ open.body }}</div></div>
        <div v-if="open.phone_e164" class="field"><label>Puhelin</label><a :href="'tel:' + open.phone_e164">{{ open.phone_e164 }}</a></div>
        <div class="row" v-if="open.status === 'pending'"><button class="primary" @click="done(open, 'done')">✓ Tehty</button><button class="ghost" @click="done(open, 'skipped')">Ohita</button></div>
      </template>
    </div>
  </template>
</template>

<style scoped>
tr.overdue td:first-child { color: var(--danger); font-weight: 600; }
</style>
