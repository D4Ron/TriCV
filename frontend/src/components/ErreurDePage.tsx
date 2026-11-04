import { Component, type ErrorInfo, type ReactNode } from 'react'

/**
 * Une page qui plante ne doit pas laisser un écran blanc.
 *
 * Sans ce filet, une seule erreur de rendu efface toute l'application : plus de
 * menu, plus de message, et rien pour savoir quoi faire. Ici le menu reste, et
 * le recruteur peut recharger ou repartir ailleurs.
 */
export default class ErreurDePage extends Component<
  { children: ReactNode },
  { erreur: Error | null }
> {
  state = { erreur: null as Error | null }

  static getDerivedStateFromError(erreur: Error) {
    return { erreur }
  }

  componentDidCatch(erreur: Error, info: ErrorInfo) {
    console.error('Page en erreur', erreur, info.componentStack)
  }

  render() {
    if (!this.state.erreur) return this.props.children
    return (
      <div className="card mx-auto mt-10 max-w-lg p-6 text-center">
        <p className="text-sm font-medium text-ink-900">Cette page n&apos;a pas pu s&apos;afficher.</p>
        <p className="mt-1 text-xs text-ink-500">
          Rien n&apos;est perdu : ce qui était enregistré l&apos;est toujours. Rechargez la page, et
          si l&apos;erreur revient, signalez ce message : {this.state.erreur.message}
        </p>
        <div className="mt-4 flex justify-center gap-2">
          <button type="button" className="btn-primary" onClick={() => window.location.reload()}>
            Recharger la page
          </button>
          <a className="btn-ghost" href="/mandats">
            Retour aux mandats
          </a>
        </div>
      </div>
    )
  }
}
