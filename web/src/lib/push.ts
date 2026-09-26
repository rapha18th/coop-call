import { api, post } from './api'

function urlBase64ToUint8Array(base64: string) {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4)
  const raw = atob((base64 + padding).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)))
}

export const pushSupported = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window

export async function registerWorker() {
  if (!('serviceWorker' in navigator)) return null
  return navigator.serviceWorker.register('/sw.js')
}

// Lets the coop ring this phone: a push notification styled as an incoming call.
export async function letCoopCall(coopId: string) {
  if (!pushSupported()) throw new Error('This browser cannot receive calls from the coop. On iPhone, add Coop Call to the home screen first.')
  const permission = await Notification.requestPermission()
  if (permission !== 'granted') throw new Error('Notifications are off, so the coop cannot ring you.')
  const reg = (await navigator.serviceWorker.getRegistration()) ?? (await registerWorker())
  if (!reg) throw new Error('Service worker unavailable.')
  const { key } = await api<{ key: string }>('/api/push/key')
  if (!key) throw new Error('The server has no push key yet.')
  const sub =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(key) }))
  await post(`/api/coops/${coopId}/push/subscribe`, sub.toJSON())
}
