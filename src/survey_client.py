"""
survey_client.py
-----------------
Client Python pour l'API Headquarters de Survey Solutions.

Points importants :
- Survey Solutions expose une API REST documentée par serveur, à l'adresse
  https://<votre-serveur>/apidocs/index
  Les endpoints ci-dessous correspondent à la structure standard de l'API
  publique (v1 pour les métadonnées/interviews, v2 pour l'export tabulaire).
  Selon la version installée sur votre serveur, vérifiez/ajustez ces chemins
  dans la documentation interactive de VOTRE serveur avant la mise en prod.
- Deux modes d'authentification sont supportés : Basic (identifiant/mot de
  passe d'un compte de rôle "API User") et Bearer (jeton API), lorsque ce
  dernier est activé sur le serveur.
"""

from __future__ import annotations

import io
import time
import zipfile
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import requests


class SurveySolutionsAPIError(Exception):
    """Erreur levée pour tout problème de communication avec le serveur."""


@dataclass
class SurveyCredentials:
    server_url: str
    workspace: str = "primary"
    auth_mode: str = "basic"  # "basic" ou "token"
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None


class SurveySolutionsClient:
    """Client HTTP léger pour l'API Survey Solutions Headquarters."""

    def __init__(self, creds: SurveyCredentials, timeout: int = 60):
        self.creds = creds
        self.timeout = timeout
        self.base = creds.server_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

        if creds.auth_mode == "token" and creds.token:
            self.session.headers.update(
                {"Authorization": f"Bearer {creds.token}"}
            )
        else:
            self.session.auth = (creds.username or "", creds.password or "")

    # ------------------------------------------------------------------
    # Bas niveau
    # ------------------------------------------------------------------
    def _url(self, path: str) -> str:
        ws = self.creds.workspace.strip("/")
        path = path.lstrip("/")
        # Les endpoints "workspace-aware" suivent le schéma /api/v1/{ws}/...
        return f"{self.base}/api/v1/{ws}/{path}" if ws and ws != "primary" \
            else f"{self.base}/api/v1/{path}"

    def _get(self, path: str, params: dict | None = None) -> requests.Response:
        try:
            resp = self.session.get(self._url(path), params=params, timeout=self.timeout)
        except requests.exceptions.RequestException as exc:
            raise SurveySolutionsAPIError(f"Erreur réseau : {exc}") from exc
        if resp.status_code == 401:
            raise SurveySolutionsAPIError("Authentification refusée (401). Vérifiez identifiant/mot de passe/token.")
        if resp.status_code == 403:
            raise SurveySolutionsAPIError("Accès refusé (403). Le compte n'a probablement pas le rôle API.")
        if resp.status_code >= 400:
            raise SurveySolutionsAPIError(f"Erreur HTTP {resp.status_code} sur {path} : {resp.text[:300]}")
        return resp

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------
    def test_connection(self) -> bool:
        """Vérifie que le serveur répond et que l'authentification passe."""
        self._get("questionnaires", params={"limit": 1})
        return True

    def list_questionnaires(self) -> pd.DataFrame:
        resp = self._get("questionnaires", params={"limit": 200})
        data = resp.json()
        items = data.get("Questionnaires", data) if isinstance(data, dict) else data
        return pd.json_normalize(items)

    def list_interviews(self, questionnaire_id: str, version: int, limit: int = 2000) -> pd.DataFrame:
        """Liste les interviews (statuts, enquêteur, dates, durée, GPS...)."""
        params = {
            "questionnaireId": questionnaire_id,
            "questionnaireVersion": version,
            "limit": limit,
        }
        resp = self._get("interviews", params=params)
        data = resp.json()
        items = data.get("Interviews", data) if isinstance(data, dict) else data
        return pd.json_normalize(items)

    def request_tabular_export(self, questionnaire_id: str, version: int,
                                export_format: str = "Tabular") -> str:
        """Démarre un job d'export et retourne son identifiant."""
        payload = {
            "ExportType": export_format,
            "QuestionnaireId": questionnaire_id,
            "QuestionnaireVersion": version,
        }
        resp = self.session.post(
            self._url("export").replace("/api/v1/", "/api/v2/"),
            json=payload, timeout=self.timeout,
        )
        if resp.status_code >= 400:
            raise SurveySolutionsAPIError(f"Échec de la demande d'export : {resp.status_code} {resp.text[:300]}")
        return resp.json().get("JobId") or resp.json().get("Id")

    def wait_for_export(self, job_id: str, poll_seconds: int = 3, max_wait: int = 180) -> str:
        waited = 0
        status_url = self._url(f"export/{job_id}").replace("/api/v1/", "/api/v2/")
        while waited < max_wait:
            resp = self.session.get(status_url, timeout=self.timeout)
            resp.raise_for_status()
            status = resp.json().get("ExportStatus", "")
            if status.lower() in ("completed", "done", "finished"):
                return status_url + "/file"
            time.sleep(poll_seconds)
            waited += poll_seconds
        raise SurveySolutionsAPIError("Délai d'attente dépassé pour la génération de l'export.")

    def download_export_zip(self, download_url: str) -> dict[str, pd.DataFrame]:
        """Télécharge et parse l'archive zip d'export tabulaire en DataFrames."""
        resp = self.session.get(download_url, timeout=self.timeout)
        resp.raise_for_status()
        frames = {}
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            for name in z.namelist():
                if name.lower().endswith(".tab") or name.lower().endswith(".csv"):
                    with z.open(name) as f:
                        frames[name] = pd.read_csv(f, sep="\t" if name.endswith(".tab") else ",")
        return frames
