<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiDelete, apiGet, apiPatch, apiPost, errorText } from '../api/client'
import type { Campaign, ListDetail } from '../api/types'
import { STATUS_LABELS } from '../api/types'
import { fmtDate, fmtDateTime } from '../format'
import CompanyLogo from '../components/CompanyLogo.vue'

const route = useRoute()
const router = useRouter()
const list = ref<ListDetail | null>(null)
const campaigns = ref<Campaign[]>([])
const error = ref('')
const notice = ref('')
const campaign = ref('')
const editing = ref(false)
const name = ref('')

async function load() {
  try {
    list.value = await apiGet<ListDetail>(`/lists/${route.params.id}`)
    name.value = list.value.name
  } catch (e) { error.value = errorText(e) }
}
onMounted(async () => {
  await load()
  campaigns.value = (await apiGet<Campaign[]>('/campaigns')).filter((c) => c.status === 'active')
})

async function enqueue() {
  if (!list.value || !campaign.value) return
  try {
    const r = await apiPost<{ enqueued: number }>(`/lists/${list.value.id}/enqueue`, { campaign_id: campaign.value })
    notice.value = `${r.enqueued} yritystä lisätty soittojonoon`
  } catch (e) { error.value = errorText(e) }
}
async function removeMember(id: string) {
  if (!list.value) return
  await apiDelete(`/lists/${list.value.id}/members/${id}`)
  await load()
}
async function rename() {
  if (!list.value) return
  await apiPatch(`/lists/${list.value.id}`, { name: name.value })
  editing.value = false
  await load()
}
const withPhone = computed(() => list.value?.members.filter((m) => m.phone_e164 || m.phone_count > 0).length ?? 0)
</script>

<template>
  <p v-if="error" class="error">{{ error }}</p>
  <div v-if="list">
    <router-link to="/listat" class="small">← Listat</router-link>
    <div class="page-head">
      <div>
        <h1 v-if="!editing" @dblclick="editing = true">{{ list.name }} <button class="ghost small" @click="editing = true">muokkaa</button></h1>
        <div v-else class="row"><input v-model="name" style="width:320px" @keyup.enter="rename" /><button class="primary small" @click="rename">Tallenna</button><button class="ghost small" @click="editing = false">Peruuta</button></div>
        <p class="muted small">{{ list.kind === 'contact' ? 'Henkilölista' : 'Yrityslista' }} · {{ list.members.length }} jäsentä · {{ withPhone }} joilla numero · {{ list.owner_name || '—' }} · {{ fmtDateTime(list.updated_at) }}</p>
      </div>
      <div class="row">
        <button class="small" @click="router.push({ path: '/haku', query: { list_id: list.id } })">Avaa haussa</button>
        <a class="btn small" :href="`/api/lists/${list.id}/export.csv`">Vie CSV</a>
        <select v-model="campaign" style="width:auto"><option value="">Soittojonoon…</option><option v-for="c in campaigns" :key="c.id" :value="c.id">{{ c.name }}</option></select>
        <button class="primary small" :disabled="!campaign" @click="enqueue">Lisää koko lista jonoon</button>
      </div>
    </div>
    <p v-if="notice" class="tag ok">{{ notice }}</p>

    <div v-if="!list.members.length" class="empty">Lista on tyhjä. Rastita hakutuloksia ja lisää ne tähän listaan.</div>
    <div v-else class="table-wrap">
      <table>
        <thead><tr><th>Yritys</th><th>Henkilö</th><th>Puhelin</th><th>Sähköposti</th><th>Sijainti</th><th>Tila</th><th>Viim. soitto</th><th>Lisätty</th><th></th></tr></thead>
        <tbody>
          <tr v-for="m in list.members" :key="m.id" class="clickable" @click="router.push(`/yritykset/${m.company_id}`)">
            <td><div class="co"><CompanyLogo :name="m.company_name" :website="m.website" /><div class="t"><strong>{{ m.company_name }}</strong><div class="sub">{{ m.business_id || '' }}<template v-if="m.industry_label"> · {{ m.industry_label.slice(0, 40) }}</template></div></div></div></td>
            <td class="small">{{ m.contact_name || (m.contact_id ? '—' : `${m.phone_count} numeroa`) }}<div v-if="m.title" class="muted">{{ m.title }}</div></td>
            <td class="nowrap" @click.stop><a v-if="m.phone_e164" :href="'tel:' + m.phone_e164">{{ m.phone_e164 }}</a><span v-else class="muted">—</span><span v-if="m.do_not_call" class="tag danger" style="margin-left:0.3rem">kielto</span></td>
            <td class="small" @click.stop><a v-if="m.email" :href="'mailto:' + m.email">{{ m.email }}</a><span v-else class="muted">—</span></td>
            <td class="small">{{ m.city || '—' }}</td>
            <td><span class="tag" :class="{ ok: m.company_status === 'customer', danger: m.company_status === 'do_not_call' }">{{ STATUS_LABELS[m.company_status] ?? m.company_status }}</span></td>
            <td class="small muted">{{ m.last_call_at ? fmtDate(m.last_call_at) : '—' }}</td>
            <td class="small muted nowrap">{{ fmtDate(m.added_at) }}<div>{{ m.added_by_name }}</div></td>
            <td @click.stop><button class="ghost small" title="Poista listalta" @click="removeMember(m.id)">✕</button></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
