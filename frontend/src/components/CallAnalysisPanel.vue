<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { apiGet, apiPost, errorText } from '../api/client'
import type { CallAnalysisBundle } from '../api/intelligence'
import { BLOCKER_FI, OBJECTION_FI, SENTIMENT_FI, STAGE_FI } from '../api/intelligence'

const props = defineProps<{ callId: string; hasNotes: boolean }>()
const bundle = ref<CallAnalysisBundle | null>(null)
const error = ref('')
const consent = ref(false)
const uploading = ref(false)
const showTranscript = ref(false)

async function load() {
  try {
    bundle.value = await apiGet<CallAnalysisBundle>(`/calls/${props.callId}/analysis`)
  } catch (e) {
    error.value = errorText(e)
  }
}
onMounted(load)

async function analyze(source: 'notes' | 'transcript') {
  error.value = ''
  try {
    await apiPost(`/calls/${props.callId}/analyze`, { source })
    await load()
  } catch (e) {
    error.value = errorText(e)
  }
}
async function upload(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  uploading.value = true
  error.value = ''
  const fd = new FormData()
  fd.append('file', file)
  fd.append('consent', String(consent.value))
  try {
    await apiPost(`/calls/${props.callId}/recording`, fd)
    await load()
  } catch (e) {
    error.value = errorText(e)
  } finally {
    uploading.value = false
    input.value = ''
  }
}
</script>

<template>
  <div class="small">
    <p v-if="error" class="error">{{ error }}</p>
    <template v-if="bundle">
      <div v-for="a in bundle.analyses" :key="a.id" style="margin-bottom: 0.5rem">
        <div class="muted">Analyysi {{ a.source === 'transcript' ? 'litteroinnista' : 'muistiinpanoista' }} · {{ a.status }}<span v-if="a.agent"> · {{ a.agent }}</span></div>
        <template v-if="a.status === 'done'">
          <div class="row" style="gap: 0.35rem; margin: 0.25rem 0">
            <span v-if="a.sentiment" class="tag" :class="{ ok: a.sentiment === 'positive', danger: a.sentiment === 'negative', warn: a.sentiment === 'mixed' }">{{ SENTIMENT_FI[a.sentiment] }}</span>
            <span v-if="a.interest_level !== null" class="tag">kiinnostus {{ a.interest_level }}/5</span>
            <span v-if="a.stage_reached" class="tag">eteni: {{ STAGE_FI[a.stage_reached] ?? a.stage_reached }}</span>
            <span v-if="a.reached_decision_maker !== null" class="tag">{{ a.reached_decision_maker ? 'päättäjä tavoitettu' : 'ei päättäjää' }}</span>
          </div>
          <div v-if="a.summary_fi">{{ a.summary_fi }}</div>
          <div v-if="a.objections.length" style="margin-top: 0.25rem">
            <strong>Vastaväitteet:</strong>
            <span v-for="(o, i) in a.objections" :key="i" class="tag" :class="o.handled ? 'ok' : 'warn'" style="margin: 0 0.25rem 0.25rem 0" :title="(o.detail_fi ?? '') + (o.quote_redacted ? ' – “' + o.quote_redacted + '”' : '')">
              {{ OBJECTION_FI[o.category] ?? o.category }}{{ o.handled ? ' ✓' : '' }}
            </span>
          </div>
          <div v-if="a.blockers.length"><strong>Estot:</strong> {{ a.blockers.map((b) => BLOCKER_FI[b.category] ?? b.category).join(', ') }}</div>
          <div v-if="a.buying_signals.length"><strong>Ostosignaalit:</strong> {{ a.buying_signals.map((s) => s.signal_fi).join(' · ') }}</div>
          <div v-if="a.friction.length"><strong>Kitka:</strong> {{ a.friction.map((f) => f.moment_fi + (f.cause_fi ? ' (' + f.cause_fi + ')' : '')).join(' · ') }}</div>
          <div v-if="a.next_step_fi"><strong>Seuraava askel:</strong> {{ a.next_step_fi }}</div>
          <div v-if="a.coaching_fi" class="muted">💡 {{ a.coaching_fi }}</div>
        </template>
        <div v-else-if="a.status === 'failed'" class="error">{{ a.error }}</div>
        <div v-else-if="a.status === 'pending'" class="muted">Jonossa – analysoidaan kun tekoäly on käytettävissä.</div>
      </div>

      <div v-for="r in bundle.recordings" :key="r.id" class="muted">
        Nauhoite ({{ r.source === 'upload' ? 'ladattu' : 'puhelinpalvelu' }}): {{ r.status }}<span v-if="r.duration_seconds"> · {{ Math.round(r.duration_seconds / 60) }} min</span><span v-if="r.error" class="error"> {{ r.error }}</span>
      </div>
      <div v-if="bundle.transcript">
        <a v-if="bundle.transcript.text" href="#" @click.prevent="showTranscript = !showTranscript">{{ showTranscript ? 'Piilota' : 'Näytä' }} litterointi</a>
        <span v-else class="muted">Litterointi poistettu säilytysajan päätyttyä; analyysi säilyy.</span>
        <div v-if="showTranscript && bundle.transcript.text" class="script" style="max-height: 240px; overflow: auto; margin-top: 0.25rem">{{ bundle.transcript.text }}</div>
      </div>

      <div class="row" style="margin-top: 0.4rem; gap: 0.5rem">
        <button v-if="hasNotes" class="small" @click="analyze('notes')">{{ bundle.analyses.some((a) => a.source === 'notes') ? 'Analysoi uudelleen' : 'Analysoi muistiinpanot' }}</button>
        <label class="small" style="margin: 0"><input v-model="consent" type="checkbox" style="width: auto; margin-right: 0.3rem" />Asiakkaalle kerrottiin tallennuksesta</label>
        <label class="btn small" :style="{ opacity: consent ? 1 : 0.5 }" style="margin: 0">{{ uploading ? 'Ladataan…' : 'Lataa nauhoite' }}
          <input type="file" accept="audio/*,.m4a,.mp3,.wav,.ogg" style="display: none" :disabled="!consent || uploading" @change="upload" />
        </label>
      </div>
    </template>
  </div>
</template>
