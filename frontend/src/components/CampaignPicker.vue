<script setup lang="ts">
/** Pick the campaign queue to push into. When there is no active campaign
 *  yet, an admin can create one right here instead of being sent to another
 *  page with a greyed-out button. */
import { computed, onMounted, ref } from 'vue'
import { apiGet, apiPost, errorText } from '../api/client'
import type { Campaign } from '../api/types'
import { useAuthStore } from '../stores/auth'

const props = defineProps<{ suggestedName?: string }>()
const model = defineModel<string>({ required: true })
const auth = useAuthStore()
const campaigns = ref<Campaign[]>([])
const creating = ref(false)
const name = ref('')
const product = ref('Palveluesittely')
const error = ref('')

async function load() {
  campaigns.value = (await apiGet<Campaign[]>('/campaigns')).filter((c) => c.status === 'active')
  if (!model.value && campaigns.value.length === 1) model.value = campaigns.value[0].id
}
onMounted(load)

async function create() {
  error.value = ''
  try {
    const c = await apiPost<Campaign>('/campaigns', { name: name.value.trim(), product: product.value.trim() || 'Palveluesittely' })
    await load()
    model.value = c.id
    creating.value = false
  } catch (e) { error.value = errorText(e) }
}
function startCreate() {
  name.value = props.suggestedName || `Soitot ${new Date().toLocaleDateString('fi-FI')}`
  creating.value = true
}
const canCreate = computed(() => auth.isAdmin)
</script>

<template>
  <span class="row" style="gap: 0.4rem">
    <select v-if="campaigns.length" v-model="model" style="width: auto">
      <option value="">Soittojonoon…</option>
      <option v-for="c in campaigns" :key="c.id" :value="c.id">{{ c.name }}</option>
      <option v-if="canCreate" value="__new">+ Uusi kampanja…</option>
    </select>
    <template v-if="!campaigns.length || model === '__new'">
      <template v-if="!creating">
        <button v-if="canCreate" class="small" @click="startCreate">+ Luo kampanja</button>
        <span v-else class="small muted">Ei aktiivista kampanjaa – pyydä adminia luomaan yksi.</span>
      </template>
      <template v-else>
        <input v-model="name" placeholder="Kampanjan nimi" style="width: 200px" @keyup.enter="create" />
        <input v-model="product" placeholder="Mitä myydään" style="width: 150px" @keyup.enter="create" />
        <button class="primary small" :disabled="!name.trim()" @click="create">Luo</button>
        <button class="ghost small" @click="creating = false; if (model === '__new') model = ''">Peruuta</button>
      </template>
    </template>
    <span v-if="error" class="error small">{{ error }}</span>
  </span>
</template>
