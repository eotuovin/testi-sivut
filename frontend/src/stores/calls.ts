import { defineStore } from 'pinia'
import { apiGet, apiPost } from '../api/client'
import type { Booking, CallLog, Callback, Campaign, Task } from '../api/types'

export const useCallsStore = defineStore('calls', {
  state: () => ({
    campaigns: [] as Campaign[],
    campaignId: (localStorage.getItem('luuri.campaign') || '') as string,
    task: null as Task | null,
    loading: false,
    queueEmpty: false,
    callStartedAt: null as number | null,
    callbacks: [] as Callback[],
    lastBooking: null as Booking | null,
  }),
  getters: {
    activeCampaigns: (s) => s.campaigns.filter((c) => c.status === 'active'),
  },
  actions: {
    async loadCampaigns() {
      this.campaigns = await apiGet<Campaign[]>('/campaigns')
      if (!this.campaignId && this.activeCampaigns.length === 1) this.setCampaign(this.activeCampaigns[0].id)
    },
    setCampaign(id: string) {
      this.campaignId = id
      localStorage.setItem('luuri.campaign', id)
    },
    async next() {
      this.loading = true
      this.lastBooking = null
      try {
        const t = await apiPost<Task | null>('/calls/next', undefined, { campaign_id: this.campaignId || undefined })
        this.task = t
        this.queueEmpty = t === null
        this.callStartedAt = null
      } finally {
        this.loading = false
      }
    },
    startTimer() {
      if (!this.callStartedAt) this.callStartedAt = Date.now()
    },
    async log(body: CallLog) {
      if (!this.task) return
      const duration = this.callStartedAt ? Math.round((Date.now() - this.callStartedAt) / 1000) : undefined
      const res = await apiPost<{ booking: Booking | null }>('/calls', { task_id: this.task.id, duration_seconds: duration, ...body })
      this.lastBooking = res.booking
      this.task = null
      this.callStartedAt = null
      await this.loadCallbacks()
    },
    async release() {
      if (!this.task) return
      await apiPost(`/calls/tasks/${this.task.id}/release`)
      this.task = null
      this.callStartedAt = null
    },
    async loadCallbacks() {
      this.callbacks = await apiGet<Callback[]>('/calls/callbacks')
    },
  },
})
