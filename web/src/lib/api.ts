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

export type State = { coop: Coop; now: Now; alarms: Alarm[]; strip: Hour[]; owner: boolean }
