import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

/** Main navigation (left rail). `icon` is a small inline SVG path. */
export const NAV = [
  { path: '/haku', name: 'haku', label: 'Haku', icon: 'M10 2a8 8 0 1 0 4.9 14.3l5.4 5.4 1.4-1.4-5.4-5.4A8 8 0 0 0 10 2zm0 2a6 6 0 1 1 0 12 6 6 0 0 1 0-12z', component: () => import('../views/SearchView.vue') },
  { path: '/listat', name: 'listat', label: 'Listat', icon: 'M4 5h16v2H4zm0 6h16v2H4zm0 6h10v2H4z', component: () => import('../views/ListsView.vue') },
  { path: '/soita', name: 'soita', label: 'Soita', icon: 'M6.6 10.8a15 15 0 0 0 6.6 6.6l2.2-2.2a1 1 0 0 1 1-.25 11.4 11.4 0 0 0 3.6.6 1 1 0 0 1 1 1V20a1 1 0 0 1-1 1A17 17 0 0 1 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1 11.4 11.4 0 0 0 .6 3.6 1 1 0 0 1-.25 1z', component: () => import('../views/CallView.vue') },
  { path: '/sekvenssit', name: 'sekvenssit', label: 'Sekvenssit', icon: 'M4 6h4v4H4zm6 1h10v2H10zM4 14h4v4H4zm6 1h10v2H10z', component: () => import('../views/SequencesView.vue') },
  { path: '/tehtavat', name: 'tehtavat', label: 'Tehtävät', icon: 'M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z', component: () => import('../views/TasksView.vue') },
  { path: '/prospektointi', name: 'prospektointi', label: 'Agentti', icon: 'M12 2a5 5 0 0 1 5 5v1h1a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h1V7a5 5 0 0 1 5-5zm0 2a3 3 0 0 0-3 3v1h6V7a3 3 0 0 0-3-3zm-3 8a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3zm6 0a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3z', component: () => import('../views/ProspectingView.vue') },
  { path: '/bookkaukset', name: 'bookkaukset', label: 'Bookkaukset', icon: 'M7 2v2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-2V2h-2v2H9V2zm12 8v10H5V10z', component: () => import('../views/BookingsView.vue') },
  { path: '/raportit', name: 'raportit', label: 'Raportit', icon: 'M4 20h16v2H4zM6 10h3v8H6zm5-6h3v14h-3zm5 4h3v10h-3z', component: () => import('../views/ReportsView.vue') },
  { path: '/oivallukset', name: 'oivallukset', label: 'Oivallukset', icon: 'M12 2a7 7 0 0 0-4 12.7V17a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1v-2.3A7 7 0 0 0 12 2zm-3 18h6v2H9z', component: () => import('../views/InsightsView.vue') },
  { path: '/kampanjat', name: 'kampanjat', label: 'Kampanjat', icon: 'M3 11l18-7-4 18-5-6-5 1zm6 6l4-1 2.5 3 2.5-11z', component: () => import('../views/CampaignsView.vue'), admin: true },
  { path: '/integraatiot', name: 'integraatiot', label: 'Integraatiot', icon: 'M10 4h4v3h3a2 2 0 0 1 2 2v3h3v4h-3v3a2 2 0 0 1-2 2h-3v-3h-4v3H7a2 2 0 0 1-2-2v-3H2v-4h3V9a2 2 0 0 1 2-2h3z', component: () => import('../views/IntegrationsView.vue'), admin: true },
  { path: '/kayttajat', name: 'kayttajat', label: 'Asetukset', icon: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zm8.9 5.4-1.9-.5a7 7 0 0 0 0-1.8l1.9-.5-.7-2.6-1.9.5a7 7 0 0 0-1.3-1.3l.5-1.9-2.6-.7-.5 1.9a7 7 0 0 0-1.8 0l-.5-1.9-2.6.7.5 1.9a7 7 0 0 0-1.3 1.3l-1.9-.5-.7 2.6 1.9.5a7 7 0 0 0 0 1.8l-1.9.5.7 2.6 1.9-.5a7 7 0 0 0 1.3 1.3l-.5 1.9 2.6.7.5-1.9a7 7 0 0 0 1.8 0l.5 1.9 2.6-.7-.5-1.9a7 7 0 0 0 1.3-1.3l1.9.5z', component: () => import('../views/UsersView.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/haku' },
    { path: '/login', name: 'login', component: () => import('../views/LoginView.vue'), meta: { public: true } },
    { path: '/yritykset', redirect: '/haku' },
    { path: '/yritykset/:id', name: 'yritys', component: () => import('../views/CompanyDetailView.vue') },
    { path: '/listat/:id', name: 'lista', component: () => import('../views/ListDetailView.vue') },
    ...NAV.map((n) => ({ path: n.path, name: n.name, component: n.component, meta: { admin: !!n.admin } })),
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.loaded) await auth.load()
  if (to.meta.public) return true
  if (!auth.me) return { name: 'login', query: { next: to.fullPath } }
  if (to.meta.admin && !auth.isAdmin) return { name: 'haku' }
  return true
})

export default router
