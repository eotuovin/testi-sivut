import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

export const NAV = [
  { path: '/soita', name: 'soita', label: 'Soita', component: () => import('../views/CallView.vue') },
  { path: '/yritykset', name: 'yritykset', label: 'Yritykset', component: () => import('../views/CompaniesView.vue') },
  { path: '/prospektointi', name: 'prospektointi', label: 'Prospektointi', component: () => import('../views/ProspectingView.vue') },
  { path: '/bookkaukset', name: 'bookkaukset', label: 'Bookkaukset', component: () => import('../views/BookingsView.vue') },
  { path: '/raportit', name: 'raportit', label: 'Raportit', component: () => import('../views/ReportsView.vue') },
  { path: '/oivallukset', name: 'oivallukset', label: 'Oivallukset', component: () => import('../views/InsightsView.vue') },
  { path: '/kampanjat', name: 'kampanjat', label: 'Kampanjat', component: () => import('../views/CampaignsView.vue'), admin: true },
  { path: '/integraatiot', name: 'integraatiot', label: 'Integraatiot', component: () => import('../views/IntegrationsView.vue'), admin: true },
  { path: '/kayttajat', name: 'kayttajat', label: 'Asetukset', component: () => import('../views/UsersView.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/soita' },
    { path: '/login', name: 'login', component: () => import('../views/LoginView.vue'), meta: { public: true } },
    { path: '/yritykset/:id', name: 'yritys', component: () => import('../views/CompanyDetailView.vue') },
    ...NAV.map((n) => ({ path: n.path, name: n.name, component: n.component, meta: { admin: !!n.admin } })),
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.loaded) await auth.load()
  if (to.meta.public) return true
  if (!auth.me) return { name: 'login', query: { next: to.fullPath } }
  if (to.meta.admin && !auth.isAdmin) return { name: 'soita' }
  return true
})

export default router
