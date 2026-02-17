# TripReport Webapp

## Description du projet
Application web Flask permettant de rechercher, scraper, traduire et afficher des trip reports de substances psychoactives. L'utilisateur tape un nom de substance, le programme scrape les sources, traduit en français, et affiche tout dans une interface web moderne.

## Stack technique
- **Backend** : Python 3.11+, Flask, Flask-SocketIO
- **Scraping** : requests, BeautifulSoup4
- **Traduction** : deep-translator (Google Translate, 100% gratuit, pas de clé API)
- **Frontend** : HTML/CSS/JS vanilla (pas de framework), Socket.IO client
- **Cache** : fichiers JSON locaux dans `data/`

## Architecture des fichiers

```
tripreport-webapp/
├── CLAUDE.md
├── requirements.txt          # Flask, flask-socketio, requests, beautifulsoup4, deep-translator, lxml
├── app.py                    # Application Flask principale + routes + WebSocket
├── scraper/
│   ├── __init__.py
│   ├── erowid.py             # Scraper Erowid (liste + contenu individuel)
│   ├── psychonaut.py         # Scraper Psychonaut.fr (liste + contenu individuel)
│   └── psychonautwiki.py     # Scraper PsychonautWiki (liste + contenu individuel)
├── translator/
│   ├── __init__.py
│   └── translate.py          # Module de traduction via deep-translator
├── cache/
│   ├── __init__.py
│   └── manager.py            # Gestion du cache JSON local
├── data/                     # Dossier de cache (créé automatiquement)
│   └── {substance_name}/     # Un sous-dossier par substance
│       ├── index.json        # Liste des rapports scrapés (métadonnées)
│       └── reports/           # Un fichier JSON par rapport traduit
│           ├── {report_id}.json
│           └── ...
├── templates/
│   ├── index.html            # Page d'accueil avec champ de recherche
│   ├── substance.html        # Dashboard d'une substance (liste des rapports)
│   └── report.html           # Page individuelle d'un rapport traduit
└── static/
    ├── css/
    │   └── style.css         # Style dark theme inspiré du fichier fourni
    └── js/
        └── main.js           # Logique frontend + Socket.IO client
```

## Fonctionnalités détaillées

### 1. Page d'accueil (`/`)
- Champ de recherche centré, design minimaliste dark theme
- L'utilisateur tape un nom de substance (ex: "4-HO-MET", "cannabis", "LSD")
- Bouton "Rechercher" ou Entrée pour lancer
- En dessous : liste des substances déjà en cache (accès instantané)

### 2. Page substance (`/substance/<name>`)
- Si la substance est en cache → chargement instantané depuis `data/`
- Si pas en cache → lance le scraping en temps réel avec affichage progressif via WebSocket
- **Barre de progression** : "Scraping Erowid... 15/47 rapports" etc.
- **Dashboard** similaire au HTML fourni en pièce jointe :
  - Stats en haut (nombre total, recommandés, solo, combo, etc.)
  - Grille de cartes avec : titre, auteur, date, substances, rating, source
  - **Filtres latéraux** : recherche titre/auteur/substance, langue, solo/combo, date, rating
  - Chaque carte a un lien "Lire le rapport" qui ouvre la page traduite

### 3. Page rapport (`/report/<substance>/<report_id>`)
- Affiche le trip report complet traduit en français
- Header : titre, auteur, date, substances utilisées, dosages, source originale
- Corps : texte traduit, bien formaté avec les sections chronologiques si présentes
- Lien vers le rapport original
- Bouton retour vers le dashboard

### 4. Scraping

#### Erowid (`scraper/erowid.py`)
- **Liste des rapports** : scraper `https://www.erowid.org/experiences/subs/exp_{substance}.shtml`
  - Chaque ligne du tableau contient : titre, auteur, rating, date, lien
  - Gérer la pagination si elle existe
  - Le nom de substance dans l'URL peut varier (ex: "4HOMET", "Cannabis", "LSD") → prévoir un mapping ou une recherche
- **Rapport individuel** : scraper `https://www.erowid.org/experiences/exp.php?ID={id}`
  - Extraire : titre complet, auteur, date de soumission, substances + dosages (tableau en haut), body text, rating/catégorie
  - Le body text est dans un `<div class="report-text-surround">` contenant le texte principal
  - Conserver la structure des paragraphes et des timestamps si présents (ex: "T+0:00", "T+1:30")
  - **Important** : respecter un délai entre les requêtes (1-2 secondes) pour ne pas se faire bloquer
  - User-Agent réaliste dans les headers

#### Psychonaut.fr (`scraper/psychonaut.py`)
- **Liste des rapports** : scraper la catégorie trip reports ou rechercher par substance
  - URL de base : `https://www.psychonaut.fr/categories/trip-reports-vos-experiences-psychedeliques.148/`
  - Chercher les threads contenant le nom de la substance dans le titre
- **Rapport individuel** : scraper le premier post du thread
  - Extraire : titre, auteur, date, contenu du premier message
  - Le contenu est déjà en français → pas besoin de traduire
  - Marquer `language: "fr"` dans les métadonnées

#### PsychonautWiki (`scraper/psychonautwiki.py`)
- **Liste des rapports** : scraper `https://psychonautwiki.org/wiki/Experience_index` ou la page spécifique de la substance
- **Rapport individuel** : scraper la page wiki de l'expérience
  - Extraire le contenu textuel principal
  - Format plus simple que Erowid

#### Règles communes pour tous les scrapers
- Headers HTTP réalistes (User-Agent navigateur)
- Délai de 1-2 secondes entre chaque requête
- Gestion des erreurs (timeout, 404, contenu vide)
- Chaque scraper retourne un format unifié :
```python
{
    "id": "erowid_63399",           # Identifiant unique
    "source": "erowid",             # ou "psychonaut", "psychonautwiki"
    "title": "Beautiful Introduction to a New Substitution",
    "author": "Xorkoth",
    "date": "2007-07-31",
    "url": "https://www.erowid.org/experiences/exp.php?ID=63399",
    "language": "en",               # "en" ou "fr"
    "rating": "Highly Recommended", # si disponible
    "substances": [
        {"name": "4-HO-MET", "dose": "20mg", "route": "oral"}
    ],
    "body_original": "...",         # Texte original complet
    "body_translated": "...",       # Texte traduit en français (vide si déjà fr)
}
```

### 5. Traduction (`translator/translate.py`)
- Utiliser `deep_translator.GoogleTranslator`
- Traduire anglais → français uniquement (les rapports Psychonaut.fr sont déjà en français)
- **Découper le texte** en chunks de max 4500 caractères (limite Google Translate) en respectant les limites de paragraphes
- Conserver les timestamps (T+0:00, T+1:30, etc.) sans les traduire
- Conserver les noms de substances sans les traduire
- Gérer les erreurs de traduction (retry 3 fois avec délai)
- Délai de 0.5s entre chaque chunk pour éviter le rate limiting

### 6. Cache (`cache/manager.py`)
- **Structure** : `data/{substance_slug}/index.json` + `data/{substance_slug}/reports/{report_id}.json`
- `substance_slug` : nom normalisé en minuscules, espaces remplacés par des tirets (ex: "4-ho-met", "cannabis")
- `index.json` contient la liste des métadonnées de tous les rapports (sans le body)
- Chaque `{report_id}.json` contient le rapport complet (métadonnées + body original + body traduit)
- **Vérification** : avant de scraper, vérifier si le rapport existe déjà en cache
- **Mise à jour incrémentale** : si on relance une recherche, ne scraper que les nouveaux rapports
- Horodatage du dernier scraping dans `index.json`

### 7. WebSocket (affichage progressif)
- Quand le scraping commence, envoyer des événements via Socket.IO :
  - `scraping_start` : `{"source": "erowid", "total": 47}`
  - `report_scraped` : `{"source": "erowid", "current": 15, "total": 47, "title": "..."}`
  - `report_translated` : `{"report_id": "erowid_63399", "title": "..."}`
  - `scraping_complete` : `{"total_reports": 120}`
- Le frontend ajoute les cartes au fur et à mesure qu'elles arrivent
- Barre de progression globale en haut de la page

### 8. Design / Frontend

#### Thème visuel
- **Dark theme** inspiré du HTML fourni en pièce jointe
- Palette : fond `#121214`, panneaux `#1A1A1E`, containers `#202024`, accent `#F0EAD6`
- Font : `'Roboto Mono', 'Fira Code', monospace`
- Bordures subtiles `#222327`, ombres douces
- Couleurs spéciales : titres verts `#5D9152`, tags beige `#CE9178`, méta-infos jaunes `#E5DC94`

#### Page d'accueil
- Centré verticalement, titre du projet en haut
- Grand champ de recherche avec placeholder "Entrez le nom d'une substance..."
- En dessous : grille de boutons pour les substances déjà en cache
- Animation subtile au hover

#### Page substance (dashboard)
- Layout : sidebar filtres à gauche + grille de cartes à droite
- Stats en haut : rapports affichés, recommandés, solo, combo, total
- Cartes avec : titre (vert), auteur+date (jaune), substances (tags beige), rating, source, lien "Lire"
- **Filtres** : recherche titre/auteur/substance, langue (fr/en/toutes), checkboxes (recommandé, solo, combo), slider nombre substances, dates
- Sidebar repliable sur desktop, overlay sur mobile
- Responsive (mobile = 1 colonne)

#### Page rapport
- Layout centré, max-width 800px, bonne lisibilité
- Header avec métadonnées bien présentées
- Corps du texte avec bonne typographie, espacement entre paragraphes
- Timestamps stylisés (ex: badges colorés pour T+0:00)
- Bouton retour et lien vers l'original

#### Barre de progression (pendant le scraping)
- Fixée en haut de la page substance
- Barre animée + texte "Scraping Erowid... 15/47"
- Disparaît une fois le scraping terminé
- Les cartes apparaissent progressivement avec une animation fade-in

## Contraintes techniques

- **100% gratuit** : pas de clé API payante, pas de service externe payant
- **Respecter les sites scrapés** : délais entre requêtes, User-Agent réaliste, pas de requêtes parallèles massives
- **Robustesse** : gestion des erreurs à chaque étape, retry sur échec, logs clairs dans la console
- **Performance** : le cache doit rendre les recherches répétées instantanées
- **Code propre** : fonctions bien séparées, docstrings, typehints Python

## Commandes

```bash
# Installation
pip install -r requirements.txt

# Lancement
python app.py
# → Ouvre http://localhost:5000
```

## Notes importantes

- Les rapports de Psychonaut.fr sont déjà en français → ne pas les traduire, juste les scraper
- Erowid peut changer sa structure HTML → le scraper doit être facilement maintenable
- Google Translate a des limites de débit → espacer les requêtes de traduction
- Certains rapports Erowid ont des structures variées (tableaux de dosage, sections chronologiques) → être flexible dans le parsing
- Le programme doit fonctionner en local sans connexion internet une fois les données en cache
