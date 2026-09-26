// Coop Call service worker: the coop rings the owner.
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()))

self.addEventListener('push', (event) => {
  let data = {}
  try { data = event.data.json() } catch { data = { title: 'Your coop is calling', body: event.data?.text() } }
  event.waitUntil(self.registration.showNotification(data.title || 'Your coop is calling', {
    body: data.body || '',
    tag: data.tag || 'coop-call',
    renotify: true,
    requireInteraction: true,
    vibrate: [600, 300, 600, 300, 600, 900, 600, 300, 600],
    icon: '/icon-192.png',
    badge: '/icon-192.png',
    data: { url: data.url || '/' },
    actions: [{ action: 'answer', title: 'Answer' }, { action: 'later', title: 'Later' }],
  }))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  if (event.action === 'later') return
  const url = new URL(event.notification.data?.url || '/', self.location.origin).href
  event.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    for (const c of all) {
      if ('focus' in c) { await c.navigate(url); return c.focus() }
    }
    return self.clients.openWindow(url)
  })())
})
