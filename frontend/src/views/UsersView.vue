<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { apiDelete, apiGet, apiPatch, apiPost, errorText } from '../api/client'
import type { User } from '../api/types'
import { fmtDateTime } from '../format'
import { useTelephonyStore } from '../stores/telephony'
import { useAuthStore } from '../stores/auth'

interface ApiKey { id: string; name: string; scopes: string[]; active: boolean; created_at: string; last_used_at: string | null }

const tel = useTelephonyStore()
const auth = useAuthStore()
const myPhone = ref('')
const phoneSaved = ref('')
const users = ref<User[]>([])
const keys = ref<ApiKey[]>([])
const error = ref('')
const form = ref({ email: '', name: '', role: 'sales', password: '' })
const keyForm = ref({ name: '', scopes: ['read'] })
const newKey = ref('')

async function load() {
  try {
    ;[users.value, keys.value] = await Promise.all([apiGet<User[]>('/users'), apiGet<ApiKey[]>('/api-keys')])
  } catch (e) {
    error.value = errorText(e)
  }
}
onMounted(async () => {
  await tel.load()
  myPhone.value = tel.myPhone ?? ''
  if (auth.isAdmin) await load()
})

async function savePhone() {
  error.value = ''
  try {
    await tel.saveMyPhone(myPhone.value)
    phoneSaved.value = tel.myPhone ? `Tallennettu: ${tel.myPhone}` : 'Numero poistettu'
  } catch (e) {
    error.value = errorText(e)
  }
}

async function create() {
  error.value = ''
  try {
    await apiPost('/users', form.value)
    form.value = { email: '', name: '', role: 'sales', password: '' }
    await load()
  } catch (e) {
    error.value = errorText(e)
  }
}
async function toggle(u: User) {
  await apiPatch(`/users/${u.id}`, { active: !u.active })
  await load()
}
async function createKey() {
  error.value = ''
  try {
    const r = await apiPost<{ key: string }>('/api-keys', keyForm.value)
    newKey.value = r.key
    keyForm.value = { name: '', scopes: ['read'] }
    await load()
  } catch (e) {
    error.value = errorText(e)
  }
}
async function revoke(k: ApiKey) {
  await apiDelete(`/api-keys/${k.id}`)
  await load()
}
</script>

<template>
  <h1>Asetukset</h1>
  <p v-if="error" class="error">{{ error }}</p>
  <div class="card">
    <h2>Oma puhelinnumero</h2>
    <p class="small muted">Kun soitat Luurilla, puhelinpalvelu soittaa ensin tähän numeroon ja yhdistää sitten asiakkaalle. Asiakas näkee yrityksen numeron, ei tätä.</p>
    <div class="row">
      <input v-model="myPhone" placeholder="esim. 045 123 4567" style="width: 220px" />
      <button class="primary" @click="savePhone">Tallenna</button>
      <span class="small muted">{{ phoneSaved }}</span>
    </div>
    <p v-if="tel.status" class="small muted" style="margin-top: 0.5rem">
      Puhelinpalvelu: <strong>{{ tel.status.enabled ? tel.status.provider + ' · ' + tel.status.from_number : 'ei käytössä' }}</strong>
      · Tekoäly: <strong>{{ tel.status.ai.provider === 'mira' ? 'Mira' + (tel.status.ai.agent ? ' (' + tel.status.ai.agent + ')' : '') + (tel.status.ai.reachable ? '' : ' – ei tavoitettavissa') : tel.status.ai.provider === 'anthropic' ? 'Claude' : 'ei käytössä (sääntöpohjainen poiminta)' }}</strong>
    </p>
  </div>
  <template v-if="auth.isAdmin">
  <div class="grid2">
    <div class="card">
      <h2>Uusi käyttäjä</h2>
      <div class="field"><label>Nimi</label><input v-model="form.name" /></div>
      <div class="field"><label>Sähköposti</label><input v-model="form.email" type="email" /></div>
      <div class="field"><label>Rooli</label><select v-model="form.role"><option value="sales">Myyjä</option><option value="admin">Admin</option></select></div>
      <div class="field"><label>Salasana (min 8)</label><input v-model="form.password" type="password" /></div>
      <button class="primary" :disabled="!form.email || !form.name || form.password.length < 8" @click="create">Luo</button>
    </div>
    <div class="card">
      <h2>API-avaimet muille järjestelmille</h2>
      <p class="small muted">read = lukeminen, write = yritysten/soittojen kirjaus, admin = kaikki. Avain näytetään vain kerran.</p>
      <div class="field"><label>Nimi</label><input v-model="keyForm.name" placeholder="esim. CRM-synkka" /></div>
      <div class="field row">
        <label v-for="s in ['read', 'write', 'admin']" :key="s" style="margin: 0"><input type="checkbox" :value="s" v-model="keyForm.scopes" style="width: auto; margin-right: 0.3rem" />{{ s }}</label>
      </div>
      <button :disabled="!keyForm.name" @click="createKey">Luo avain</button>
      <div v-if="newKey" class="card" style="margin-top: 0.5rem"><strong>Kopioi nyt:</strong> <code>{{ newKey }}</code></div>
    </div>
  </div>

  <div class="card">
    <h2>Käyttäjät</h2>
    <table class="small">
      <tr><th>Nimi</th><th>Sähköposti</th><th>Rooli</th><th>Aktiivinen</th><th></th></tr>
      <tr v-for="u in users" :key="u.id">
        <td>{{ u.name }}</td><td>{{ u.email }}</td><td>{{ u.role }}</td>
        <td><span class="tag" :class="u.active ? 'ok' : ''">{{ u.active ? 'kyllä' : 'ei' }}</span></td>
        <td><button class="small" @click="toggle(u)">{{ u.active ? 'Poista käytöstä' : 'Aktivoi' }}</button></td>
      </tr>
    </table>
  </div>

  <div class="card">
    <h2>API-avaimet</h2>
    <div v-if="!keys.length" class="muted small">Ei avaimia.</div>
    <table v-else class="small">
      <tr><th>Nimi</th><th>Oikeudet</th><th>Luotu</th><th>Käytetty viimeksi</th><th></th></tr>
      <tr v-for="k in keys" :key="k.id">
        <td>{{ k.name }}</td><td>{{ k.scopes.join(', ') }}</td><td>{{ fmtDateTime(k.created_at) }}</td>
        <td>{{ k.last_used_at ? fmtDateTime(k.last_used_at) : 'ei koskaan' }}</td>
        <td><button v-if="k.active" class="small danger" @click="revoke(k)">Mitätöi</button><span v-else class="muted">mitätöity</span></td>
      </tr>
    </table>
  </div>
  </template>
</template>
