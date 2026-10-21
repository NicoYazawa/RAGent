import { createRouter, createWebHistory } from 'vue-router'
import AppLayout from '@/components/layout/AppLayout.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: AppLayout,
      children: [
        { path: '', redirect: '/chat' },
        { path: 'chat', name: 'chat', component: () => import('@/views/ChatView.vue'), meta: { titleKey: 'nav.chat' } },
        { path: 'admin/kb', name: 'kb', component: () => import('@/views/KbManageView.vue'), meta: { titleKey: 'nav.title.kb' } },
        { path: 'admin/datasources', name: 'datasources', component: () => import('@/views/DatasourceView.vue'), meta: { titleKey: 'nav.title.datasource' } },
        { path: 'admin/playground', name: 'playground', component: () => import('@/views/PlaygroundView.vue'), meta: { titleKey: 'nav.playground' } },
        { path: 'admin/logs', name: 'logs', component: () => import('@/views/DecisionLogView.vue'), meta: { titleKey: 'nav.logs' } },
      ],
    },
  ],
})

// The browser tab title is always RAGent (it does not follow the page or language)
router.afterEach(() => {
  document.title = 'RAGent'
})

export default router
