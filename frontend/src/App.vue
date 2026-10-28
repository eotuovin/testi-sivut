<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import { NAV } from './router'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const nav = computed(() => NAV.filter((n) => !n.admin || auth.isAdmin))
const quick = ref('')

async function logout() {
  await auth.logout()
  router.push({ name: 'login' })
}
function quickSearch() {
  const q = quick.value.trim()
  if (!q) return
  router.push({ path: '/haku', query: { q } })
  quick.value = ''
}
const initials = computed(() => (auth.me?.name ?? '?').split(' ').map((p) => p[0]).join('').slice(0, 2).toUpperCase())
</script>

<template>
  <div v-if="route.name === 'login'">
    <router-view />
  </div>
  <div v-else class="shell">
    <aside class="rail">
      <router-link to="/haku" class="brand" title="Luuri"><span class="mark">L</span><span class="word">Luuri</span></router-link>
      <nav>
        <router-link v-for="n in nav" :key="n.path" :to="n.path" :title="n.label">
          <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path :d="n.icon" fill="currentColor" /></svg>
          <span>{{ n.label }}</span>
        </router-link>
      </nav>
    </aside>
    <div class="body">
      <header class="topbar">
        <form class="quick" @submit.prevent="quickSearch">
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M10 2a8 8 0 1 0 4.9 14.3l5.4 5.4 1.4-1.4-5.4-5.4A8 8 0 0 0 10 2zm0 2a6 6 0 1 1 0 12 6 6 0 0 1 0-12z" fill="currentColor" /></svg>
          <input v-model="quick" placeholder="Hae yritystä, henkilöä tai Y-tunnusta…" />
        </form>
        <div class="spacer" />
        <div v-if="auth.me" class="who">
          <span class="avatar">{{ initials }}</span>
          <span class="name">{{ auth.me.name }}<small>{{ auth.me.role === 'admin' ? 'Admin' : 'Myyjä' }}</small></span>
          <button class="ghost small" @click="logout">Kirjaudu ulos</button>
        </div>
      </header>
      <main>
        <router-view />
      </main>
    </div>
  </div>
</template>
