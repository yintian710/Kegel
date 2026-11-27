import { http, type RequestConfig } from './http'

export interface User {
  id: string
  username: string
  name: string
}

export interface RewardTier { through: number; amount: number }
export interface Wallet { balance: number }
export interface Quota { limit: string; used: string; remaining: string }

export interface CheckinEntry {
  day: string
  user_id: string
  username: string
  rank: number
  amount: number
  completed_at: string
  claimed_at: string | null
  reward_status: 'unclaimed' | 'credited' | 'none'
  flow_id: string | null
  skipped?: boolean
  streak_days?: number
  reward_bonus_percent?: number
}

export interface Session {
  token: string
  mode: 'manual' | 'auto'
  repetitions: number
  step: number
  completed: boolean
  eligible: boolean
  wait_seconds: number
  expires_in: number | null
  interval_seconds?: number
  min_seconds?: number
}

export interface Review { reason: string; approved: boolean | number }
// rank 为不含「不发货名单」用户的名次；名单用户 skipped=true、rank=null（不占名次、奖励不变）；position 为完成先后序号
export interface CheckinLeaderboardItem { rank: number | null; position: number; skipped: boolean; username: string; amount: number; reward_status: CheckinEntry['reward_status']; completed_at: string }
// 连续打卡榜：streak_days 为当前连续工作日数；done_today=今日已打卡（否则是上个工作日已打、连续仍有效）
export interface StreakBoardItem { rank: number | null; position: number; skipped: boolean; username: string; streak_days: number; done_today: boolean }
export interface StreakBoardData { day: string; items: StreakBoardItem[] }

export interface StatusData {
  user: User | null
  day: string
  is_open: boolean
  opened_at: string | null
  open_reason: string
  deadline: string
  timezone: string
  min_step_seconds: number
  reward_tiers: RewardTier[]
  wallet: Wallet | null
  quota: Quota
  oauth_ready: boolean
  total: number
  entry: CheckinEntry | null
  session: Session | null
  review: Review | null
  leaderboard: CheckinLeaderboardItem[]
  streak_days?: number
}

export interface SessionStartInput {
  mode?: 'manual' | 'auto'
  repetitions?: number
  interval_seconds?: number
}
export interface SessionData { session: Session }
export interface SessionCompleteData extends SessionData { entry: CheckinEntry }
export interface ClaimData { entry: CheckinEntry; wallet: Wallet; quota: Quota }

export interface PracticeLeaderboardItem { rank: number; username: string; count: number }
export interface PracticeRecord {
  round_id: string
  started_at: number
  ended_at: number
  repetitions: number
  interval_seconds: number
  mode: 'manual' | 'auto'
}
export interface PracticeData {
  user: User | null
  oauth_ready: boolean
  day: string
  leaderboard: PracticeLeaderboardItem[]
  total_leaderboard: PracticeLeaderboardItem[]
  records: PracticeRecord[]
}
export interface PracticeUploadInput extends PracticeRecord { expected_user_id?: string }
export interface PracticeUploadData extends PracticeData { record: PracticeRecord }

export interface LedgerEntry {
  id: string
  kind: string
  reference: string
  delta: number
  balance_after: number
  created_at: string
}
export interface AdminCreditEntry extends Omit<LedgerEntry, 'created_at'> { user_id: string; created_at: number }
export interface Product {
  id: string
  category: string
  name: string
  description: string
  points_price: number
  ldc_amount: string
  user_daily_limit: number
  total_daily_limit: number
  is_active: boolean
  total_today_count: number
  total_remaining: number | null
  user_today_count: number
  user_remaining: number | null
  draw_count?: number
  discount_eligible?: number
  special_discount_bp?: number | null
  // 限时折扣：promo_bp 为折扣力度（8000=8 折），promo_ends_at 为结束时间（epoch 秒），与称号折扣叠加
  promo_enabled?: number
  promo_bp?: number | null
  promo_ends_at?: number | null
  promo_active?: boolean
  price_now?: number
}
export interface Purchase {
  order_no: string
  product_id: string
  category: string
  product_name: string
  user_id: string
  username: string
  points_cost: number
  ldc_amount: string
  status: 'pending' | 'success' | 'simulated' | 'failed' | 'uncertain'
  trade_no: string
  error: string
  created_at: string | number
  no_payout?: boolean
  day: string
  request_id: string | null
}
export interface ShopData {
  user: User | null
  oauth_ready: boolean
  wallet: Wallet | null
  quota: Quota
  discount: ShopDiscount
  ledger: LedgerEntry[]
  products: Product[]
  purchases: Purchase[]
}
export interface ShopDiscount { bp: number; label: string; saved_today: number; cap: number; remaining: number }
export interface PurchaseInput { product_id: string; request_id: string }
export interface PurchaseData { order: Purchase; status: Purchase['status']; trade_no: string; error: string }
export type CheckOutcome = 'success' | 'failed' | 'waiting' | 'unknown' | 'settled'
export interface OrderCheckData { order: Purchase; outcome: CheckOutcome; message: string; wallet?: Wallet }
export interface CheckAllData { checked: Partial<Record<CheckOutcome | 'error', number>>; reasons: string[] }

export type Rarity = 'N' | 'R' | 'SR' | 'SSR' | 'UR'
export type TicketType = 'single' | 'ten' | 'hundred'
export interface TicketBalances { single: number; ten: number; hundred: number }
export interface TitleItem {
  id: string
  code: string
  rarity: Rarity
  weight: number
  discount_bp: number
  is_active: boolean
  is_limited: boolean
  is_smeltable: boolean
  name: string
  description: string
  icon: string
  route: string
  copies: number
  owned: boolean
}
export interface TicketProduct { id: string; name: string; description: string; points_price: number; draw_count: number; price_now?: number; promo_active?: boolean }
export interface DrawHistoryItem { id: string; title_id: string; rarity: Rarity; is_new: boolean; created_at: string }
export interface TitleData {
  user: User | null
  tickets: TicketBalances
  pity: number
  pity_limit: number
  equipped_title_id: string | null
  collection: TitleItem[]
  ticket_products: TicketProduct[]
  recipes: Array<{ id: string; output_code: string; materials: string[] }>
  wallet: Wallet | null
  history: { draws: DrawHistoryItem[]; crafts: Array<Record<string, unknown>> }
}
export interface DrawInput { ticket_type: TicketType; request_id: string }
export interface DrawResultItem {
  title_id: string
  rarity: Rarity
  is_new: boolean
  name?: string
  description?: string
  icon?: string
}
export interface DrawData {
  batch: { id: string; ticket_type: TicketType; count: number }
  results: DrawResultItem[]
  pity: number
  pity_limit: number
  tickets: TicketBalances
}
export interface TicketPurchaseData { order: { order_no: string; product_name: string; points_cost: number; draw_count: number }; status: string; ticket_type: TicketType | null; tickets: TicketBalances; wallet: Wallet }
export interface SmeltData { kind: string; output: { title_id: string; rarity: Rarity; is_new: boolean }; consumed: Array<{ title_id: string; count: number }>; collection: { copies: number } }

export interface DonationLeaderboardItem { rank: number; username: string; amount: string; count: number }
export interface DonationOrder { order_no: string; amount: string; status: 'created' | 'paid'; created_at: string; paid_at: string | null }
export interface DonationsData {
  user: User | null
  oauth_ready: boolean
  donation_ready: boolean
  donation_leaderboard: DonationLeaderboardItem[]
  donation_orders: DonationOrder[]
}
export interface DonationPayment { action: string; fields: Record<string, string> }
export interface DonationCreateData { order: DonationOrder; payment: DonationPayment }

export interface Settings { deadline: string; min_step_seconds: number; reward_tiers: RewardTier[]; condition_url: string; no_payout_user_ids: string[] }
export interface AdminVisit { user_id: string; username: string; count: number; last_seen: string; reason: string; approved: boolean | number }
export interface AdminWallet { user_id: string; username: string; balance: number }
export interface PracticeTrigger {
  day: string
  user_id: string
  username: string
  group_no: number
  created_at: string
  flow_id: string
}
export interface AdminOverviewData {
  settings: Settings
  status: StatusData
  visits: AdminVisit[]
  rewards: CheckinEntry[]
  wallets: AdminWallet[]
  practice_triggers: PracticeTrigger[]
  products: Product[]
  purchases: Purchase[]
  admin_credit_enabled: boolean
}
export interface AdminUser { user_id: string; username: string }
export interface AdminUsersData { users: AdminUser[] }
export interface SaveSettingsInput extends Partial<Settings> { secondary_secret?: string; secondary_password?: string }
export interface ReviewInput { user_id: string; approved: true }
export interface AddPointsInput { user_id: string; amount: number | string; request_id: string; secondary_secret: string }
export interface AddPointsData { user: Pick<User, 'id' | 'username'>; wallet: Wallet; entry: AdminCreditEntry }
export interface SaveProductInput {
  id?: string
  category: 'LDC' | 'TICKET'
  name: string
  description: string
  points_price: number
  ldc_amount: string
  user_daily_limit: number
  total_daily_limit: number
  is_active: boolean
  draw_count?: number
  promo_enabled?: boolean
  promo_discount_bp?: number
  promo_ends_at?: number
  secondary_secret?: string
  secondary_password?: string
}
export interface SaveProductData { product: Product }
export type EmptyData = Record<string, never> | null
export interface ReconcileInput { result: 'success' | 'failed'; trade_no?: string; secondary_secret?: string }
export interface ReconcileData { order: Purchase }

async function get<T>(url: string, config?: RequestConfig): Promise<T> {
  return (await http.get<T>(url, config)).data
}
async function post<T>(url: string, body: unknown, config?: RequestConfig): Promise<T> {
  return (await http.post<T>(url, body, config)).data
}

export const status = (config?: RequestConfig) => get<StatusData>('/status', config)
export const visit = (config?: RequestConfig) => post<StatusData>('/visit', {}, config)
export const session = {
  start: (input: SessionStartInput = {}, config?: RequestConfig) => post<SessionData>('/session/start', input, config),
  step: (token: string, config?: RequestConfig) => post<SessionData>('/session/step', { token }, config),
  complete: (token: string, config?: RequestConfig) => post<SessionCompleteData>('/session/complete', { token }, config),
}
export const leaderboard = {
  streak: (config?: RequestConfig) => get<StreakBoardData>('/leaderboard/streak', config),
}
export const claim = (config?: RequestConfig) => post<ClaimData>('/claim', {}, config)
export const practice = {
  get: (config?: RequestConfig) => get<PracticeData>('/practice', config),
  upload: (input: PracticeUploadInput, config?: RequestConfig) => post<PracticeUploadData>('/practice/records', input, config),
}
export const shop = {
  get: (config?: RequestConfig) => get<ShopData>('/shop', config),
  purchase: (input: PurchaseInput, config?: RequestConfig) => post<PurchaseData>('/shop/purchase', input, config),
  checkOrder: (orderNo: string, config?: RequestConfig) => post<OrderCheckData>(`/shop/orders/${encodeURIComponent(orderNo)}/check`, {}, config),
}
export const titles = {
  get: (config?: RequestConfig) => get<TitleData>('/titles', config),
  draw: (input: DrawInput, config?: RequestConfig) => post<DrawData>('/titles/draw', input, config),
  buyTicket: (input: { product_id: string; request_id: string }, config?: RequestConfig) => post<TicketPurchaseData>('/titles/tickets/purchase', input, config),
  equip: (input: { title_id: string | null }, config?: RequestConfig) => post<{ equipped_title_id: string | null }>('/titles/equip', input, config),
  smelt: (input: { mode: 'random' | 'target'; input_rarity: Rarity; target_title_id?: string; materials: Array<{ title_id: string; count: number }>; request_id: string }, config?: RequestConfig) => post<SmeltData>('/titles/smelt', input, config),
  craft: (input: { recipe_id: string; materials: Array<{ title_id: string; count: number }>; request_id: string }, config?: RequestConfig) => post<SmeltData>('/titles/craft', input, config),
}
export const donations = {
  get: (config?: RequestConfig) => get<DonationsData>('/donations', config),
  create: (amount: string, config?: RequestConfig) => post<DonationCreateData>('/donations/create', { amount }, config),
}
export const admin = {
  overview: (config?: RequestConfig) => get<AdminOverviewData>('/admin', config),
  users: (q: string, config?: RequestConfig) => get<AdminUsersData>('/admin/users', { ...config, params: { ...config?.params, q } }),
  open: (config?: RequestConfig) => post<EmptyData>('/admin/open', {}, config),
  saveSettings: (input: SaveSettingsInput, config?: RequestConfig) => post<EmptyData>('/admin/settings', input, config),
  review: (input: ReviewInput, config?: RequestConfig) => post<EmptyData>('/admin/review', input, config),
  addPoints: (input: AddPointsInput, config?: RequestConfig) => post<AddPointsData>('/admin/points/add', input, config),
  saveProduct: (input: SaveProductInput, config?: RequestConfig) => post<SaveProductData>('/admin/products', input, config),
  archiveProduct: (id: string, config?: RequestConfig) => post<EmptyData>(`/admin/products/${encodeURIComponent(id)}/archive`, {}, config),
  checkPurchase: (orderNo: string, config?: RequestConfig) => post<OrderCheckData>(`/admin/purchases/${encodeURIComponent(orderNo)}/check`, {}, config),
  checkAllPurchases: (config?: RequestConfig) => post<CheckAllData>('/admin/purchases/check', {}, config),
  reconcilePurchase: (orderNo: string, input: ReconcileInput, config?: RequestConfig) => post<ReconcileData>(`/admin/purchases/${encodeURIComponent(orderNo)}/reconcile`, input, config),
}

// 与 http.ts 一致的 API 前缀；子路径部署（如测试环境 /box）用 VITE_API_BASE=/box/api 覆盖。
export const API_BASE = (import.meta.env.VITE_API_BASE || '/api').replace(/\/$/, '')

const LOGIN_PATHS: Record<string, true> = { '/': true, '/practice': true, '/shop': true, '/titles': true, '/donate': true, '/admin': true }
export function loginUrl(next = '/'): string {
  const safeNext = LOGIN_PATHS[next] ? next : '/'
  return `${API_BASE}/auth/linuxdo/start?${new URLSearchParams({ next: safeNext })}`
}
export function logoutUrl(): string {
  return `${API_BASE}/auth/logout`
}

export { ApiError, http } from './http'
export type { RequestConfig } from './http'
