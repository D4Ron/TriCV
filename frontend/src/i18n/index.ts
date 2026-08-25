import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import fr from './locales/fr.json'

/**
 * Application francophone, sans bascule de langue.
 *
 * Les avis, les grilles et les rapports sont produits en français ; une
 * interface bilingue laissait croire qu'un avis pouvait être servi en anglais
 * alors que rien en aval ne l'était. i18next reste en place pour que les
 * libellés vivent hors des composants, pas pour traduire.
 */
void i18n.use(initReactI18next).init({
  resources: { fr: { translation: fr } },
  lng: 'fr',
  fallbackLng: 'fr',
  supportedLngs: ['fr'],
  interpolation: { escapeValue: false },
})

document.documentElement.lang = 'fr'

export default i18n
