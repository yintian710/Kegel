import { createRouter, createWebHistory } from 'vue-router'
import { applyDocumentPreferences } from '../composables/usePreferences'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      component: () => import('../pages/HomePage.vue'),
      meta: {
        title: '你今天提肛了吗？ · 提肛打卡',
        description: '每天三次，给自己一点向上的力量。LINUX DO 每日提肛打卡。',
      },
    },
    {
      path: '/practice',
      component: () => import('../pages/PracticePage.vue'),
      meta: {
        title: '提肛练习',
        description: '提肛练习，可配置次数、间隔和浏览器提醒，无需登录即可使用。',
      },
    },
    {
      path: '/shop',
      component: () => import('../pages/ShopPage.vue'),
      meta: {
        title: '商店 · 提肛打卡',
        description: '使用站内积分兑换 LDC，购买后自动发货到 Linux DO 账户。',
      },
    },
    {
      path: '/donate',
      component: () => import('../pages/DonatePage.vue'),
      meta: {
        title: 'LDC 赞助 · 提肛打卡',
        description: '通过 LINUX DO Credit 赞助本站，查看已确认的 LDC 赞助榜。',
      },
    },
    {
      path: '/admin',
      component: () => import('../pages/AdminPage.vue'),
      meta: { title: '管理后台 · 提肛打卡', description: '' },
    },
  ],
})

router.afterEach((to) => {
  applyDocumentPreferences(String(to.meta.title ?? ''), String(to.meta.description ?? ''))
})

export default router
