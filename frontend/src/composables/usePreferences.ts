const STORAGE_KEY = 'practice_preferences_v1'
const REMINDER_KEY = 'practice_reminder_last_v1'

export interface GlobalPreferences {
  hideTigang: boolean
  exerciseName: string
  notifyHour: boolean
  notifyHalfHour: boolean
}

const DEFAULTS: Readonly<GlobalPreferences> = Object.freeze({
  hideTigang: false,
  exerciseName: '',
  notifyHour: false,
  notifyHalfHour: false,
})

function cleanName(value: unknown): string {
  return Array.from(String(value ?? '').replace(/[\u0000-\u001f\u007f]/g, '').trim()).slice(0, 24).join('')
}

function safeRead(): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    return typeof parsed === 'object' && parsed !== null ? parsed as Record<string, unknown> : {}
  } catch {
    return {}
  }
}

function normalize(candidate: Record<string, unknown>): GlobalPreferences {
  return {
    hideTigang: candidate.hideTigang === true || DEFAULTS.hideTigang,
    exerciseName: cleanName(candidate.exerciseName) || DEFAULTS.exerciseName,
    notifyHour: candidate.notifyHour === true || DEFAULTS.notifyHour,
    notifyHalfHour: candidate.notifyHalfHour === true || DEFAULTS.notifyHalfHour,
  }
}

const saved = safeRead()
const initialParams = new URLSearchParams(location.search)
if (initialParams.has('hide_tigang')) saved.hideTigang = initialParams.get('hide_tigang') === '1'
if (initialParams.has('exercise_name')) saved.exerciseName = initialParams.get('exercise_name')

export const preferences = reactive<GlobalPreferences>(normalize(saved))
let reminderTimer: number | undefined

function persist(): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...safeRead(), ...toRaw(preferences) }))
  } catch {
    // Preferences remain active in this tab when storage is unavailable.
  }
}

function replacement(): string {
  return preferences.exerciseName || (preferences.hideTigang ? '训练' : '提肛')
}

export function ft(text: string): string {
  return String(text).replaceAll('提肛', replacement())
}

export function preferenceQuery(): Record<string, string> {
  return {
    ...(preferences.hideTigang ? { hide_tigang: '1' } : {}),
    ...(preferences.exerciseName ? { exercise_name: preferences.exerciseName } : {}),
  }
}

function updateAddress(): void {
  const url = new URL(location.href)
  if (preferences.hideTigang) url.searchParams.set('hide_tigang', '1')
  else url.searchParams.delete('hide_tigang')
  if (preferences.exerciseName) url.searchParams.set('exercise_name', preferences.exerciseName)
  else url.searchParams.delete('exercise_name')
  history.replaceState(history.state, '', `${url.pathname}${url.search}${url.hash}`)
}

export function applyDocumentPreferences(title: string, description = ''): void {
  document.documentElement.dataset.preferencesTitle = title
  document.title = ft(title)
  const meta = document.querySelector<HTMLMetaElement>('meta[name="description"]')
  if (meta) {
    meta.dataset.preferencesDescription = description
    meta.content = ft(description)
  }
}

function refreshDocumentPreferences(): void {
  const title = document.documentElement.dataset.preferencesTitle
  const meta = document.querySelector<HTMLMetaElement>('meta[name="description"]')
  if (title) document.title = ft(title)
  if (meta?.dataset.preferencesDescription !== undefined) meta.content = ft(meta.dataset.preferencesDescription)
}

function emitChange(): void {
  window.dispatchEvent(new CustomEvent('practicepreferenceschange', { detail: { ...toRaw(preferences) } }))
}

function nextReminder(now: Date): Date | null {
  let nearest: Date | null = null
  for (let hourOffset = 0; hourOffset <= 25; hourOffset += 1) {
    const base = new Date(now)
    base.setMinutes(0, 0, 0)
    base.setHours(base.getHours() + hourOffset)
    const candidates: Date[] = []
    if (preferences.notifyHour) candidates.push(new Date(base))
    if (preferences.notifyHalfHour) {
      const half = new Date(base)
      half.setMinutes(30, 0, 0)
      candidates.push(half)
    }
    for (const candidate of candidates) {
      if (candidate.getTime() > now.getTime() && (!nearest || candidate < nearest)) nearest = candidate
    }
    if (nearest) break
  }
  return nearest
}

function reminderWasSent(timestamp: number): boolean {
  try {
    if (localStorage.getItem(REMINDER_KEY) === String(timestamp)) return true
    localStorage.setItem(REMINDER_KEY, String(timestamp))
  } catch {
    const state = reminderWasSent as typeof reminderWasSent & { last?: number }
    if (state.last === timestamp) return true
    state.last = timestamp
  }
  return false
}

function scheduleReminder(): void {
  if (reminderTimer !== undefined) window.clearTimeout(reminderTimer)
  reminderTimer = undefined
  if (!(preferences.notifyHour || preferences.notifyHalfHour)) return
  const target = nextReminder(new Date())
  if (!target) return
  reminderTimer = window.setTimeout(() => {
    const lateness = Date.now() - target.getTime()
    if (lateness >= 0 && lateness <= 30_000 && 'Notification' in window
      && Notification.permission === 'granted' && !reminderWasSent(target.getTime())) {
      const title = preferences.hideTigang && !preferences.exerciseName ? '活动提醒' : `${replacement()}提醒`
      new Notification(title, { body: '到时间了。页面打开期间才会显示这条提醒，请按自己的节奏进行。' })
    }
    scheduleReminder()
  }, Math.max(0, target.getTime() - Date.now()))
}

export function updatePreferences(next: Partial<GlobalPreferences>, updateUrl = true): void {
  Object.assign(preferences, normalize({ ...toRaw(preferences), ...next }))
  persist()
  if (updateUrl) updateAddress()
  refreshDocumentPreferences()
  scheduleReminder()
  emitChange()
}

export function notificationMessage(): string {
  if (!('Notification' in window)) return '当前浏览器不支持系统通知。你仍可保存提醒时段。'
  if (Notification.permission === 'denied') return '系统通知已被拒绝，请在浏览器的网站设置中重新允许。'
  if (Notification.permission === 'granted') return '通知权限已允许。页面打开期间会按所选时段提醒。'
  if (preferences.notifyHour || preferences.notifyHalfHour) return '提醒时段已保存，请点击按钮允许通知。'
  return '选择提醒时段后，点击按钮允许通知。'
}

export async function requestNotificationPermission(): Promise<void> {
  if ('Notification' in window && Notification.permission === 'default') await Notification.requestPermission()
  scheduleReminder()
}

export function usePreferences() {
  return {
    preferences,
    ft,
    updatePreferences,
    preferenceQuery,
    notificationMessage,
    requestNotificationPermission,
  }
}

window.addEventListener('storage', (event) => {
  if (event.key !== STORAGE_KEY) return
  Object.assign(preferences, normalize(safeRead()))
  refreshDocumentPreferences()
  scheduleReminder()
  emitChange()
})

persist()
scheduleReminder()
queueMicrotask(() => window.dispatchEvent(new CustomEvent('practicepreferencesready', { detail: { ...toRaw(preferences) } })))
