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
    router.push((route.query.next as string) || '/tanaan')
  } catch (e) {
    error.value = errorText(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="login">
    <div class="card">
      <div class="row" style="gap: 0.6rem; margin-bottom: 0.5rem"><span class="logo-mark">L</span><h1 style="margin: 0">Luuri</h1></div>
      <p class="muted small">Muutto365:n myyntityökalu. Kirjaudu omilla tunnuksillasi.</p>
      <form @submit.prevent="submit">
        <div class="field"><label>Sähköposti</label><input v-model="email" type="email" autocomplete="username" required /></div>
        <div class="field"><label>Salasana</label><input v-model="password" type="password" autocomplete="current-password" required /></div>
        <p v-if="error" class="error small">{{ error }}</p>
        <button class="primary" type="submit" :disabled="busy">Kirjaudu</button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.login { min-height: 100vh; display: grid; place-items: center; background: #08090A; padding: 1rem; position: relative; overflow: hidden; }
.login::before { content: ''; position: absolute; left: 50%; top: 38%; width: 900px; height: 420px; transform: translate(-50%, -50%); background: radial-gradient(50% 50% at 50% 50%, rgba(142,162,255,.14), rgba(142,162,255,0) 70%); pointer-events: none; }
.login .card { position: relative; width: min(400px, 100%); margin: 0; padding: 1.8rem 1.8rem 1.6rem; border-radius: 16px; background: #0F1013; }
.login h1 { font-size: 1.6rem; }
.login button.primary { width: 100%; justify-content: center; height: 44px; margin-top: 0.3rem; }
.logo-mark { width: 34px; height: 34px; border-radius: 9px; background: var(--accent); color: var(--accent-ink); display: grid; place-items: center; font-weight: 800; font-size: 1.1rem; }
</style>
