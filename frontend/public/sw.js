// Le service worker minimal qui rend TriCV installable comme une application.
//
// Il ne met rien en cache : chaque ouverture charge la version déployée, et
// une mise à jour du serveur se voit aussitôt. Les données des candidats ne
// sont jamais stockées sur le poste par ce biais.
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))
self.addEventListener('fetch', () => {
  // Laisse passer toutes les requêtes vers le réseau, sans intervention.
})
