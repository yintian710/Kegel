import { computed, ref } from 'vue'
import {
  admin,
  ApiError,
  loginUrl,
  type AdminOverviewData,
  type AdminUser,
  type AdminVisit,
  type AdminWallet,
  type Product,
  type Purchase,
  type RewardTier,
  type SaveProductInput,
  type Settings,
} from '../api'
import { useIdentity } from './useIdentity'

export type ToastTone = 'ok' | 'err' | 'info'
export interface Toast { id: number; text: string; tone: ToastTone }

export interface PendingAction {
  title: string
  description: string
  check: string
  secret: boolean
  danger?: boolean
  success: string
  run: (secret: string) => Promise<unknown>
  afterSuccess?: () => void
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败。'
}

function headers(secret = '') {
  return secret ? { headers: { 'X-Secondary-Password': secret } } : {}
}

export function useAdmin() {
  const identity = useIdentity()
  const data = ref<AdminOverviewData | null>(null)
  const loading = ref(true)
  const busy = ref(false)
  const denied = ref('')
  const users = ref<AdminUser[] | null>(null)
  const toasts = ref<Toast[]>([])
  const pending = ref<PendingAction | null>(null)
  const confirmError = ref('')
  const creditTarget = ref<AdminWallet | AdminUser | null>(null)
  const creditError = ref('')
  let creditRequest: { id: string; amount: string } | null = null
  let toastSeq = 0

  // 待处理事项：待人工核对的订单 + 被标记且未批准的访问
  const uncertainOrders = computed(() => (data.value?.purchases ?? []).filter((p) => p.status === 'uncertain'))
  const flaggedVisits = computed(() => (data.value?.visits ?? []).filter((v) => v.reason && !v.approved))
  const todoCount = computed(() => uncertainOrders.value.length + flaggedVisits.value.length)

  function toast(text: string, tone: ToastTone = 'ok'): void {
    const id = ++toastSeq
    toasts.value.push({ id, text, tone })
    window.setTimeout(() => dismissToast(id), tone === 'err' ? 6000 : 3500)
  }
  function dismissToast(id: number): void {
    toasts.value = toasts.value.filter((t) => t.id !== id)
  }

  function handleAuth(error: unknown): void {
    if (error instanceof ApiError && error.status === 401 && identity.oauthReady.value) {
      data.value = null
      window.location.assign(loginUrl('/admin'))
    }
  }

  async function refresh(): Promise<void> {
    try {
      data.value = await admin.overview(headers())
    } catch (error) {
      handleAuth(error)
      throw error
    }
  }

  async function init(): Promise<void> {
    if (!(await identity.requireLogin('/admin'))) return
    loading.value = true
    try {
      await refresh()
    } catch (error) {
      denied.value = errorText(error)
    } finally {
      loading.value = false
    }
  }

  async function reload(): Promise<void> {
    busy.value = true
    try {
      await refresh()
      toast('数据已刷新')
    } catch (error) {
      toast(errorText(error), 'err')
    } finally {
      busy.value = false
    }
  }

  // 不需要二次确认的直接操作
  async function direct(run: () => Promise<unknown>, success: string): Promise<boolean> {
    if (busy.value) return false
    busy.value = true
    try {
      await run()
      await refresh()
      toast(success)
      return true
    } catch (error) {
      handleAuth(error)
      toast(errorText(error), 'err')
      return false
    } finally {
      busy.value = false
    }
  }

  // ── 二次确认流程 ──
  function ask(action: PendingAction): void {
    confirmError.value = ''
    pending.value = action
  }
  function cancelAsk(): void {
    if (busy.value) return
    pending.value = null
  }
  async function confirmAsk(secret: string): Promise<void> {
    const action = pending.value
    if (!action || busy.value) return
    if (action.secret && !secret) {
      confirmError.value = '请输入二级密码以确认操作'
      return
    }
    busy.value = true
    try {
      await action.run(secret)
      pending.value = null
      action.afterSuccess?.()
      toast(action.success)
      await refresh()
    } catch (error) {
      handleAuth(error)
      confirmError.value = errorText(error)
    } finally {
      busy.value = false
    }
  }

  // ── 业务动作 ──
  function saveBase(value: Pick<Settings, 'deadline' | 'min_step_seconds' | 'condition_url'>): Promise<boolean> {
    return direct(() => admin.saveSettings(value, headers()), '基础规则已更新')
  }

  function saveRewards(tiers: RewardTier[]): void {
    if (!data.value) return
    const settings = data.value.settings
    ask({
      title: '保存排名奖励',
      description: '修改排名奖励会调整用户每日打卡可领取的站内积分。',
      check: '我已核对各档位名次与积分数值，确认保存生效。',
      secret: true,
      success: '排名奖励已保存',
      run: (secret) => admin.saveSettings(
        { ...settings, reward_tiers: tiers, secondary_secret: secret, secondary_password: secret },
        headers(secret),
      ),
    })
  }

  function saveNoPayout(ids: string[]): void {
    ask({
      title: '保存不发货名单',
      description: `名单共 ${ids.length} 人。名单内用户的兑换订单仍显示成功，但不会调用 Credit 转账。`,
      check: '我已核对名单，确认保存生效。',
      secret: true,
      danger: true,
      success: '不发货名单已保存',
      run: (secret) => admin.saveSettings(
        { no_payout_user_ids: ids, secondary_secret: secret, secondary_password: secret },
        headers(secret),
      ),
    })
  }

  function review(visit: AdminVisit): void {
    ask({
      title: '批准异常访问',
      description: `批准 ${visit.username ? '@' + visit.username : '匿名访客'} 的打卡资格？标记原因：${visit.reason}`,
      check: '我已核实访问行为，确认解除限制。',
      secret: false,
      success: '已批准',
      run: () => admin.review({ user_id: visit.user_id, approved: true }, headers()),
    })
  }

  function openToday(): void {
    if (!data.value) return
    ask({
      title: '手动开放今日打卡',
      description: `立即开放 ${data.value.status.day} 的打卡，开放后登录用户可正式参与练习与排名。`,
      check: '我确认立即开放今日打卡。',
      secret: false,
      success: '今日打卡已开放',
      run: () => admin.open(headers()),
    })
  }

  function saveProduct(product: SaveProductInput, afterSuccess: () => void): void {
    ask({
      title: product.id ? `更新商品 #${product.id}` : '上架新商品',
      description: product.category === 'TICKET'
        ? `抽卡券「${product.name}」· ${product.draw_count} 抽 · 售价 ${product.points_price} 积分${product.promo_enabled ? ` · 限时折扣 ${(product.promo_discount_bp ?? 0) / 1000} 折` : ''}。`
        : `「${product.name}」· 售价 ${product.points_price} 积分 · 发货 ${product.ldc_amount} LDC${product.promo_enabled ? ` · 限时折扣 ${(product.promo_discount_bp ?? 0) / 1000} 折` : ''}。购买后将自动调用 Credit 接口发货。`,
      check: '我已核对商品售价与发货数量。',
      secret: true,
      success: product.id ? '商品已更新' : '新商品已上架',
      afterSuccess,
      run: (secret) => admin.saveProduct(
        { ...product, secondary_secret: secret, secondary_password: secret },
        headers(secret),
      ),
    })
  }

  function archiveProduct(product: Product): void {
    ask({
      title: `下架商品 #${product.id}`,
      description: `下架「${product.name}」后，用户将无法在商店兑换该商品。`,
      check: '我确认下架该商品。',
      secret: true,
      danger: true,
      success: '商品已下架',
      run: (secret) => admin.archiveProduct(product.id, headers(secret)),
    })
  }

  function reconcile(order: Purchase, result: 'success' | 'failed'): void {
    const delivered = result === 'success'
    ask({
      title: delivered ? `确认订单 ${order.order_no} 已发货` : `确认订单 ${order.order_no} 未发货并退分`,
      description: delivered
        ? `@${order.username} 兑换 ${order.ldc_amount} LDC 的订单将标记为发货成功，已扣的 ${order.points_cost} 积分不退。请先在 Credit 商户后台确认这笔转账确实已发出。`
        : `@${order.username} 兑换 ${order.ldc_amount} LDC 的订单将标记为失败，并退还 ${order.points_cost} 积分。请先在 Credit 商户后台确认转账没有发出，否则会重复发放。`,
      check: delivered ? '我已在 Credit 商户后台核实该笔 LDC 已发出。' : '我已在 Credit 商户后台核实该笔 LDC 没有发出。',
      secret: true,
      danger: !delivered,
      success: delivered ? '订单已标记为发货成功' : '订单已标记为失败，积分已退还',
      run: (secret) => admin.reconcilePurchase(order.order_no, { result, secondary_secret: secret }, headers(secret)),
    })
  }

  // ── 向 Credit 查询发货状态（后台也每 5 分钟自动跑一次） ──
  async function checkOrder(order: Purchase): Promise<void> {
    if (busy.value) return
    busy.value = true
    try {
      const result = await admin.checkPurchase(order.order_no, headers())
      await refresh()
      toast(`${order.order_no}：${result.message}`, result.outcome === 'unknown' ? 'err' : 'ok')
    } catch (error) {
      handleAuth(error)
      toast(errorText(error), 'err')
    } finally {
      busy.value = false
    }
  }

  async function checkAll(): Promise<void> {
    if (busy.value) return
    busy.value = true
    try {
      const { checked, reasons } = await admin.checkAllPurchases(headers())
      await refresh()
      const labels: Array<[keyof typeof checked, string]> = [
        ['success', '笔确认已发货'], ['failed', '笔判定未发货并已退分'],
        ['waiting', '笔下单不满 30 秒，稍后再查'], ['unknown', '笔暂时无法确认'], ['error', '笔查询出错'],
      ]
      const parts = labels.filter(([key]) => checked[key]).map(([key, text]) => `${checked[key]} ${text}`)
      const why = checked.unknown && reasons.length ? `（原因：${reasons.join('；')}）` : ''
      toast(parts.length ? parts.join('，') + why : '没有待核对的订单', checked.unknown || checked.error ? 'err' : 'ok')
    } catch (error) {
      handleAuth(error)
      toast(errorText(error), 'err')
    } finally {
      busy.value = false
    }
  }

  async function search(query: string): Promise<void> {
    busy.value = true
    try {
      users.value = (await admin.users(query, headers())).users
      toast(`找到 ${users.value.length} 位用户（最多显示 50 位）`, 'info')
    } catch (error) {
      handleAuth(error)
      toast(errorText(error), 'err')
    } finally {
      busy.value = false
    }
  }

  // ── 加积分（request_id 在金额不变时复用，保证重试幂等） ──
  function openCredit(user: AdminWallet | AdminUser): void {
    creditTarget.value = user
    creditError.value = ''
    creditRequest = null
  }
  function closeCredit(): void {
    if (busy.value) return
    creditTarget.value = null
  }
  async function submitCredit(amountValue: number, secret: string): Promise<void> {
    const target = creditTarget.value
    if (!target || busy.value) return
    const amount = String(amountValue)
    if (!creditRequest || creditRequest.amount !== amount) creditRequest = { id: crypto.randomUUID(), amount }
    busy.value = true
    let credited = false
    try {
      const result = await admin.addPoints(
        { user_id: target.user_id, amount, request_id: creditRequest.id, secondary_secret: secret },
        headers(secret),
      )
      credited = true
      creditTarget.value = null
      toast(`已向 @${result.user.username} 增加 ${result.entry.delta} 积分，当前余额 ${result.wallet.balance}`)
      await refresh()
    } catch (error) {
      handleAuth(error)
      if (credited) toast(`加积分已成功，但刷新失败：${errorText(error)}`, 'err')
      else creditError.value = errorText(error)
    } finally {
      busy.value = false
    }
  }

  return {
    data, loading, busy, denied, users, toasts, pending, confirmError, creditTarget, creditError,
    uncertainOrders, flaggedVisits, todoCount,
    toast, dismissToast, init, reload,
    ask, cancelAsk, confirmAsk,
    saveBase, saveRewards, saveNoPayout, review, openToday,
    saveProduct, archiveProduct, reconcile, checkOrder, checkAll,
    search, openCredit, closeCredit, submitCredit,
  }
}
