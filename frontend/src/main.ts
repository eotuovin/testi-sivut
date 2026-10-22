import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './styles.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
window.addEventListener('luuri:unauthenticated', () => {
  if (router.currentRoute.value.name !== 'login') router.push({ name: 'login' })
})
app.mount('#app')
