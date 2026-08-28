"""
quality_checks.py
------------------
Calcule les indicateurs de qualité à partir d'un DataFrame d'interviews.

Deux familles de sources sont reconnues :
1. Données issues de la connexion API GraphQL (survey_client.list_interviews) :
   colonnes responsibleName, notAnsweredCount, errorsCount, status,
   wasCompleted, createdDate, updateDateUtc, questionnaireVariable...
2. Données manuelles (export tabulaire Survey Solutions, fichier CSV/Excel
   maison, ou mode démonstration) : colonnes interviewer, duration_minutes,
   n_missing, n_answered, latitude, longitude, rejected...

Toutes les fonctions sont robustes à l'absence de colonnes : elles ne
plantent pas et renvoient un indicateur neutre si la donnée n'existe pas.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED_COLUMNS_HINT = {
    "interviewer": ["interviewer", "responsibleName", "ResponsibleName", "responsible"],
    "status": ["status", "Status", "InterviewStatus"],
    "duration_minutes": ["duration_minutes", "InterviewDuration", "duration"],
    "n_missing_raw": ["notAnsweredCount", "n_missing", "missing_count"],
    "n_answered": ["n_answered", "answered_count"],
    "n_errors_raw": ["errorsCount", "n_errors"],
    "completed": ["wasCompleted", "completed"],
    "latitude": ["gps_lat", "Latitude", "lat", "latitude"],
    "longitude": ["gps_lon", "Longitude", "lon", "longitude"],
    "rejected": ["rejected", "is_rejected"],
}

# Statuts Survey Solutions correspondant à un rejet (voir capture d'écran
# "Enquêtes et Statuts" : Rejeté par le Chef d'Equipe / Rejeté par le HQ)
REJECTED_STATUSES = {"RejectedBySupervisor", "RejectedByHeadquarters", "Rejected"}
APPROVED_STATUSES = {"ApprovedBySupervisor", "ApprovedByHeadquarters", "Approved"}


def _first_match(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Renomme les colonnes reconnues vers un schéma interne standard."""
    df = df.copy()
    for target, candidates in REQUIRED_COLUMNS_HINT.items():
        match = _first_match(df, candidates)
        if match and match != target:
            df[target] = df[match]

    if "interviewer" not in df.columns:
        df["interviewer"] = "Inconnu"

    # dérive le statut de rejet depuis `status` si la colonne dédiée n'existe pas
    if "rejected" not in df.columns and "status" in df.columns:
        df["rejected"] = df["status"].isin(REJECTED_STATUSES)

    if "completed" not in df.columns and "status" in df.columns:
        df["completed"] = df["status"].notna() & ~df["status"].isin(
            ["SupervisorAssigned", "InterviewerAssigned"]
        )

    return df


def missing_rate(df: pd.DataFrame) -> pd.DataFrame:
    """
    Indicateur de valeurs manquantes.
    - Si n_missing/n_answered sont disponibles (export détaillé) : vrai taux (%).
    - Sinon, si notAnsweredCount (API) est disponible : on garde le compte brut ;
      il sera normalisé de façon relative entre enquêteurs dans scoring.py.
    """
    df = df.copy()
    if "n_missing" in df.columns and "n_answered" in df.columns:
        total = (df["n_missing"].fillna(0) + df["n_answered"].fillna(0)).replace(0, np.nan)
        df["missing_rate"] = df["n_missing"].fillna(0) / total
    elif "n_missing_raw" in df.columns:
        df["missing_rate"] = np.nan  # taux non calculable ; le compte brut sera utilisé
    else:
        df["missing_rate"] = np.nan
    return df


def duplicate_flags(df: pd.DataFrame, key_columns: list[str] | None = None) -> pd.DataFrame:
    """Marque les interviews potentiellement dupliquées sur des colonnes clés."""
    df = df.copy()
    key_columns = key_columns or [
        c for c in ["household_id", "respondent_name", "gps_lat", "gps_lon", "key"]
        if c in df.columns
    ]
    if key_columns:
        df["is_duplicate"] = df.duplicated(subset=key_columns, keep=False)
    else:
        df["is_duplicate"] = False
    return df


def duration_outliers(df: pd.DataFrame, min_minutes: float = 10, max_minutes: float = 180) -> pd.DataFrame:
    """Flag les interviews trop courtes (bâclées) ou anormalement longues."""
    df = df.copy()
    if "duration_minutes" in df.columns:
        df["duration_flag"] = np.where(
            df["duration_minutes"] < min_minutes, "trop_courte",
            np.where(df["duration_minutes"] > max_minutes, "trop_longue", "normale"),
        )
    else:
        df["duration_flag"] = "inconnue"
    return df


def gps_anomalies(df: pd.DataFrame, min_distance_m: float = 15.0) -> pd.DataFrame:
    """
    Détecte les GPS manquants et les points quasi-identiques entre interviews
    d'un même enquêteur (signe possible de fabrication de données depuis un
    point fixe / bureau plutôt que sur le terrain).
    """
    df = df.copy()
    if "latitude" not in df.columns or "longitude" not in df.columns:
        df["gps_flag"] = "inconnu"
        return df

    df["gps_flag"] = np.where(df["latitude"].isna() | df["longitude"].isna(), "manquant", "ok")

    if "interviewer" in df.columns:
        for interviewer, sub in df.groupby("interviewer"):
            coords = sub[["latitude", "longitude"]].dropna()
            if len(coords) < 2:
                continue
            lat_rad = np.radians(coords["latitude"].mean())
            m_per_deg_lat = 111_320
            m_per_deg_lon = 111_320 * np.cos(lat_rad)
            for i, (idx_i, row_i) in enumerate(coords.iterrows()):
                for idx_j, row_j in list(coords.iterrows())[i + 1:]:
                    dx = (row_i["longitude"] - row_j["longitude"]) * m_per_deg_lon
                    dy = (row_i["latitude"] - row_j["latitude"]) * m_per_deg_lat
                    dist = np.sqrt(dx**2 + dy**2)
                    if dist < min_distance_m:
                        df.loc[idx_i, "gps_flag"] = "points_suspects_identiques"
                        df.loc[idx_j, "gps_flag"] = "points_suspects_identiques"
    return df


def outlier_flags(df: pd.DataFrame, numeric_columns: list[str] | None = None, z_threshold: float = 3.0) -> pd.DataFrame:
    """
    Détecte les valeurs aberrantes (z-score) sur les colonnes numériques
    métier choisies. Si `errorsCount` (API) est disponible, on l'utilise en
    complément direct plutôt que de recalculer un z-score dessus.
    """
    df = df.copy()
    numeric_columns = numeric_columns or []
    numeric_columns = [c for c in numeric_columns if c in df.columns]
    df["n_outliers"] = 0
    for col in numeric_columns:
        series = df[col]
        std = series.std(ddof=0)
        if not std or np.isnan(std):
            continue
        z = (series - series.mean()) / std
        df["n_outliers"] += (z.abs() > z_threshold).astype(int).fillna(0)

    if "n_errors_raw" in df.columns:
        df["n_outliers"] = df["n_outliers"] + df["n_errors_raw"].fillna(0)

    return df


def run_all_checks(df: pd.DataFrame) -> pd.DataFrame:
    """Pipeline complet de contrôle qualité, retourne le DataFrame enrichi."""
    df = normalize_columns(df)
    df = missing_rate(df)
    df = duplicate_flags(df)
    df = duration_outliers(df)
    df = gps_anomalies(df)
    df = outlier_flags(df)
    return df
