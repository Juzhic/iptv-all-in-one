import { createApp } from 'vue'
import TDesign from 'tdesign-vue-next'
import 'tdesign-vue-next/es/style/index.css'
import App from './App.vue'
import { useTheme } from './composables/useTheme.js'

const { init: initTheme } = useTheme()
initTheme()

const app = createApp(App)
app.use(TDesign)
app.mount('#app')
