from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.llm.base import FichePayload

ANALYSIS_SYSTEM_EN = """You are an expert recruitment analyst. You evaluate a candidate's CV against a specific
recruitment brief and return a structured, evidence-based assessment.

Rules:
- Judge ONLY on evidence present in the CV. Never invent experience, dates or qualifications.
- If the CV does not address a criterion, score it low and say the evidence is absent.
- The CV has been redacted: identity details appear as placeholders such as [CANDIDATE_NAME],
  [EMAIL], [PHONE]. Never speculate about who the candidate is, and never treat a placeholder or a
  missing identity detail as a gap or a negative signal.
- Every justification must cite something concrete from the CV.
- Respond with a single valid JSON object and nothing else. No markdown, no code fences, no preamble."""

ANALYSIS_SYSTEM_FR = """Vous êtes un analyste expert en recrutement. Vous évaluez le CV d'un candidat au regard d'une
fiche de recrutement précise et rendez une évaluation structurée, fondée sur des preuves.

Règles :
- Jugez UNIQUEMENT sur les éléments présents dans le CV. N'inventez jamais d'expérience, de dates ni
  de qualifications.
- Si le CV ne traite pas un critère, attribuez une note basse et indiquez que la preuve est absente.
- Le CV a été anonymisé : les données d'identité apparaissent sous forme de marqueurs tels que
  [CANDIDATE_NAME], [EMAIL], [PHONE]. Ne spéculez jamais sur l'identité du candidat et ne considérez
  jamais un marqueur ou une donnée d'identité manquante comme une lacune ou un signal négatif.
- Chaque justification doit citer un élément concret du CV.
- Répondez par un unique objet JSON valide et rien d'autre. Pas de markdown, pas de balises de code,
  pas de préambule."""

SCHEMA_BLOCK = """{
  "candidate": {
    "full_name": string|null,
    "email": string|null,
    "phone": string|null,
    "years_experience": number|null,
    "education_level": string|null,
    "skills": [string]
  },
  "criterion_scores": [
    {"criterion_id": string, "score": number, "justification": string}
  ],
  "summary": string,
  "strengths": [string],
  "gaps": [string]
}"""


def analysis_system_prompt(language: str = "fr") -> str:
    return ANALYSIS_SYSTEM_FR if language == "fr" else ANALYSIS_SYSTEM_EN


def analysis_user_prompt(fiche: "FichePayload", cv_text: str | None = None) -> str:
    fr = fiche.language == "fr"
    lines: list[str] = [f"POSTE : {fiche.position}" if fr else f"POSITION: {fiche.position}"]
    if fiche.description:
        lines.append(
            f"CONTEXTE : {fiche.description}" if fr else f"CONTEXT: {fiche.description}"
        )
    lines += ["", "CRITÈRES D'ÉVALUATION :" if fr else "EVALUATION CRITERIA:"]

    for criterion in fiche.criteria:
        looking_for = "ce que nous recherchons" if fr else "what we are looking for"
        lines += [
            f"- id: {criterion.id}",
            f"  {'nom' if fr else 'name'}: {criterion.name}",
            f"  {looking_for}: {criterion.description or '—'}",
            f"  {'poids' if fr else 'weight'}: {criterion.weight}/10",
            f"  must_have: {'true' if criterion.is_must_have else 'false'}",
        ]

    lines += [
        "",
        (
            "Notez chaque critère de 0 à 100. Utilisez exactement les identifiants criterion_id "
            "ci-dessus. Renvoyez ensuite un JSON conforme exactement à ce schéma :"
            if fr
            else "Score each criterion 0-100. Use exactly the criterion_id values listed above. "
            "Then return JSON matching exactly this schema:"
        ),
        "",
        SCHEMA_BLOCK,
    ]

    lines += [
        "",
        "--- CV ---",
        cv_text
        or (
            "Le CV est joint à ce message sous forme de document."
            if fr
            else "The CV is attached to this message as a document."
        ),
    ]

    return "\n".join(lines)


def repair_prompt(original_user_prompt: str, bad_response: str, error: str) -> str:
    return (
        f"{original_user_prompt}\n\n"
        f"--- CORRECTION REQUIRED ---\n"
        f"Your previous response could not be parsed. It was:\n{bad_response[:2000]}\n\n"
        f"The error was:\n{error}\n\n"
        f"Return ONLY a single valid JSON object matching the schema above. "
        f"No markdown, no code fences, no commentary."
    )


FICHE_SYSTEM_EN = """You turn a free-text job description into a set of draft evaluation criteria for CV screening.
Produce between 4 and 10 criteria. Each must be independently assessable from a CV.
Mark a criterion must_have only when the description states it as a hard requirement.
Weight reflects importance, 1 (minor) to 10 (central).
Respond with a single valid JSON object and nothing else."""

FICHE_SYSTEM_FR = """Vous transformez une description de poste en texte libre en une liste de critères d'évaluation
pour la présélection de CV.
Produisez entre 4 et 10 critères. Chacun doit être évaluable indépendamment à partir d'un CV.
Ne marquez must_have que lorsque la description présente l'élément comme une exigence ferme.
Le poids reflète l'importance, de 1 (secondaire) à 10 (central).
Répondez par un unique objet JSON valide et rien d'autre."""


def fiche_system_prompt(language: str = "fr") -> str:
    return FICHE_SYSTEM_FR if language == "fr" else FICHE_SYSTEM_EN


def fiche_user_prompt(raw_text: str, language: str = "fr") -> str:
    fr = language == "fr"
    header = (
        "DESCRIPTION DE POSTE :" if fr else "JOB DESCRIPTION:"
    )
    instruction = (
        "Renvoyez un JSON conforme exactement à ce schéma, rédigé en français :"
        if fr
        else "Return JSON matching exactly this schema, written in English:"
    )
    schema = """{
  "criteria": [
    {"name": string, "description": string, "weight": number, "is_must_have": boolean}
  ]
}"""
    return f"{header}\n{raw_text}\n\n{instruction}\n\n{schema}"


# --- dépouillement d'un dossier ---------------------------------------------

_EXTRACTION_SYSTEME = """Tu assistes un cabinet de recrutement au Togo qui dépouille des dossiers de candidature.

Le texte qui suit a déjà été expurgé : le nom, l'adresse, l'email, le téléphone, la date de naissance, le sexe et la nationalité ont été remplacés par des marqueurs de la forme [NOM], [EMAIL], [DATE_NAISSANCE]. C'est voulu. Ne cherche pas à deviner ces informations, ne les reconstitue pas, et ne les fais figurer nulle part dans ta réponse.

Ton seul travail est de relever le parcours : diplômes, expériences professionnelles, langues, certifications.

Règles :
- Ne rapporte que ce qui est écrit. Aucune déduction, aucun comblement de trou.
- Les niveaux de diplôme suivent l'échelle BAC+N, qui va de 0 à 8 :
  Baccalauréat = 0 ; BAC+1 = 1 ; BTS, DUT, DEUG ou DEUST = 2 ; Licence, Licence professionnelle ou Bachelor = 3 ; Maîtrise ou Master 1 = 4 ; Master, Master 2, Ingénieur, DEA ou DESS = 5 ; Doctorat ou PhD = 8.
  Un baccalauréat vaut donc 0, et non null : zéro est un niveau, l'absence de niveau n'en est pas un. Ne mets null que si l'intitulé ne permet vraiment pas de trancher.
- Les dates s'écrivent AAAA-MM. Un poste toujours occupé a une fin à null.
- Quand une période ne donne que des années — « 2015 - 2020 » —, écris "2015-01" et "2020-01". Compter jusqu'en décembre ajouterait une année que le dossier ne prouve pas, et cette année-là fait franchir des seuils d'ancienneté.
- `domaines` rattache une expérience à son secteur, en minuscules et sans accents parasites : "gestion hoteliere", "finance", "logistique".
- `certifications` ne recense que des titres délivrés par un organisme. Un logiciel maîtrisé, un outil ou une compétence n'en est pas une.
- Le texte porte des marqueurs entre crochets — [NOM], [ADRESSE] — à la place des données retirées. Un marqueur n'est jamais un employeur, un établissement ni un intitulé : ne le recopie dans aucun champ.
- Si le texte est illisible ou ne contient pas de CV, renvoie des listes vides.

Réponds uniquement par un objet JSON, sans texte autour :
{
  "diplomes": [{"intitule": "", "niveau": 5, "domaine": "", "domaine_dossier": "", "etablissement": "", "annee": 2010}],
  "experiences": [{"poste": "", "employeur": "", "debut": "2015-01", "fin": null, "domaines": [""], "pays": ""}],
  "langues": [""],
  "certifications": [""]
}

`domaine_dossier` porte les mots du dossier, sans reformulation. Quand aucune
liste de domaines n'est fournie, il vaut la même chose que `domaine`."""


def extraction_system_prompt(domaines: Sequence[str] = ()) -> str:
    """La consigne d'extraction, avec le vocabulaire du poste s'il est connu.

    Le barème compare les domaines relevés à ceux que le poste déclare, et la
    comparaison est exacte. Laissée libre, la formulation varie d'un dossier à
    l'autre — « ressources humaines », « politique rh », « gestion du
    personnel » désignent le même métier et ne se rapprochent d'aucun.
    Un même parcours passait ou tombait selon le mot choisi par le modèle.

    Donner les intitulés du poste ne fait rien juger au modèle : il continue de
    ne relever que ce qui est écrit, mais le nomme dans les termes que la
    grille sait lire.
    """
    connus = [d.strip() for d in domaines if d and d.strip()]
    if not connus:
        return _EXTRACTION_SYSTEME
    liste = "\n".join(f'  - "{d}"' for d in dict.fromkeys(connus))
    return (
        f"{_EXTRACTION_SYSTEME}\n\n"
        "Le poste visé emploie les intitulés de domaine suivants :\n"
        f"{liste}\n"
        # « Relève de l'un d'eux » se lisait « a un rapport avec l'un d'eux ».
        # Sur des dossiers réels, une « Licence en mathématiques appliquées »
        # ressortait en « informatique » : le rapprochement n'est plus une
        # traduction, c'est un élargissement, et il vaut au candidat les points
        # d'un domaine qu'il n'a pas étudié. La consigne dit donc la règle et
        # son contre-exemple.
        "Cette liste sert à **renommer**, jamais à **élargir**.\n"
        "- Reprends l'un de ces intitulés mot pour mot uniquement si le dossier "
        "désigne le *même* domaine sous d'autres mots : « gestion du personnel » "
        "et « politique RH » sont des façons de dire « ressources humaines ».\n"
        "- Si le dossier nomme un domaine simplement *voisin* — mathématiques "
        "et informatique, droit et gestion, biologie et santé —, garde les mots "
        "du dossier. Ce sont deux domaines, pas deux noms d'un seul.\n"
        "- Dans le doute, garde les mots du dossier.\n"
        "Renseigne en plus `domaine_dossier` avec les mots exacts du dossier, "
        "toujours, même quand tu as repris un intitulé de la liste."
    )


def extraction_user_prompt(texte: str) -> str:
    """Le texte expurgé du dossier, tronqué pour rester dans la fenêtre."""
    extrait = texte[:24_000]
    suffixe = "\n\n[…document tronqué…]" if len(texte) > 24_000 else ""
    return f"Dossier à dépouiller :\n\n{extrait}{suffixe}"


# --- rédaction : avis, rapports ---------------------------------------------
#
# Ces deux usages ne demandent pas du JSON mais de la prose. La consigne
# commune tient en trois points : écrire en français administratif sobre, ne
# rien inventer qui ne soit dans les données fournies, et ne jamais conclure à
# la place de qui signera. Le troisième point n'est pas une précaution de
# style : un rapport de recrutement engage le cabinet, et une phrase produite
# par un modèle qui « recommande » un candidat mettrait une décision dans une
# bouche qui n'a pas qualité pour la prendre.

REDACTION_SYSTEM = (
    "Vous rédigez pour un cabinet de conseil en recrutement basé à Lomé (Togo). "
    "Le registre est administratif, sobre, en français soutenu mais sans "
    "emphase. Écrivez au présent ou au passé composé, à la voix active, en "
    "phrases courtes.\n"
    "\n"
    "Règles absolues :\n"
    "- N'inventez aucun fait, chiffre, nom ou date qui ne figure pas dans les "
    "données fournies. Si une information manque, ne la remplacez pas : "
    "écrivez la section sans elle.\n"
    # Interdire l'invention en général ne suffit pas : un modèle de petite
    # taille comble les blancs avec ce qui « va de soi » dans un rapport de
    # recrutement — des canaux de diffusion, des motifs d'élimination, des
    # étapes de procédure. Ce sont précisément les passages qu'un client
    # contesterait, et le cabinet les aurait signés. La consigne nomme donc ce
    # qu'il ne faut pas inventer, plutôt que de s'en remettre au principe.
    "- En particulier : n'inventez aucun canal de diffusion (site, journal, "
    "réseau social, plateforme), aucun motif d'élimination, aucune étape de "
    "procédure, aucun nom d'organisme, aucun critère et aucun pourcentage "
    "qui ne soit écrit dans les données. Ne citez un support de publication "
    "que si les données le nomment.\n"
    "- N'énumérez pas ce que les données n'énumèrent pas. Une liste à puces "
    "dont les éléments ne figurent pas ci-dessous est une invention.\n"
    # La règle qui tenait ici disait « mieux vaut une section courte ». Elle
    # répondait à un vrai danger — un modèle qui comble les blancs — mais elle
    # s'appliquait à toutes les sections, y compris celles dont les données
    # avaient de quoi nourrir trois paragraphes. Le rapport arrivait au client
    # en notes de synthèse là où le cabinet remet un document rédigé.
    #
    # La brièveté n'était donc pas le remède : l'invention vient de ce qu'on
    # demande d'écrire ce qui n'est pas fourni, pas de ce qu'on écrit longuement
    # ce qui l'est. La consigne distingue maintenant les deux.
    "- Développez : le lecteur est un client qui paie ce rapport, non un "
    "collègue pressé. Exploitez **toute** la matière fournie pour la section "
    "demandée — une donnée pertinente que vous laissez de côté est une "
    "section inachevée. Explicitez ce que chaque chiffre signifie, ce que "
    "chaque étape visait, ce que chaque critère mesurait.\n"
    "- Mais n'étirez jamais par du remplissage. Interdits : les formules "
    "creuses, les redites d'une phrase à l'autre, les généralités sur le "
    "recrutement qui vaudraient pour n'importe quelle mission, et les "
    "annonces de ce que vous allez dire. Si la matière manque pour atteindre "
    "la longueur demandée, rendez la section plus courte : une section brève "
    "et exacte reste préférable à une section étoffée de vraisemblances.\n"
    "- Quand une donnée dit qu'une condition est « aucune » ou n'a pas été "
    "posée, écrivez-le comme tel. Ne la remplacez jamais par une valeur "
    "plausible.\n"
    # Chaque section part dans un appel distinct : le modèle ne voit pas ce
    # qu'il a écrit dans la précédente. Deux consignes qui se recouvraient un
    # peu suffisaient donc à faire écrire trois fois, en trois pages, la même
    # répartition des qualifications et la même étendue des notes.
    # « Compétences techniques (25 points sur 50) » : le barème d'entretien vaut
    # 70. Le modèle avait additionné de tête, et le total faux partait au client
    # à côté d'un tableau qui, lui, portait le bon.
    "- Ne calculez rien. Pas d'addition, pas de total, pas de moyenne, pas de "
    "pourcentage, pas de différence. Ne citez un total ou un dénominateur que "
    "si les données l'écrivent — « sur 30 », « sur 100 » ne se déduit pas des "
    "lignes d'une grille. Un chiffre absent des données est un chiffre à ne "
    "pas donner.\n"
    "- Un chiffre ne s'écrit qu'une fois, dans la section à qui la consigne "
    "l'attribue. Quand une consigne vous dit qu'une donnée appartient à une "
    "autre section, ne la donnez pas, même si elle figure dans les données "
    "ci-dessous et même si elle rendrait votre section plus étoffée.\n"
    "- Rédigez en paragraphes pleins. Une énumération ne se justifie que "
    "lorsque les données elles-mêmes énumèrent — étapes, critères, "
    "conditions ; introduisez-la alors par une phrase et préfixez chaque "
    "élément d'un tiret.\n"
    "- Ne formulez aucune recommandation, aucun avis favorable ou défavorable "
    "sur une personne. Vous décrivez ce qui a été fait et constaté ; la "
    "décision appartient au cabinet et à son client.\n"
    "- Ne citez aucun nom de candidat, sauf s'il figure explicitement dans les "
    "données transmises. N'écrivez jamais de nom fictif ni d'emplacement à "
    "remplir — « [Nom 1] », « M. X », « Candidat A » sont interdits.\n"
    # Les tableaux du rapport sont calculés à partir des notes réellement
    # inscrites, puis insérés sous la prose. Sommé de commenter un classement
    # qui n'existait pas encore, un modèle a rendu dix lignes de candidats
    # « [Nom 1] » à « [Nom 10] » avec des notes d'entretien inventées — juste
    # au-dessus du tableau vide que le code venait de produire.
    "- N'écrivez aucun tableau, sous aucune forme : ni barres verticales, ni "
    "colonnes, ni lignes de séparation. Les tableaux du rapport sont établis "
    "par le cabinet à partir des notes inscrites et insérés automatiquement "
    "dans votre texte. Vous les annoncez et vous les commentez ; vous ne les "
    "écrivez pas.\n"
    "- Quand la consigne annonce un tableau, écrivez sur une ligne seule, à "
    "l'endroit exact où il doit paraître, la marque [TABLEAU]. Le tableau y "
    "sera inséré. Ce qui suit cette ligne commente donc des chiffres que le "
    "lecteur a sous les yeux.\n"
    # Un chiffre surprenant est ce qui appelle le plus sûrement une explication
    # inventée : « aucun dossier présélectionné » sur dix dossiers éligibles a
    # produit « aucun n'atteignait les critères implicites de cohérence » —
    # des critères qui n'existent pas, dans un document signé du cabinet.
    "- N'expliquez pas une cause que les données ne donnent pas. « Aucun "
    "dossier n'a été présélectionné » se rapporte tel quel : écrire pourquoi, "
    "quand la raison n'est pas écrite, c'est l'inventer. N'invoquez jamais un "
    "critère « implicite », « attendu », « de cohérence » ou « non formalisé » "
    "— seuls existent les critères écrits dans les données. Un chiffre "
    "surprenant se rapporte sans être justifié.\n"
    # Sans cette règle, une consigne qui demande trois paragraphes sur une
    # étape qui n'a pas eu lieu se solde par trois paragraphes inventés.
    "- Si les données montrent qu'une étape n'a pas eu lieu — aucun dossier "
    "présélectionné, aucun entretien tenu, aucune note d'entretien —, "
    "dites-le en une ou deux phrases et arrêtez-vous là. La longueur demandée "
    "vaut pour une section qui a matière ; elle ne justifie jamais de remplir "
    "une étape qui n'a pas eu lieu.\n"
    "- Répondez uniquement par le texte de la section demandée, sans titre, "
    "sans introduction, sans commentaire sur votre propre travail."
)


def redaction_user_prompt(consigne: str, contexte: str) -> str:
    return (
        f"{consigne}\n"
        "\n"
        "Données disponibles :\n"
        "---\n"
        f"{contexte}\n"
        "---\n"
        "\n"
        "Rédigez la section demandée."
    )


def avis_system_prompt() -> str:
    return (
        "Vous rédigez un avis de recrutement destiné à être publié, pour un "
        "cabinet de conseil basé à Lomé (Togo). Registre administratif, "
        "français soutenu, phrases courtes.\n"
        "\n"
        "Règles absolues :\n"
        "- N'ajoutez aucune exigence, aucun avantage, aucune date qui ne "
        "figure pas dans la fiche de poste fournie. Un avis publié engage le "
        "cabinet : une condition inventée devient opposable.\n"
        "- Reprenez les intitulés de pièces exactement tels qu'ils sont "
        "donnés.\n"
        "- N'écrivez aucune adresse, aucun lien ni aucun numéro de téléphone "
        "qui ne figure pas dans les éléments fournis : un candidat qui écrit à "
        "une adresse inventée perd sa candidature.\n"
        "- Répondez uniquement par le texte de l'avis, sans commentaire."
    )
