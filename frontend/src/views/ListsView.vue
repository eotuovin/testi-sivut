<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiDelete, apiGet, apiPost, errorText } from '../api/client'
import type { List } from '../api/types'
import { fmtDateTime } from '../format'

const router = useRouter()
const lists = ref<List[]>([])
const error = ref('')
const showNew = ref(false)
const form = ref({ name: '', kind: 'company' as 'company' | 'contact', description: '' })

async function load() {
  try { lists.value = await apiGet<List[]>('/lists') } catch (e) { error.value = errorText(e) }
}
onMounted(load)

async function create() {
  try {
    const l = await apiPost<List>('/lists', form.value)
    showNew.value = false
    form.value = { name: '', kind: 'company', description: '' }
    router.push(`/listat/${l.id}`)
  } catch (e) { error.value = errorText(e) }
}
async function remove(l: List) {
  if (!confirm(`Poistetaanko lista ”${l.name}”? Yritykset säilyvät Luurissa.`)) return
  await apiDelete(`/lists/${l.id}`)
  await load()
}
</script>

<template>
  <div class="page-head">
    <div><h1>Listat</h1><p class="muted small">Listat ovat hausta kerättyjä yrityksiä tai henkilöitä. Listasta voi viedä CSV:n tai työntää koko listan soittojonoon.</p></div>
    <button class="primary" @click="showNew = true">+ Uusi lista</button>
  </div>
  <p v-if="error" class="error">{{ error }}</p>

  <div v-if="!lists.length" class="empty">Ei listoja vielä. Rastita hakutuloksia ja valitse ”Lisää listaan”, tai luo tyhjä lista tästä.</div>
  <div v-else class="table-wrap">
    <table>
      <thead><tr><th>Lista</th><th>Tyyppi</th><th>Jäseniä</th><th>Yrityksiä</th><th>Numeroita</th><th>Omistaja</th><th>Päivitetty</th><th></th></tr></thead>
      <tbody>
        <tr v-for="l in lists" :key="l.id" class="clickable" @click="router.push(`/listat/${l.id}`)">
          <td><strong>{{ l.name }}</strong><div v-if="l.description" class="small muted">{{ l.description }}</div></td>
          <td><span class="tag" :class="l.kind === 'contact' ? 'info' : ''">{{ l.kind === 'contact' ? 'Henkilöt' : 'Yritykset' }}</span></td>
          <td class="mono">{{ l.member_count }}</td>
          <td class="mono">{{ l.company_count }}</td>
          <td class="mono">{{ l.phone_count }}</td>
          <td class="small">{{ l.owner_name || '—' }}<span v-if="!l.shared" class="muted"> · yksityinen</span></td>
          <td class="small muted nowrap">{{ fmtDateTime(l.updated_at) }}</td>
          <td @click.stop><button class="ghost small" @click="remove(l)">Poista</button></td>
        </tr>
      </tbody>
    </table>
  </div>

  <div v-if="showNew" class="modal" @click.self="showNew = false">
    <div class="box">
      <h2>Uusi lista</h2>
      <div class="field"><label>Nimi</label><input v-model="form.name" placeholder="esim. Tampereen autokorjaamot" @keyup.enter="create" /></div>
      <div class="field"><label>Tyyppi</label><select v-model="form.kind"><option value="company">Yrityslista</option><option value="contact">Henkilölista</option></select></div>
      <div class="field"><label>Kuvaus</label><textarea v-model="form.description" style="min-height:60px" /></div>
      <div class="row" style="justify-content:flex-end"><button class="ghost" @click="showNew = false">Peruuta</button><button class="primary" :disabled="!form.name.trim()" @click="create">Luo</button></div>
    </div>
  </div>
</template>
