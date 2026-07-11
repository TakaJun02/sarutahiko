import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '../stores/auth'
import ChatView from '../views/ChatView.vue'
import LoginView from '../views/LoginView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: () => {
        const auth = useAuthStore()
        return auth.token ? '/app/chat' : '/login'
      },
    },
    {
      path: '/login',
      name: 'login',
      component: LoginView,
    },
    {
      path: '/app/chat',
      name: 'chat',
      component: ChatView,
      meta: { requiresAuth: true },
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!to.meta.requiresAuth) {
    return true
  }
  if (!auth.token) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  try {
    await auth.ensureSession()
    return true
  } catch (error) {
    auth.clearSession()
    return { name: 'login', query: { redirect: to.fullPath } }
  }
})

export default router
