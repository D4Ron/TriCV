import { useEffect, useState } from 'react'

/**
 * « Installer l'application » : TriCV dans le menu Démarrer, le Dock ou sur
 * le bureau, dans sa propre fenêtre, comme un logiciel.
 *
 * Le manifeste n'est posé qu'ici, dans le tableau de bord : la page publique
 * n'en a pas, et les candidats ne se voient pas proposer d'installer l'outil
 * du cabinet. Le bouton n'apparaît que si le navigateur sait installer
 * (Chrome, Edge) et que l'application ne l'est pas déjà.
 */

interface EvenementInstallation extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

function poserManifeste() {
  if (document.querySelector('link[rel="manifest"]')) return
  const lien = document.createElement('link')
  lien.rel = 'manifest'
  lien.href = '/manifest.json'
  document.head.appendChild(lien)
  const icone = document.createElement('link')
  icone.rel = 'apple-touch-icon'
  icone.href = '/icone-192.png'
  document.head.appendChild(icone)
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      /* sans service worker, l'application reste utilisable dans l'onglet */
    })
  }
}

const dejaInstallee = () =>
  window.matchMedia?.('(display-mode: standalone)').matches ||
  (navigator as Navigator & { standalone?: boolean }).standalone === true

export default function InstallerApplication() {
  const [invite, setInvite] = useState<EvenementInstallation | null>(null)

  useEffect(() => {
    poserManifeste()
    const surInvite = (event: Event) => {
      event.preventDefault()
      setInvite(event as EvenementInstallation)
    }
    const surInstallee = () => setInvite(null)
    window.addEventListener('beforeinstallprompt', surInvite)
    window.addEventListener('appinstalled', surInstallee)
    return () => {
      window.removeEventListener('beforeinstallprompt', surInvite)
      window.removeEventListener('appinstalled', surInstallee)
    }
  }, [])

  if (!invite || dejaInstallee()) return null
  return (
    <button
      type="button"
      className="btn-ghost px-2 py-1 text-xs"
      title="Ouvrir TriCV dans sa propre fenêtre, depuis le bureau ou le menu Démarrer."
      onClick={async () => {
        await invite.prompt()
        await invite.userChoice
        setInvite(null)
      }}
    >
      <svg aria-hidden viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M10 3v9m0 0-3.5-3.5M10 12l3.5-3.5M4 14v2h12v-2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      Installer l&apos;application
    </button>
  )
}
