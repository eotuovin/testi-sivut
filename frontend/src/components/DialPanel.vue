<script setup lang="ts">
/** The dial button. Two modes, decided by the server:
 *  - browser: Telnyx WebRTC — the call plays in this tab, headset + microphone
 *  - bridged (46elks): the provider rings the seller's own phone first */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
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

onMounted(async () => {
  // Connect the browser dialer early so the first call does not wait for the login.
  if (tel.browser && !tel.rtcReady) {
    try { await tel.connectBrowser() } catch (e) { error.value = errorText(e) }
  }
})

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
    const msg = errorText(e)
    error.value = /permission|NotAllowed|mikrofoni/i.test(msg) ? 'Selain esti mikrofonin. Salli mikrofoni osoiterivin kuvakkeesta ja yritä uudelleen.' : msg
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
    <!-- browser mode -->
    <template v-if="tel.browser">
      <audio id="luuri-remote-audio" autoplay></audio>
      <div class="row">
        <button v-if="!tel.active" class="primary big" :disabled="!phone || busy" @click="dial">🎧 Soita selaimessa</button>
        <template v-else>
          <button class="danger big" :disabled="busy" @click="hangup">Lopeta puhelu</button>
          <button :disabled="tel.session?.state !== 'in_progress'" :class="{ selected: tel.muted }" @click="tel.toggleMute()">{{ tel.muted ? '🔇 Mykistetty' : '🎙 Mykistä' }}</button>
        </template>
        <div v-if="tel.session" class="small">
          <span class="tag" :class="{ ok: tel.session.state === 'in_progress' || tel.session.state === 'ended', warn: tel.session.state === 'connecting', danger: ['failed', 'busy', 'no_answer'].includes(tel.session.state) }">
            {{ SESSION_LABELS[tel.session.state] }}
          </span>
          <span v-if="elapsed" class="timer"> {{ elapsed }}</span>
          <span v-if="tel.session.error" class="error"> {{ tel.session.error }}</span>
        </div>
      </div>
      <div class="small muted" style="margin-top: 0.25rem">
        Puhelu kuuluu kuulokkeissa. Asiakas näkee numeron {{ tel.status.from_number }}.
        <span v-if="tel.status.recording"> Puhelu nauhoitetaan, kun merkitset lopputulokseen, että kerroit siitä asiakkaalle.</span>
        <span v-if="!tel.rtcReady" class="warn"> · yhdistetään puhelinpalveluun…</span>
      </div>
    </template>

    <!-- bridged mode (46elks) -->
    <template v-else>
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
    </template>
    <p v-if="error" class="error small">{{ error }}</p>
  </div>
</template>

<style scoped>
button.selected { outline: 2px solid var(--accent); }
.warn { color: var(--warn); }
</style>
