import { initializeApp } from 'firebase/app'
import { GoogleAuthProvider, getAuth, onAuthStateChanged, signInWithPopup, signOut, type User } from 'firebase/auth'

const env = import.meta.env
export const API = (env.VITE_API_URL as string).replace(/\/$/, '')
export const DEMO_COOP = (env.VITE_DEMO_COOP_ID as string) || 'demo'

const app = initializeApp({
  apiKey: env.VITE_FIREBASE_API_KEY,
  authDomain: env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: env.VITE_FIREBASE_PROJECT_ID,
  appId: env.VITE_FIREBASE_APP_ID,
})
export const auth = getAuth(app)

export const signIn = () => signInWithPopup(auth, new GoogleAuthProvider())
export const signOutNow = () => signOut(auth)
export const watchUser = (fn: (u: User | null) => void) => onAuthStateChanged(auth, fn)

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const user = auth.currentUser
  if (user) headers.set('Authorization', `Bearer ${await user.getIdToken()}`)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const res = await fetch(API + path, { ...init, headers })
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {}
    throw new ApiError(res.status, detail)
  }
  return res.json()
}

export const post = <T = any>(path: string, body: unknown = {}) =>
  api<T>(path, { method: 'POST', body: JSON.stringify(body) })

// ------------------------------------------------------------------ shapes

export type Now = {
  local_time: string
  camera: string
  frame_url?: string | null
  frame_time?: string
  sensors?: string
  note?: string
}

export type Alarm = {
  id: string
  kind: string
  message: string
  status: string
  time: string
  frame_url?: string | null
}

export type Hour = {
  hour: string
  nv: number
  birds: number | null
  huddled: number
  drinker_low: number
  agitated: number
  sound: number | null
  notes: number
  simulated: boolean
}

export type Coop = { id: string; name: string; birds_expected?: number; owner_name?: string }

export type State = {
  coop: Coop; role: string; now: Now; alarms: Alarm[]; strip: Hour[]; owner: boolean
  device: Device; flock: Flock | null
}

export type Device = {
  level: 'ok' | 'warn' | 'down'; summary: string
  checks: { name: string; level: 'ok' | 'warn' | 'down'; text: string }[]
  battery: number | null; charging: boolean | null; network: string | null; frames: number
  resolution: string | null; version: string | null
}

export type Task = { when: string; kind: string; text: string }

export type PlanRow = {
  day: number; weight_kg: number; revenue: number; feed_to_buy: number; margin: number
  margin_per_bird: number | null; extra_day_value: number
}

export type Flock = {
  batch: string; placed: string; breed: string; age_days: number; week: number; phase: string
  phase_ends_in: number | null; next_phase: string | null
  birds: { placed: number; alive: number; deaths: number; sold: number; mortality_pct: number }
  growth: {
    target_kg: number; estimate_kg: number; factor: number; factor_source: string
    measured: { kg: number; day: number; target_kg: number } | null
    curve: { day: number; target_kg: number }[]; weighs: { day: number; kg: number }[]
  }
  feed: {
    today_kg: number; today_bags: number; per_bird_g: number; bought_kg: number; eaten_kg: number
    on_hand_kg: number | null; days_left: number | null; last_two_weeks_share: number; last_two_weeks_usd: number
    sell_day: number
    weekly: { week: number; kg_per_bird: number; kg: number; usd: number; bags: number; now: boolean }[]
  }
  water_l_today: number
  money: {
    spent: number; income: number; cost_per_bird_so_far: number | null; plan: PlanRow[]
    best_day: number | null; chosen: PlanRow | null
    prices: { chick: number; feed_per_kg: number; sell_per_kg: number; other_per_bird: number }
  }
  tasks: Task[]
}

export type LedgerRow = {
  id: string; ts: string; kind: string; quantity: number | null; unit: string
  amount_usd: number | null; note: string
}

export const usd = (v?: number | null, places = 0) =>
  v == null ? '–' : `${v < 0 ? '−' : ''}$${Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: places, maximumFractionDigits: places })}`


export type Me = { uid: string; email: string; name: string; admin: boolean }

export type Card = Coop & {
  role: string
  open_alarms: number
  latest: {
    time: string; ago: string; birds: number; spread: string; drinker: string; feeder: string
    frame_url?: string | null; simulated: boolean
  } | null
}

export type Cell = { state: 'none' | 'fine' | 'cold' | 'hot'; water?: boolean; feed?: boolean; note?: boolean; birds?: number }

export type Day = {
  day: string; readings: number; coverage_h: number; water_ok?: number; dry_minutes?: number
  feed_ok?: number; empty_feeder_minutes?: number; cold?: number; hot?: number; comfort?: number
  calm_nights?: number; birds_mean?: number; birds_max?: number; care?: number; simulated?: boolean
}

export type Week = {
  days: Day[]
  grid: { day: string; hours: Cell[] }[]
  today: Day
  insights: { kind: string; level: 'act' | 'watch' | 'ok'; text: string }[]
  flock: { expected?: number; age_days: number; week_of_life: number }
  alarms: { count: number; by_kind: Record<string, number>; unanswered: number; median_answer_min: number | null }
  calls: { count: number; minutes: number }
  care_weights: Record<string, number>
}

export type CallRecord = {
  id: string; when: string; name: string; role: string; alarm_id?: string | null
  duration_s?: number; status: string; tools: string[]; evidence: number
  transcript: { who: string; text: string }[]
}

export type Member = { uid: string; role: string; name?: string; email?: string }
export type Team = { members: Member[]; invites: { email: string; role: string }[]; can_manage: boolean }

export type AdminOverview = {
  coops: { id: string; name: string; owner: string; members: number; invites: number; birds?: number; last_seen: string; open_alarms: number; calls_7d: number }[]
  users: { uid: string; email: string; name: string; coops: number; blocked: boolean; admin: boolean; first_seen: string; last_seen: string }[]
  usage: { day: string; frames: number; calls: number; call_minutes: number; cost_usd: number }[]
}

export const del = <T = any>(path: string) => api<T>(path, { method: 'DELETE' })
export const put = <T = any>(path: string, body: unknown) =>
  api<T>(path, { method: 'PUT', body: JSON.stringify(body) })
export const patch = <T = any>(path: string, body: unknown) =>
  api<T>(path, { method: 'PATCH', body: JSON.stringify(body) })

export const dayLabel = (d: string) =>
  new Date(`${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}T12:00:00`).toLocaleDateString('en-GB', { weekday: 'short' })
