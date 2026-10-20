import { createApp } from 'vue'
import { createPinia } from 'pinia'
// 字体本地化：随包构建，避免外网 CDN 不可达时回落到系统字体
import '@fontsource/public-sans/400.css'
import '@fontsource/public-sans/500.css'
import '@fontsource/public-sans/600.css'
import '@fontsource/public-sans/700.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'
import '@fontsource/jetbrains-mono/600.css'
import App from './App.vue'
import router from './router'
import i18n from './i18n'
import { useLocaleStore } from './stores/locale'
import './styles/theme.css'

const app = createApp(App)
app.use(createPinia())
app.use(i18n)
useLocaleStore().initLocale()
app.use(router)
app.mount('#app')
