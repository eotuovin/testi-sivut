<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import { NAV } from './router'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const nav = computed(() => NAV.filter((n) => !n.admin || auth.isAdmin))

async function logout() {
  await auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div v-if="route.name === 'login'">
    <router-view />
  </div>
  <div v-else class="layout">
    <nav class="sidebar">
      <div class="brand">Luuri</div>
      <router-link v-for="n in nav" :key="n.path" :to="n.path">{{ n.label }}</router-link>
      <div class="spacer" />
      <div v-if="auth.me" class="me">{{ auth.me.name }} · {{ auth.me.role }}</div>
      <button @click="logout">Kirjaudu ulos</button>
    </nav>
    <main>
      <router-view />
    </main>
  </div>
</template>
