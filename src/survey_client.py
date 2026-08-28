"""
survey_client.py
-----------------
Client Python pour l'API Headquarters de Survey Solutions — RÉÉCRIT à partir
du code source réel des bibliothèques officielles (packages R `susoapi` et
`ssaw`), afin de corriger les erreurs de la première version :

1. Le WORKSPACE fait partie du CHEMIN de l'URL, AVANT /api/... :
       {serveur}/{workspace}/api/v2/export
       {serveur}/{workspace}/graphql
   (et non {serveur}/api/v1/{workspace}/... comme dans la v1 de ce fichier)

2. L'authentification standard de l'API Survey Solutions est HTTP Basic
   (compte "API User" créé par l'administrateur) ; il n'y a pas de mécanisme
   Bearer/JWT documenté pour cette API — l'option "jeton API" de la v1 était
   erronée et a été retirée.

3. Le LISTING des questionnaires et des interviews se fait via l'endpoint
   GraphQL (/graphql), les anciens endpoints REST /api/v1/questionnaires et
   /api/v1/interviews (pluriels) étant dépréciés. Les endpoints REST
   unitaires (/api/v1/interviews/{id}/..., approve/reject/assign) restent
   eux valides.

Référence du code source consulté : https://github.com/arthur-shaw/susoapi
(fichiers R/export.R, R/interviews.R, R/questionnaires.R, R/utils.R)
"""

from __future__ import annotations

import io
import time
import zipfile
from dataclasses import dataclass

import pandas as pd
import requests


class SurveySolutionsAPIError(Exception):
    """Erreur levée pour tout problème de communication avec le serveur."""


@dataclass
class SurveyCredentials:
    server_url: str
    workspace: str = "primary"
    username: str = ""
    password: str = ""


# Nœuds (champs) disponibles sur la requête GraphQL "interviews"
INTERVIEW_NODES = [
    "id", "key", "assignmentId",
    "questionnaireId", "questionnaireVersion", "questionnaireVariable",
    "responsibleName", "responsibleId", "responsibleRole", "supervisorName",
    "status", "actionFlags", "wasCompleted",
    "notAnsweredCount", "errorsCount",
    "createdDate", "updateDateUtc", "receivedByInterviewerAtUtc",
    "interviewMode",
]


class SurveySolutionsClient:
    """Client HTTP pour l'API Survey Solutions Headquarters (Basic Auth)."""

    def __init__(self, creds: SurveyCredentials, timeout: int = 60):
        self.creds = creds
        self.timeout = timeout
        self.base = creds.server_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (creds.username, creds.password)
        self.session.headers.update({"Accept": "application/json"})

    # ------------------------------------------------------------------
    # Construction des URLs — le workspace est TOUJOURS dans le chemin
    # ------------------------------------------------------------------
    def _rest_url(self, path: str) -> str:
        ws = self.creds.workspace.strip("/")
        return f"{self.base}/{ws}/api/v1/{path.lstrip('/')}"

    def _export_url(self, path: str = "") -> str:
        ws = self.creds.workspace.strip("/")
        return f"{self.base}/{ws}/api/v2/export/{path.lstrip('/')}".rstrip("/")

    def _graphql_url(self) -> str:
        ws = self.creds.workspace.strip("/")
        return f"{self.base}/{ws}/graphql"

    # ------------------------------------------------------------------
    # GraphQL — bas niveau
    # ------------------------------------------------------------------
    def _graphql(self, query: str, variables: dict | None = None) -> dict:
        try:
            resp = self.session.post(
                self._graphql_url(),
                json={"query": query, "variables": variables or {}},
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as exc:
            raise SurveySolutionsAPIError(
                f"Erreur réseau lors de l'appel GraphQL : {exc}"
            ) from exc

        if resp.status_code == 401:
            raise SurveySolutionsAPIError(
                "Authentification refusée (401). Vérifiez l'identifiant/mot de passe "
                "du compte API et son accès au workspace indiqué."
            )
        if resp.status_code == 404:
            raise SurveySolutionsAPIError(
                f"Endpoint GraphQL introuvable (404) à l'adresse {self._graphql_url()}. "
                "Vérifiez l'URL du serveur et le nom exact du workspace."
            )
        if resp.status_code >= 400:
            raise SurveySolutionsAPIError(
                f"Erreur HTTP {resp.status_code} sur l'appel GraphQL : {resp.text[:300]}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise SurveySolutionsAPIError(
                "Réponse du serveur illisible (pas du JSON). "
                "Vérifiez que l'URL pointe bien vers un serveur Survey Solutions."
            ) from exc

        if "errors" in data and data["errors"]:
            messages = "; ".join(e.get("message", str(e)) for e in data["errors"])
            raise SurveySolutionsAPIError(f"Erreur GraphQL : {messages}")

        return data

    # ------------------------------------------------------------------
    # Connexion
    # ------------------------------------------------------------------
    def test_connection(self) -> bool:
        """Vérifie serveur + authentification + accès au workspace."""
        query = """
        query ($workspace: String!) {
            questionnaires(workspace: $workspace, take: 1) {
                filteredCount
            }
        }
        """
        self._graphql(query, {"workspace": self.creds.workspace})
        return True

    # ------------------------------------------------------------------
    # Questionnaires
    # ------------------------------------------------------------------
    def list_questionnaires(self) -> pd.DataFrame:
        query = """
        query ($workspace: String!) {
            questionnaires(workspace: $workspace) {
                nodes {
                    id
                    questionnaireId
                    version
                    variable
                    title
                    defaultLanguageName
                }
                filteredCount
            }
        }
        """
        data = self._graphql(query, {"workspace": self.creds.workspace})
        nodes = data["data"]["questionnaires"]["nodes"]
        if not nodes:
            return pd.DataFrame(columns=["id", "questionnaireId", "version", "variable", "title"])
        return pd.json_normalize(nodes)

    # ------------------------------------------------------------------
    # Interviews
    # ------------------------------------------------------------------
    def count_interviews(self, questionnaire_id: str, version: int) -> int:
        query = """
        query ($workspace: String!, $qid: String!, $ver: Int!) {
            interviews(
                workspace: $workspace
                where: { questionnaireId: { eq: $qid }, questionnaireVersion: { eq: $ver } }
                take: 1
                skip: 0
            ) {
                filteredCount
            }
        }
        """
        data = self._graphql(query, {
            "workspace": self.creds.workspace, "qid": questionnaire_id, "ver": version,
        })
        return data["data"]["interviews"]["filteredCount"]

    def list_interviews(
        self, questionnaire_id: str, version: int,
        max_interviews: int = 5000, chunk_size: int = 200,
        progress_callback=None,
    ) -> pd.DataFrame:
        """Récupère les interviews (avec enquêteur, statut, indicateurs) en paginant."""
        total = self.count_interviews(questionnaire_id, version)
        n_to_fetch = min(total, max_interviews)

        node_fields = "\n".join(INTERVIEW_NODES)
        query = f"""
        query ($workspace: String!, $qid: String!, $ver: Int!, $take: Int!, $skip: Int!) {{
            interviews(
                workspace: $workspace
                where: {{ questionnaireId: {{ eq: $qid }}, questionnaireVersion: {{ eq: $ver }} }}
                take: $take
                skip: $skip
            ) {{
                nodes {{
                    {node_fields}
                }}
                filteredCount
            }}
        }}
        """

        all_rows = []
        skip = 0
        while skip < n_to_fetch:
            take = min(chunk_size, n_to_fetch - skip)
            data = self._graphql(query, {
                "workspace": self.creds.workspace, "qid": questionnaire_id,
                "ver": version, "take": take, "skip": skip,
            })
            nodes = data["data"]["interviews"]["nodes"]
            if not nodes:
                break
            all_rows.extend(nodes)
            skip += len(nodes)
            if progress_callback:
                progress_callback(skip, n_to_fetch)
            if len(nodes) < take:
                break  # plus rien à paginer

        if not all_rows:
            return pd.DataFrame(columns=INTERVIEW_NODES)
        return pd.json_normalize(all_rows)

    # ------------------------------------------------------------------
    # Export tabulaire (optionnel/avancé — pour GPS, variables métier, etc.)
    # Confirmé par le code source de susoapi : POST/GET /api/v2/export
    # Le champ QuestionnaireId attendu est au format "guid$version"
    # ------------------------------------------------------------------
    def start_tabular_export(self, questionnaire_id: str, version: int,
                              export_type: str = "Tabular",
                              interview_status: str = "All") -> int:
        body = {
            "ExportType": export_type,
            "QuestionnaireId": f"{questionnaire_id}${version}",
            "InterviewStatus": interview_status,
            "IncludeMeta": "true",
        }
        resp = self.session.post(self._export_url(), json=body, timeout=self.timeout)
        if resp.status_code != 201:
            raise SurveySolutionsAPIError(
                f"Échec de la demande d'export (HTTP {resp.status_code}) : {resp.text[:300]}"
            )
        return resp.json()["JobId"]

    def get_export_status(self, job_id: int) -> dict:
        resp = self.session.get(self._export_url(str(job_id)), timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def wait_for_export(self, job_id: int, poll_seconds: int = 3, max_wait: int = 300) -> None:
        waited = 0
        while waited < max_wait:
            details = self.get_export_status(job_id)
            status = details.get("ExportStatus", "")
            if status == "Completed":
                return
            if status in ("Fail", "Canceled"):
                raise SurveySolutionsAPIError(f"L'export a échoué (statut : {status}).")
            time.sleep(poll_seconds)
            waited += poll_seconds
        raise SurveySolutionsAPIError("Délai d'attente dépassé pour la génération de l'export.")

    def download_export_zip(self, job_id: int) -> dict[str, pd.DataFrame]:
        url = self._export_url(f"{job_id}/file")
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        frames = {}
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            for name in z.namelist():
                if name.lower().endswith((".tab", ".csv")):
                    with z.open(name) as f:
                        frames[name] = pd.read_csv(f, sep="\t" if name.endswith(".tab") else ",")
        return frames
