import type { PracticeRecord } from '../api'

const PREFERENCES_KEY = 'practice_preferences_v1'
const TRAINING_KEY = 'local_training_v1'

export interface PracticePreferences {
  mode: 'manual' | 'auto'
  repetitions: number
  intervalSeconds: number
  liftEnd: number
  relaxEnd: number
  phaseNames: [string, string, string]
}

export interface LocalPracticeSession {
  token: string
  mode: 'manual' | 'auto'
  repetitions: number
  round_id: string
  owner_id: string | null
  started_at: number
  interval_seconds: number
  min_seconds: number
  step: number
  completed: boolean
  completed_repetitions?: number
  abandoned?: boolean
  uploaded_user_id?: string
  upload_error?: string
  lift_end: number
  relax_end: number
  phase_names: [string, string, string]
  ready_at: number
  expires_at: number
  ended_at?: number
  eligible: false
  wait_seconds: number
  expires_in: number | null
}

interface PendingRecord extends PracticeRecord {
  owner_id: string | null
  error?: string
}

interface LocalRecord {
  day?: string
  count?: number
  session?: Omit<LocalPracticeSession, 'eligible' | 'wait_seconds' | 'expires_in'> | null
  pending?: PendingRecord[]
  [key: string]: unknown
}

const defaults: PracticePreferences = {
  mode: 'auto', repetitions: 10, intervalSeconds: 3, liftEnd: 45, relaxEnd: 85,
  phaseNames: ['提～', '放松', '休息'],
}

function readObject(key: string): Record<string, unknown> {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(key) || '{}')
    return value && typeof value === 'object' ? value as Record<string, unknown> : {}
  } catch { return {} }
}

function integer(value: unknown, minimum: number, maximum: number, fallback: number): number {
  const number = Number(value)
  return Number.isInteger(number) && number >= minimum && number <= maximum ? number : fallback
}

function clean(value: unknown, fallback: string): string {
  return Array.from(String(value ?? '').replace(/[\u0000-\u001f\u007f]/g, '').trim()).slice(0, 24).join('') || fallback
}

export function readPracticePreferences(): PracticePreferences {
  const saved = readObject(PREFERENCES_KEY)
  const liftEnd = integer(saved.liftEnd, 0, 100, defaults.liftEnd)
  const names = Array.isArray(saved.phaseNames) ? saved.phaseNames : []
  return {
    mode: saved.mode === 'manual' ? 'manual' : 'auto',
    repetitions: integer(saved.repetitions, 1, 20, defaults.repetitions),
    intervalSeconds: integer(saved.intervalSeconds, 2, 10, defaults.intervalSeconds),
    liftEnd,
    relaxEnd: integer(saved.relaxEnd, liftEnd, 100, Math.max(defaults.relaxEnd, liftEnd)),
    phaseNames: [clean(names[0], defaults.phaseNames[0]), clean(names[1], defaults.phaseNames[1]), clean(names[2], defaults.phaseNames[2])],
  }
}

export function savePracticePreferences(value: PracticePreferences): void {
  try { localStorage.setItem(PREFERENCES_KEY, JSON.stringify({ ...readObject(PREFERENCES_KEY), ...value })) } catch { /* active settings still work */ }
  window.dispatchEvent(new CustomEvent('practicepreferenceschange', { detail: value }))
}

function shanghaiDay(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
}

export function useLocalPractice() {
  let record = readObject(TRAINING_KEY) as LocalRecord

  const save = () => { try { localStorage.setItem(TRAINING_KEY, JSON.stringify(record)) } catch { /* local training remains usable */ } }
  const normalizeDay = () => {
    const day = shanghaiDay()
    if (record.day !== day) record = { day, count: 0, session: record.session, pending: record.pending || [] }
  }
  const view = (): LocalPracticeSession | null => {
    normalizeDay()
    const session = record.session
    if (!session || (!session.completed && session.expires_at <= Date.now())) return null
    return {
      ...session, eligible: false,
      wait_seconds: session.completed ? 0 : Math.max(0, (session.ready_at - Date.now()) / 1000),
      expires_in: session.completed ? null : Math.max(0, (session.expires_at - Date.now()) / 1000),
    }
  }
  const status = () => ({ day: String(record.day || shanghaiDay()), session: view() })
  const start = (selected: PracticePreferences, userId?: string) => {
    const active = view()
    if (active && !active.completed) return active
    const now = Date.now()
    record.session = {
      token: crypto.randomUUID(), mode: selected.mode, repetitions: selected.repetitions,
      round_id: crypto.randomUUID(), owner_id: userId || null, started_at: now,
      interval_seconds: selected.intervalSeconds, min_seconds: selected.intervalSeconds,
      step: 0, completed: false, lift_end: selected.liftEnd, relax_end: selected.relaxEnd,
      phase_names: [...selected.phaseNames], ready_at: now + selected.intervalSeconds * 1000, expires_at: now + 600_000,
    }
    save()
    return view()!
  }
  const current = (token: string) => {
    const active = view()
    if (!active || active.token !== token || !record.session) throw new Error('本轮训练已失效，请重新开始。')
    if (active.wait_seconds > 0) throw new Error('请等待本次倒计时结束。')
    return record.session
  }
  const step = (token: string) => {
    const session = current(token)
    if (session.completed || session.step >= session.repetitions - 1) throw new Error('本轮次数已全部开始，请等待完成。')
    session.step += 1
    session.token = crypto.randomUUID()
    session.ready_at = Date.now() + session.interval_seconds * 1000
    session.expires_at = Date.now() + 600_000
    save()
    return view()!
  }
  const complete = (token: string, abandon = false) => {
    const active = view()
    if (!active || active.token !== token || !record.session) throw new Error('本轮训练已失效，请重新开始。')
    const session = record.session
    if (!session.completed) {
      if (!abandon && (session.step !== session.repetitions - 1 || session.ready_at > Date.now())) throw new Error('请先完成本轮全部训练次数。')
      const completed = Math.min(session.repetitions, session.step + (Date.now() >= session.ready_at ? 1 : 0))
      session.abandoned = abandon
      session.completed_repetitions = completed
      session.completed = true
      session.step = session.repetitions
      session.ended_at = Date.now()
      if (completed > 0) {
        record.pending ||= []
        record.pending.push({ round_id: session.round_id, owner_id: session.owner_id, started_at: session.started_at, ended_at: session.ended_at, repetitions: completed, interval_seconds: session.interval_seconds, mode: session.mode })
      }
      record.count = (Number(record.count) || 0) + completed
      save()
    }
    return view()!
  }
  const reset = () => { record.session = null; save() }
  const pending = (userId: string, retryRejected = false) => (record.pending || []).filter(item => (!item.owner_id || item.owner_id === userId) && (retryRejected || !item.error))
  const bindOwner = (roundId: string, userId: string) => {
    const item = (record.pending || []).find(candidate => candidate.round_id === roundId)
    if (item) item.owner_id = userId
    if (record.session?.round_id === roundId) record.session.owner_id = userId
    save()
  }
  const uploaded = (roundId: string, userId: string) => {
    record.pending = (record.pending || []).filter(item => item.round_id !== roundId)
    if (record.session?.round_id === roundId) { record.session.uploaded_user_id = userId; delete record.session.upload_error }
    save()
  }
  const rejected = (roundId: string, message: string) => {
    const item = (record.pending || []).find(candidate => candidate.round_id === roundId)
    if (item) item.error = message
    if (record.session?.round_id === roundId) record.session.upload_error = message
    save()
  }
  return { status, view, start, step, complete, reset, pending, bindOwner, uploaded, rejected }
}
