# Déroulé de démonstration — TriCV

Deux postes préparés, deux histoires différentes. Comptez vingt minutes.

    .\start-dev.ps1
    http://localhost:5173/login
    admin@tricv.example

---

## 1. Le classement — poste « Directeur des Ressources Humaines »

*Mandats › Recrutement de cadres hospitaliers › Directeur des Ressources Humaines*

Douze dossiers déjà dépouillés. **6 préqualifiés, 1 sous le seuil, 5 éliminés.**

À montrer, dans cet ordre :

1. **La fiche de poste** — c'est elle qui décide, et elle est lisible d'un coup d'œil.
2. **L'onglet Éliminés**, groupé par motif. Chaque ligne porte *attendu / constaté* : le tableau
   se lit à un candidat qui conteste, sans rien avoir à reconstituer.
3. **Un dossier** (clic sur une ligne) — la note se décompose critère par critère, chaque ligne
   dit son calcul. Rien n'est opaque.
4. **Poser un seuil.** L'écran montre la distribution réelle des notes : la barre se trace au vu
   des dossiers reçus, pas à l'avance. La déplacer reclasse aussitôt.
5. **Exporter (Excel)** — le document se choisit d'abord, parce qu'ils ne s'adressent pas aux
   mêmes personnes : la *grille de présélection* part au client, le *tableau d'élimination* se
   produit à un candidat qui conteste, le *détail des entretiens* sert à écrire le rapport. Le
   *dossier complet* les réunit, pour le travail interne.

---

## 2. Les exigences multiples — poste « Chef comptable »

*Mandats › Recrutement d'un Chef comptable › Chef comptable*

Cinq dossiers. L'avis demande **trois ans de comptabilité générale ET deux ans d'audit interne**,
et n'accepte que les candidats de 45 ans au plus.

C'est le poste qui montre ce qu'un tableur ne fait pas :

1. **KOUMAKO Edem — éliminé.** Quinze ans de comptabilité générale, note 20,5/30 : plus haut que
   le seul préqualifié. Un motif, un seul : *2 an(s) en audit interne — constaté : 0 mois*.
   Avec un seul jeu de domaines, son ancienneté couvrait les deux exigences et il passait.
2. **DOSSEH Akouvi — éliminée** sur l'exigence inverse : douze ans d'audit, un an de
   comptabilité générale.
3. **LAWSON-BODY Marc — écarté sur la condition d'âge.** Le meilleur dossier du lot (25,5/30),
   51 ans à la date de clôture. Ouvrez le motif : il recopie la justification écrite sur la
   fiche. C'est ce qu'on produit si la condition est contestée.
4. **Modifier la fiche** — les deux exigences, leurs poids, la condition d'âge et sa
   justification obligatoire. Enregistrer reclasse tout le poste.

### La lecture assistée, en direct

**ATTIOGBE Sena** est le dossier laissé vierge : onglet *À vérifier*, ouvrez-le, **Dépouiller le
dossier**. Une dizaine de secondes, et le parcours se remplit — deux diplômes, trois expériences,
les langues. Le dossier reste **À vérifier** : rien de ce qu'une machine propose ne peut
présélectionner ni éliminer quelqu'un avant qu'un humain ait confirmé.

Le bouton *Confirmer les données* est ce geste-là. Le dossier rejoint alors le classement.

> **Une seule réserve.** La clé Gemini est sur l'offre gratuite : sur `gemini-2.5-flash`,
> **250 appels par jour pour toute l'installation**. Ce dépouillement en coûte un, et chaque
> section de rapport rédigée aussi. S'ils sont épuisés, l'écran affiche « Extraction
> indisponible » — ce qui se raconte, mais mieux vaut ne pas le découvrir devant le client.
> Voir *Choosing a provider* dans le README : l'offre gratuite de Mistral est plus large et
> écrit un meilleur français.

---

## 3. Ce qu'on peut montrer ensuite, selon le temps

- **Écrire aux candidats** — la portée se choisit d'abord (tous, préqualifiés, écartés, à
  vérifier), puis chaque message s'affiche tel qu'il partira. *L'envoi n'est pas configuré :
  montrez l'aperçu, ne cliquez pas sur Envoyer.*
- **Rapports** (onglet du mandat) — le type se choisit avant tout le reste, et décide des
  sections. Un rapport de présélection ne porte pas de classement final. **Les deux grilles
  employées y sont reproduites**, ainsi que le tableau des préqualifiés dans les colonnes du
  document remis : nom, âge, diplôme, pays, note sur 100, rang, téléphone, e-mail.
  L'onglet **Aperçu du document** montre le rapport tel qu'il sortira — même en-tête, même ordre,
  corrections en cours comprises — sans passer par un export. Les grilles y sont de vrais
  tableaux, avec leurs rubriques, leurs sous-critères et leurs lignes de total, et le restent
  dans le Word, le PDF et l'OpenDocument.
- **Écrire à une seule personne** — ouvrez un dossier, bouton *Écrire* en tête du tiroir. Même
  fenêtre et même aperçu que l'envoi groupé, sur un destinataire. Sur KOUMAKO, le modèle
  « Candidature non retenue » est celui qui convient.
- **Vivier** — tous les candidats déjà vus, cherchables par métier.
- **Espace du promoteur** — ce que le client voit de son côté.
- **La page publique** : l'avis DL-2026-007 est publié, son lien de candidature fonctionne.
  L'avis du poste comptable est resté en brouillon, si vous voulez montrer la publication.

---

## Remettre la démonstration à zéro

    python demo/creer_dossiers.py             # dossiers du poste DRH
    python demo/creer_dossiers_comptables.py  # dossiers du poste comptable

Puis `.\start-dev.ps1 -Fresh` reconstruit la base (**et efface les comptes** : les recréer avec
`backend/comptes.py`).
