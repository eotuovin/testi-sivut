<script setup lang="ts">
/** "Lisää listaan": pick an existing list or create one, then add the selection.
 *  `register` carries search hits that are not yet in Luuri; the API saves them first. */
import { onMounted, ref } from 'vue'
import { apiGet, apiPost, errorText } from '../api/client'
import type { CompanyHit, List } from '../api/types'

const props = defineProps<{
  kind: 'company' | 'contact'
  companyIds?: string[]
  contactIds?: string[]
  register?: CompanyHit[]
}>()
const emit = defineEmits<{ close: []; added: [{ list: List; added: number }] }>()

const lists = ref<List[]>([])
const chosen = ref('')
const newName = ref('')
const error = ref('')
const busy = ref(false)

onMounted(async () => {
  lists.value = (await apiGet<List[]>('/lists')).filter((l) => l.kind === props.kind)
  chosen.value = lists.value[0]?.id ?? '__new'
})

async function submit() {
  busy.value = true
  error.value = ''
  try {
    let listId = chosen.value
    if (listId === '__new') {
      const created = await apiPost<List>('/lists', { name: newName.value, kind: props.kind })
      listId = created.id
    }
    const r = await apiPost<{ added: number; list: List }>(`/lists/${listId}/members`, {
      company_ids: props.companyIds ?? [],
      contact_ids: props.contactIds ?? [],
      register: (props.register ?? []).map((h) => ({
        business_id: h.business_id, name: h.name, company_form: h.company_form, industry_code: h.industry_code,
        industry_label: h.industry_label, website: h.website, city: h.city, postal_code: h.postal_code,
        street_address: h.street_address, registration_date: h.registration_date,
      })),
    })
    emit('added', { list: r.list, added: r.added })
  } catch (e) {
    error.value = errorText(e)
  } finally {
    busy.value = false
  }
}
const total = () => (props.companyIds?.length ?? 0) + (props.contactIds?.length ?? 0) + (props.register?.length ?? 0)
</script>

<template>
  <div class="modal" @click.self="emit('close')">
    <div class="box">
      <h2>Lisää listaan</h2>
      <p class="muted small">{{ total() }} {{ kind === 'company' ? 'yritystä' : 'henkilöä' }} valittuna.</p>
      <div class="field">
        <label>Lista</label>
        <select v-model="chosen">
          <option v-for="l in lists" :key="l.id" :value="l.id">{{ l.name }} ({{ l.member_count }})</option>
          <option value="__new">+ Uusi lista…</option>
        </select>
      </div>
      <div v-if="chosen === '__new'" class="field">
        <label>Uuden listan nimi</label>
        <input v-model="newName" placeholder="esim. Jyväskylän ravintolat, marraskuu" @keyup.enter="submit" />
      </div>
      <p v-if="error" class="error small">{{ error }}</p>
      <div class="row" style="justify-content: flex-end">
        <button class="ghost" @click="emit('close')">Peruuta</button>
        <button class="primary" :disabled="busy || (chosen === '__new' && !newName.trim())" @click="submit">Lisää</button>
      </div>
    </div>
  </div>
</template>
