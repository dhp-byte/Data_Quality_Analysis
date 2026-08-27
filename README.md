# Survey Solutions — Data Quality & Interviewer Scoring

Application Streamlit pour l'analyse de la qualité des données collectées via
**Survey Solutions** et le calcul d'un **score de qualité par enquêteur**.

## Installation

```bash
python -m venv venv
source venv/bin/activate        # Windows : venv\Scripts\activate
pip install -r requirements.txt
```

## Lancement

```bash
streamlit run app.py
```

## Trois façons d'alimenter l'application

1. **Mode Démonstration** (par défaut) : génère un jeu de données synthétique
   réaliste (10 enquêteurs, profils de qualité variés) pour tester
   immédiatement toutes les fonctionnalités sans serveur.
2. **Connexion au serveur Survey Solutions** : renseignez l'URL du serveur,
   l'identifiant/mot de passe (compte de rôle *API User* recommandé) ou un
   jeton API, puis le workspace. L'application liste les questionnaires
   disponibles et charge les interviews via l'API REST.
3. **Import d'un fichier local** (CSV ou Excel) : utile si vous exportez déjà
   vos données manuellement, ou pour brancher un export tabulaire Survey
   Solutions préalablement téléchargé.

> ⚠️ **Important — endpoints API** : les chemins utilisés dans
> `src/survey_client.py` correspondent à la structure standard de l'API
> Survey Solutions (`/api/v1/...` pour les métadonnées et interviews,
> `/api/v2/export/...` pour l'export tabulaire). Chaque serveur expose sa
> documentation interactive à jour à l'adresse
> `https://<votre-serveur>/apidocs/index` — vérifiez-y la version exacte des
> endpoints avant une mise en production, et ajustez `survey_client.py` si
> nécessaire.

## Colonnes reconnues automatiquement

Le module `quality_checks.py` reconnaît plusieurs noms de colonnes courants
(voir `REQUIRED_COLUMNS_HINT`). Au minimum, pour un calcul de score complet,
vos données devraient contenir :

| Donnée              | Noms de colonnes acceptés                         |
|---------------------|----------------------------------------------------|
| Enquêteur           | `interviewer`, `ResponsibleName`, `responsible`    |
| Statut interview     | `status`, `Status`, `InterviewStatus`              |
| Durée (minutes)      | `duration_minutes`, `InterviewDuration`            |
| Réponses manquantes  | `n_missing`                                        |
| Réponses saisies     | `n_answered`                                       |
| Latitude / Longitude | `latitude`/`gps_lat`, `longitude`/`gps_lon`        |
| Rejet HQ             | `rejected`, `is_rejected`                          |

Si une colonne est absente, l'indicateur correspondant est neutralisé (il
n'impacte pas le score) plutôt que de faire planter l'application.

## Le score de qualité par enquêteur

Pour chaque enquêteur, un score de **0 à 100** est calculé (module
`scoring.py`) comme :

```
score = 100 × (1 − Σ poids_i × taux_anomalie_i)
```

avec les indicateurs suivants (poids par défaut ajustables dans la barre
latérale) :

- **Valeurs manquantes** (25) — proportion de réponses non renseignées
- **Doublons** (20) — interviews potentiellement dupliquées
- **Durée anormale** (20) — interviews trop courtes (bâclées) ou trop longues
- **Anomalies GPS** (20) — coordonnées manquantes ou points quasi-identiques
  entre interviews d'un même enquêteur (indice de fabrication de données)
- **Valeurs aberrantes** (10) — détection par z-score sur les variables
  numériques
- **Rejet HQ** (5) — interviews rejetées lors du contrôle qualité central

Chaque enquêteur reçoit aussi un **grade A–E** et un **rang**. Le détail par
enquêteur (onglet *Score par enquêteur*) affiche un radar des six taux
d'anomalies pour visualiser rapidement ses points faibles.

## Structure du projet

```
survey_quality_app/
├── app.py                  # Interface Streamlit principale
├── requirements.txt
├── .streamlit/config.toml  # Thème visuel
└── src/
    ├── survey_client.py    # Client API Survey Solutions (Basic / Bearer)
    ├── quality_checks.py   # Indicateurs de qualité (manquants, doublons, GPS, durée, aberrants)
    ├── scoring.py          # Score composite par enquêteur
    ├── demo_data.py        # Générateur de données de démonstration
    └── ui_style.py         # CSS personnalisé (cartes KPI, badges de grade)
```

## Prochaines étapes suggérées

- Brancher `request_tabular_export` / `wait_for_export` / `download_export_zip`
  sur un vrai questionnaire pour récupérer aussi les **paradata** (temps par
  question, réponses modifiées) et enrichir encore le score.
- Ajouter un historique des scores (suivi de l'évolution d'un enquêteur dans
  le temps) en stockant les exports périodiques dans une base ou un fichier
  Parquet.
- Ajouter une authentification à l'application elle-même si elle est déployée
  pour plusieurs superviseurs (via `st.secrets` ou un reverse-proxy).
