<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { errorText } from '../api/client'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const email = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
  busy.value = true
  error.value = ''
  try {
    await auth.login(email.value, password.value)
    router.push((route.query.next as string) || '/soita')
  } catch (e) {
    error.value = errorText(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div style="max-width: 360px; margin: 10vh auto">
    <div class="card">
      <h1>Luuri</h1>
      <p class="muted small">Kirjaudu sisään soittaaksesi.</p>
      <form @submit.prevent="submit">
        <div class="field"><label>Sähköposti</label><input v-model="email" type="email" autocomplete="username" required /></div>
        <div class="field"><label>Salasana</label><input v-model="password" type="password" autocomplete="current-password" required /></div>
        <p v-if="error" class="error small">{{ error }}</p>
        <button class="primary" type="submit" :disabled="busy">Kirjaudu</button>
      </form>
    </div>
  </div>
</template>
