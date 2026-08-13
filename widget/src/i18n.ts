export type Lang = 'fr' | 'en'

export interface Strings {
  apply: string
  fullName: string
  email: string
  phone: string
  cv: string
  cvHint: string
  chooseFile: string
  noFile: string
  submit: string
  submitting: string
  required: string
  invalidEmail: string
  cvRequired: string
  successTitle: string
  successBody: string
  closedTitle: string
  closedBody: string
  errorTitle: string
  errorBody: string
  loading: string
  privacy: string
}

export const STRINGS: Record<Lang, Strings> = {
  fr: {
    apply: 'Postuler',
    fullName: 'Nom complet',
    email: 'Adresse email',
    phone: 'Téléphone (facultatif)',
    cv: 'Votre CV',
    cvHint: 'PDF ou Word (.docx), 10 Mo maximum.',
    chooseFile: 'Choisir un fichier',
    noFile: 'Aucun fichier sélectionné',
    submit: 'Envoyer ma candidature',
    submitting: 'Envoi…',
    required: 'Ce champ est obligatoire.',
    invalidEmail: 'Adresse email invalide.',
    cvRequired: 'Veuillez joindre votre CV.',
    successTitle: 'Candidature reçue',
    successBody: 'Merci. Votre dossier a bien été transmis à l’équipe de recrutement.',
    closedTitle: 'Candidatures clôturées',
    closedBody: 'Ce poste n’accepte plus de candidatures.',
    errorTitle: 'Formulaire indisponible',
    errorBody: 'Le formulaire de candidature n’a pas pu être chargé.',
    loading: 'Chargement…',
    privacy:
      'Votre CV est analysé pour évaluer votre adéquation au poste. Vos données d’identité ne sont pas utilisées dans la notation.',
  },
  en: {
    apply: 'Apply',
    fullName: 'Full name',
    email: 'Email address',
    phone: 'Phone (optional)',
    cv: 'Your CV',
    cvHint: 'PDF or Word (.docx), 10 MB max.',
    chooseFile: 'Choose a file',
    noFile: 'No file selected',
    submit: 'Send my application',
    submitting: 'Sending…',
    required: 'This field is required.',
    invalidEmail: 'Invalid email address.',
    cvRequired: 'Please attach your CV.',
    successTitle: 'Application received',
    successBody: 'Thank you. Your application has been passed to the recruitment team.',
    closedTitle: 'Applications closed',
    closedBody: 'This role is no longer accepting applications.',
    errorTitle: 'Form unavailable',
    errorBody: 'The application form could not be loaded.',
    loading: 'Loading…',
    privacy:
      'Your CV is analysed to assess your fit for the role. Your identity details are not used in the scoring.',
  },
}

export function stringsFor(lang: string | null | undefined): Strings {
  return lang === 'en' ? STRINGS.en : STRINGS.fr
}
