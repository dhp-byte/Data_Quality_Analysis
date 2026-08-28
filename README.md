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

## Quatre façons d'alimenter l'application

1. **Démonstration** : jeu de données synthétique (profils de qualité variés
   par enquêteur) pour tester toutes les fonctionnalités sans serveur.

2. **Connexion au serveur (API)** — *corrigée dans cette version.* Renseignez
   l'URL du serveur, le **workspace** (souvent `primary`), l'identifiant et le
   mot de passe d'un compte **API User**. L'application liste les
   questionnaires puis récupère les interviews (enquêteur, statut, valeurs
   manquantes, erreurs) via l'API **GraphQL** du serveur.

3. **Rapport agrégé "Enquêtes et Statuts"** — le rapport que vous téléchargez
   depuis *Rapports > Enquêtes et Statuts* dans l'interface Survey Solutions.
   ⚠️ Ce rapport est agrégé **par questionnaire**, pas par enquêteur : pour
   obtenir un score par enquêteur avec cette méthode, filtrez un enquêteur à
   la fois dans le menu déroulant *"Enquêteur (équipe)"*, téléchargez le
   fichier, répétez pour chaque enquêteur, puis importez tous les fichiers
   dans l'application (un enquêteur par fichier).

4. **Export détaillé (CSV/Excel)** : un fichier avec une ligne par interview
   (par ex. un export tabulaire Survey Solutions), utile si vous avez besoin
   de la durée d'interview ou des coordonnées GPS (non disponibles via l'API
   standard — voir plus bas).

## Correction importante par rapport à la première version

La toute première version de ce module utilisait une structure d'URL
inventée (`/api/v1/{workspace}/...`) et proposait une authentification par
jeton "Bearer" qui n'existe pas dans l'API standard de Survey Solutions.
Ces deux points ont été corrigés après vérification du **code source réel**
des bibliothèques officielles (`arthur-shaw/susoapi` en R) :

- Le **workspace fait partie du chemin, avant `/api/...`** :
  `https://<serveur>/<workspace>/graphql`,
  `https://<serveur>/<workspace>/api/v2/export`.
- L'authentification standard est **HTTP Basic** avec un compte de rôle
  *API User*, créé par l'administrateur du serveur (Équipe et rôles).
- Le **listing des questionnaires et des interviews** se fait via l'endpoint
  **GraphQL** (`/graphql`), les endpoints REST `/api/v1/questionnaires` et
  `/api/v1/interviews` (au pluriel) étant dépréciés.

Si la connexion échoue encore, vérifiez dans l'ordre :
1. L'URL est bien celle du **Headquarters** (pas d'un lien direct vers un
   fichier ou une page de rapport), sans `/` final superflu.
2. Le nom du **workspace** est exact et respecte la casse (visible dans
   l'URL de votre espace de travail une fois connecté dans le navigateur).
3. Le compte utilisé a bien le rôle **API User** (ou administrateur) et
   accès à ce workspace précis (Équipe et rôles > Utilisateurs).
4. Le serveur est accessible publiquement en HTTPS (pas seulement depuis un
   réseau interne).

## Ce qui est disponible selon la source

| Indicateur                | Démonstration | API (GraphQL) | Rapport agrégé | Export détaillé |
|----------------------------|:---:|:---:|:---:|:---:|
| Enquêteur                  | ✅ | ✅ | ✅ | ✅ (si colonne présente) |
| Valeurs manquantes          | ✅ (taux réel) | ⚠️ (compte brut, classement relatif) | — | ✅ (si colonnes fournies) |
| Doublons                   | ✅ | — | — | ✅ (si colonnes clés fournies) |
| Durée d'interview            | ✅ | ❌ (nécessite un export paradata) | — | ✅ (si colonne fournie) |
| GPS                         | ✅ | ❌ (nécessite l'export tabulaire) | — | ✅ (si colonnes fournies) |
| Erreurs de validation        | — | ✅ (`errorsCount`) | — | ✅ (si colonnes fournies) |
| Rejets (superviseur/HQ)      | ✅ | ✅ (déduit du statut) | ✅ (cœur du score) | ✅ (si colonne fournie) |

## Le score de qualité par enquêteur

Pour les modes Démonstration / API / Export détaillé (module `scoring.py`) :

```
score = 100 × (1 − Σ poids_i × taux_anomalie_i)
```

Chaque `taux_anomalie_i` est soit un **vrai pourcentage** (quand la donnée le
permet, ex. mode démonstration), soit un **classement relatif** normalisé
entre 0 et 1 par min-max entre les enquêteurs du jeu de données (quand seule
une valeur brute sans total de référence est disponible, ex. `notAnsweredCount`
et `errorsCount` renvoyés par l'API). L'application affiche clairement quand
un indicateur est relatif plutôt qu'un pourcentage absolu.

Pour le mode **Rapport agrégé**, le score est plus simple faute de détail
disponible (module `aggregate_report.py`) :

```
score = 100 × (1 − taux_de_rejet)
taux_de_rejet = (Rejeté par le Chef d'Equipe + Rejeté par le HQ) / Total
```

Dans tous les cas : grade **A–E**, rang, et — pour les modes détaillés — un
radar des taux d'anomalies par enquêteur.

## Structure du projet

```
survey_quality_app/
├── app.py                  # Interface Streamlit principale
├── requirements.txt
├── .streamlit/config.toml  # Thème visuel
└── src/
    ├── survey_client.py    # Client API Survey Solutions (GraphQL, Basic Auth)
    ├── quality_checks.py   # Indicateurs de qualité (manquants, doublons, GPS, durée, erreurs)
    ├── scoring.py           # Score composite par enquêteur (taux réels + classement relatif)
    ├── aggregate_report.py  # Traitement du rapport "Enquêtes et Statuts"
    ├── demo_data.py         # Générateur de données de démonstration
    └── ui_style.py          # CSS personnalisé (cartes KPI, badges de grade)
```

## Prochaines étapes suggérées

- Ajouter la récupération de la **durée réelle** des interviews via un export
  **Paradata** (temps entre le premier et le dernier événement de chaque
  interview) — plus complexe que l'export tabulaire simple, non implémenté
  dans cette version.
- Exploiter l'export tabulaire (`start_tabular_export` / `wait_for_export` /
  `download_export_zip`, déjà présents dans `survey_client.py`) pour
  récupérer automatiquement les variables GPS du questionnaire sans passer
  par un fichier CSV/Excel manuel.
- Ajouter un historique des scores dans le temps (stocker les exports
  périodiques et suivre l'évolution d'un enquêteur d'une semaine à l'autre).
