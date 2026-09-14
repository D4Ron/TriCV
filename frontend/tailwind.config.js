/** @type {import('tailwindcss').Config} */

// Identité visuelle de Kapi Consult, relevée sur kapiconsult.tg.
//
// Le site déclare ses couleurs en variables CSS : --blue-deep #1E2299,
// --blue-mid #2A30B5, --blue-light #6B7FE8, --blue-pale #E8ECFD, --gold
// #B8892A, --gold-light #D4A94A, --gold-pale #FBF5E8, --black #0D0E1A,
// --gray #6B7080, --light #F5F6FA. Les valeurs ci-dessous les reprennent
// telles quelles et comblent les échelons intermédiaires — un dégradé complet
// est nécessaire pour une interface d'application, là où un site vitrine se
// contente de trois tons.
//
// Les noms d'échelle (`ink`, `brand`) sont conservés pour que le changement
// d'identité ne demande pas de réécrire chaque classe : c'est la palette qui
// bouge, pas le balisage.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Neutres, ancrés sur --light, --gray et --black du site.
        ink: {
          50: '#f5f6fa',
          100: '#eceef6',
          200: '#dcdfec',
          300: '#bfc4d6',
          400: '#9298ae',
          500: '#6b7080',
          600: '#4e5361',
          700: '#383c48',
          800: '#22252f',
          900: '#0d0e1a',
        },
        // Bleu Kapi. Le 700 est le --blue-deep de la marque : c'est lui qui
        // porte les actions principales.
        brand: {
          50: '#f2f4fe',
          100: '#e8ecfd',
          200: '#d2d9fb',
          300: '#a8b4f2',
          400: '#6b7fe8',
          500: '#4a55d0',
          600: '#2a30b5',
          700: '#1e2299',
          800: '#191c7a',
          900: '#14165c',
        },
        // Or Kapi : réservé aux accents — le contour du logo, un filet, un
        // liseré. Jamais pour un état sémantique, que la couleur d'alerte ou
        // de réussite doit continuer de porter seule.
        or: {
          50: '#fbf5e8',
          100: '#f6ead0',
          200: '#edd5a2',
          300: '#e0bc6e',
          400: '#d4a94a',
          500: '#b8892a',
          600: '#966e20',
          700: '#74551a',
        },
        fit: {
          strong: '#1f7a4d',
          good: '#2a30b5',
          maybe: '#b8892a',
          no: '#a83232',
        },
      },
      fontFamily: {
        // DM Sans pour le texte, Playfair Display pour les titres : les deux
        // polices du site. Les substituts couvrent le cas où les fichiers ne
        // se chargent pas — l'application doit rester lisible hors ligne.
        sans: ['DM Sans', 'Segoe UI', 'system-ui', '-apple-system', 'sans-serif'],
        titre: ['Playfair Display', 'Georgia', 'Cambria', 'serif'],
      },
      boxShadow: {
        // Ombres teintées de bleu, comme sur le site, plutôt qu'un gris neutre.
        card: '0 1px 2px rgba(30, 34, 153, 0.06), 0 4px 16px rgba(30, 34, 153, 0.07)',
        'card-hover': '0 2px 4px rgba(30, 34, 153, 0.08), 0 10px 28px rgba(30, 34, 153, 0.12)',
        drawer: '-8px 0 40px rgba(30, 34, 153, 0.16)',
      },

      // --- mouvement --------------------------------------------------------
      // Un outil de travail : le mouvement sert à situer ce qui apparaît, pas à
      // se faire remarquer. D'où trois durées seulement, toutes courtes, et une
      // amplitude de quelques pixels. Au-delà, l'animation devient une attente.
      //
      // Tout est neutralisé sous `prefers-reduced-motion` (voir index.css).
      transitionDuration: {
        120: '120ms',
        180: '180ms',
      },
      transitionTimingFunction: {
        'out-soft': 'cubic-bezier(0.16, 1, 0.3, 1)',
      },
      keyframes: {
        'fade-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        rise: {
          from: { opacity: '0', transform: 'translateY(4px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'scale-in': {
          from: { opacity: '0', transform: 'translateY(8px) scale(0.98)' },
          to: { opacity: '1', transform: 'translateY(0) scale(1)' },
        },
        'slide-in': {
          from: { opacity: '0', transform: 'translateX(1.5rem)' },
          to: { opacity: '1', transform: 'translateX(0)' },
        },
      },
      animation: {
        'fade-in': 'fade-in 140ms ease-out both',
        rise: 'rise 180ms cubic-bezier(0.16, 1, 0.3, 1) both',
        'scale-in': 'scale-in 180ms cubic-bezier(0.16, 1, 0.3, 1) both',
        'slide-in': 'slide-in 200ms cubic-bezier(0.16, 1, 0.3, 1) both',
      },
    },
  },
  plugins: [],
}
