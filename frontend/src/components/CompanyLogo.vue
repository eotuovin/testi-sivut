<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ name: string; url?: string | null; website?: string | null }>()
const initials = computed(() => props.name.replace(/\b(oy|oyj|ab|ky|tmi|ry)\b/gi, '').trim().split(/\s+/).map((p) => p[0]).join('').slice(0, 2).toUpperCase() || '?')
const hue = computed(() => { let h = 0; for (const ch of props.name) h = (h * 31 + ch.charCodeAt(0)) % 360; return h })
const favicon = computed(() => {
  if (props.url) return props.url
  if (!props.website) return null
  const host = props.website.replace(/^https?:\/\//, '').split('/')[0]
  return host ? `https://www.google.com/s2/favicons?sz=64&domain=${host}` : null
})
</script>

<template>
  <span class="logo" :style="{ background: `hsl(${hue} 22% 24%)` }">
    <img v-if="favicon" :src="favicon" alt="" loading="lazy" @error="($event.target as HTMLImageElement).style.display = 'none'" />
    <span v-else>{{ initials }}</span>
  </span>
</template>
