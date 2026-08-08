import { createApp } from 'vue'
// 按需组件样式不会自动包含 TDesign 的全局明暗主题 token。
// 仅引入主题变量，继续由构建期 resolver 按需注入各组件样式。
import 'tdesign-vue-next/esm/common/style/web/theme/_index.less'
import './styles/layout.css'
import App from './App.vue'
import { useTheme } from './composables/useTheme.js'

const { init: initTheme } = useTheme()
initTheme()

const app = createApp(App)
app.mount('#app')
