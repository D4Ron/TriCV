import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { avisPublicApi } from '@/lib/api'
import { Marque } from '@/components/Marque'
import PiedPublic from '@/components/PiedPublic'

/**
 * Ce qu'un candidat a besoin de savoir avant d'écrire à quelqu'un.
 *
 * Le dépôt échoue de quelques façons connues — un scan trop lourd, un fichier
 * qui n'est ni PDF ni Word, une pièce qu'on n'a pas encore, un lien clôturé —
 * et jusqu'ici rien ne le disait. Un candidat bloqué refermait l'onglet ; le
 * cabinet ne voyait qu'un dossier manquant, sans savoir qu'il y avait eu une
 * tentative.
 *
 * La page est publique et hors authentification : elle sert précisément à
 * quelqu'un qui n'a pas de compte et n'en aura jamais. Elle ne promet rien
 * qu'on ne tienne — pas de délai de réponse, pas de suivi de dossier — et elle
 * ne donne d'adresse que si le cabinet en a réglé une.
 */

interface Question {
  question: string
  reponse: React.ReactNode
}

const QUESTIONS: Question[] = [
  {
    question: 'Mon fichier est refusé : « format non accepté ».',
    reponse: (
      <>
        Seuls le PDF et le Word (.doc, .docx) sont acceptés. Une photo prise au téléphone
        (.jpg, .png) ou une capture d&apos;écran est refusée même si le document est lisible :
        rassemblez vos pages dans un seul PDF avant de les déposer. La plupart des applications
        de numérisation sur téléphone savent produire un PDF.
      </>
    ),
  },
  {
    question: 'Mon fichier est trop volumineux.',
    reponse: (
      <>
        Un scan en haute définition dépasse vite la limite. Numérisez en noir et blanc plutôt
        qu&apos;en couleur, et en 200 ou 300 ppp plutôt qu&apos;au maximum : le document reste
        parfaitement lisible et pèse plusieurs fois moins. La limite exacte est rappelée sur la
        page du poste, au-dessus des champs de dépôt.
      </>
    ),
  },
  {
    question: 'Je n’ai pas encore l’une des pièces exigées.',
    reponse: (
      <>
        Les pièces marquées comme exigées conditionnent l&apos;examen du dossier : sans elles,
        la candidature est écartée sans être notée. Si une pièce vous manque, déposez votre
        dossier avant la clôture avec ce que vous avez et écrivez à l&apos;adresse ci-dessous en
        expliquant ce qui manque et quand vous l&apos;aurez — c&apos;est au cabinet, pas au
        formulaire, d&apos;en décider.
      </>
    ),
  },
  {
    question: 'On me demande la CNI ou le passeport : lequel ?',
    reponse: (
      <>
        L&apos;un des deux, à votre choix. Quand l&apos;avis présente deux pièces comme une
        alternative, le formulaire ne vous en demande qu&apos;une : choisissez celle que vous
        avez.
      </>
    ),
  },
  {
    question: 'Pourquoi remplir mon parcours alors que je joins mon CV ?',
    reponse: (
      <>
        Tant que votre CV n&apos;a pas été lu et relu par le cabinet, ce qu&apos;il contient
        n&apos;est pas encore une donnée du dossier. Les diplômes et les expériences que vous
        saisissez servent à examiner votre candidature dès sa réception. C&apos;est une
        redondance voulue, et elle joue en votre faveur.
      </>
    ),
  },
  {
    question: 'Le lien de candidature ne fonctionne plus.',
    reponse: (
      <>
        Un avis se ferme à sa date de clôture, et le lien cesse alors d&apos;accepter les
        dépôts. Consultez{' '}
        <Link className="underline" to="/careers">
          les postes ouverts
        </Link>{' '}
        : l&apos;avis y figure tant qu&apos;il accepte des candidatures.
      </>
    ),
  },
  {
    question: 'Puis-je corriger ou compléter un dossier déjà envoyé ?',
    reponse: (
      <>
        Le formulaire ne permet pas de revenir sur un dépôt. Écrivez à l&apos;adresse ci-dessous
        en rappelant le poste et la référence de l&apos;avis, et joignez la pièce corrigée.
      </>
    ),
  },
  {
    question: 'Comment saurai-je si ma candidature est retenue ?',
    reponse: (
      <>
        Vous êtes contacté par courriel si votre profil est retenu à l&apos;issue de la
        présélection. Aucune note, aucun classement et aucune information sur les autres
        candidats ne sont communiqués — ni sur ce site, ni par courriel.
      </>
    ),
  },
  {
    question: 'Que deviennent les documents que je dépose ?',
    reponse: (
      <>
        Ils servent uniquement à l&apos;examen de votre candidature par le cabinet et son
        client. Aucun compte n&apos;est créé, et rien n&apos;est publié.
      </>
    ),
  },
]

export default function AidePage() {
  const [ouverte, setOuverte] = useState<number | null>(0)
  const contact = useQuery({
    queryKey: ['aide-publique'],
    queryFn: avisPublicApi.aide,
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
  const adresse = contact.data?.contact

  return (
    <div className="min-h-screen bg-ink-50">
      <div className="h-1 bg-gradient-to-r from-or-500 via-or-400 to-or-500" />
      <header className="border-b border-ink-200 bg-white">
        <div className="mx-auto flex h-16 max-w-3xl items-center px-4">
          <Marque sousTitre="Recrutement" />
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-10">
        <h1 className="font-titre text-2xl font-bold text-ink-900">
          Déposer une candidature : questions fréquentes
        </h1>
        <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-600">
          Les difficultés qui reviennent le plus souvent au moment du dépôt, et ce qu&apos;il
          faut faire dans chaque cas.
        </p>

        <div className="mt-8 divide-y divide-ink-200 overflow-hidden rounded-lg border border-ink-200 bg-white">
          {QUESTIONS.map((q, index) => (
            <div key={q.question}>
              <button
                type="button"
                className="flex w-full items-start gap-3 px-4 py-3 text-left transition hover:bg-ink-50"
                aria-expanded={ouverte === index}
                onClick={() => setOuverte(ouverte === index ? null : index)}
              >
                <span
                  aria-hidden="true"
                  className={`mt-0.5 shrink-0 text-ink-400 transition-transform duration-180 ${
                    ouverte === index ? 'rotate-90' : ''
                  }`}
                >
                  ›
                </span>
                <span className="text-sm font-medium text-ink-900">{q.question}</span>
              </button>
              {ouverte === index && (
                <div className="px-4 pb-4 pl-10 text-sm leading-relaxed text-ink-600">
                  {q.reponse}
                </div>
              )}
            </div>
          ))}
        </div>

        <div className="mt-8 rounded-lg border border-ink-200 bg-white px-4 py-4">
          <p className="text-sm font-semibold text-ink-900">Votre question n&apos;y est pas ?</p>
          {adresse ? (
            <p className="mt-1 text-sm leading-relaxed text-ink-600">
              Écrivez à{' '}
              <a className="font-medium underline" href={`mailto:${adresse}`}>
                {adresse}
              </a>{' '}
              en indiquant le poste concerné et la référence de l&apos;avis — elle figure en tête
              de la page de candidature. Sans ces deux repères, un message ne se rattache à aucun
              dossier.
            </p>
          ) : (
            <p className="mt-1 text-sm leading-relaxed text-ink-600">
              Aucune adresse de contact n&apos;est publiée pour le moment. Consultez{' '}
              <Link className="underline" to="/careers">
                les postes ouverts
              </Link>{' '}
              : les coordonnées du recrutement figurent sur la page de chaque avis.
            </p>
          )}
        </div>

        <div className="mt-10 border-t border-ink-200 pt-6">
          <Link to="/careers" className="btn-ghost">
            Voir les postes ouverts
          </Link>
          <div className="mt-6">
            <PiedPublic aide={false} />
          </div>
        </div>
      </main>
    </div>
  )
}
