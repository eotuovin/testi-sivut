<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { errorText } from '../api/client'
import { SESSION_LABELS, useTelephonyStore } from '../stores/telephony'

const props = defineProps<{ taskId: string | null; companyId: string; contactId: string | null; phone: string | null }>()
const emit = defineEmits<{ (e: 'started'): void }>()
const tel = useTelephonyStore()
const error = ref('')
const busy = ref(false)
const now = ref(Date.now())
const tick = window.setInterval(() => (now.value = Date.now()), 1000)
onBeforeUnmount(() => window.clearInterval(tick))

const elapsed = computed(() => {
  const s = tel.session
  if (!s) return null
  const start = s.answered_at ? new Date(s.answered_at).getTime() : null
  if (!start) return null
  const end = s.ended_at ? new Date(s.ended_at).getTime() : now.value
  const sec = Math.max(0, Math.floor((end - start) / 1000))
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`
})

async function dial() {
  if (!props.phone) return
  busy.value = true
  error.value = ''
  try {
    await tel.dial({ task_id: props.taskId ?? undefined, company_id: props.companyId, contact_id: props.contactId, phone: props.phone })
    emit('started')
  } catch (e) {
    error.value = errorText(e)
  } finally {
    busy.value = false
  }
}
async function hangup() {
  busy.value = true
  try {
    await tel.hangup()
  } catch (e) {
    error.value = errorText(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div v-if="tel.status?.enabled" class="dial">
    <div v-if="!tel.myPhone" class="small muted">
      Lisää oma numerosi <router-link to="/kayttajat">asetuksiin</router-link>, niin voit soittaa tästä napista: Luuri soittaa ensin sinulle ja yhdistää sitten asiakkaalle.
    </div>
    <template v-else>
      <div class="row">
        <button v-if="!tel.active" class="primary big" :disabled="!phone || busy" @click="dial">☎ Soita Luurilla</button>
        <button v-else class="danger big" :disabled="busy" @click="hangup">Lopeta puhelu</button>
        <div v-if="tel.session" class="small">
          <span class="tag" :class="{ ok: tel.session.state === 'in_progress' || tel.session.state === 'ended', warn: tel.session.state === 'dialing_agent' || tel.session.state === 'connecting', danger: ['failed', 'busy', 'no_answer'].includes(tel.session.state) }">
            {{ SESSION_LABELS[tel.session.state] }}
          </span>
          <span v-if="elapsed" class="timer"> {{ elapsed }}</span>
          <span v-if="tel.session.error" class="error"> {{ tel.session.error }}</span>
        </div>
      </div>
      <div class="small muted" style="margin-top: 0.25rem">
        Asiakas näkee numeron {{ tel.status.from_number }}. Sinun puhelimeesi ({{ tel.myPhone }}) soitetaan ensin.
      </div>
    </template>
    <p v-if="error" class="error small">{{ error }}</p>
  </div>
</template>
