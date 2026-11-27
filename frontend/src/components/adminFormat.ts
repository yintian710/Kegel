import type { Purchase } from '../api'

export type AdminTab = 'dashboard' | 'rules' | 'shop' | 'users' | 'logs'

export function fmtTime(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const date = typeof value === 'number' ? new Date(value < 1e12 ? value * 1000 : value) : new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export const purchaseStatus: Record<Purchase['status'], { label: string; tone: 'ok' | 'warn' | 'err' | 'info' }> = {
  success: { label: '发货成功', tone: 'ok' },
  simulated: { label: '模拟发货', tone: 'info' },
  pending: { label: '处理中', tone: 'warn' },
  failed: { label: '失败（已退分）', tone: 'err' },
  uncertain: { label: '待人工核对', tone: 'warn' },
}

export const rewardStatus: Record<string, { label: string; tone: 'ok' | 'warn' | 'plain' }> = {
  unclaimed: { label: '未领取', tone: 'warn' },
  credited: { label: '已入钱包', tone: 'ok' },
  none: { label: '无奖励', tone: 'plain' },
}

// 距结束还剩多久，如「2 天 3 小时」「45 分钟」；已结束返回「已结束」
export function remaining(endSeconds: number | null | undefined, nowMs = Date.now()): string {
  if (!endSeconds) return ''
  const left = Math.floor(endSeconds - nowMs / 1000)
  if (left <= 0) return '已结束'
  const days = Math.floor(left / 86400)
  const hours = Math.floor((left % 86400) / 3600)
  const minutes = Math.floor((left % 3600) / 60)
  if (days) return `${days} 天 ${hours} 小时`
  if (hours) return `${hours} 小时 ${minutes} 分钟`
  return `${Math.max(minutes, 1)} 分钟`
}

// bp → 「8 折」「9.5 折」
export function zheText(bp: number | null | undefined): string {
  return bp ? `${(bp / 1000).toFixed(1).replace(/\.0$/, '')} 折` : ''
}

export function initial(name: string | undefined | null): string {
  return (name || '?').trim().slice(0, 1)
}
