"""
quality_checks.py
------------------
Fonctions de calcul des indicateurs de qualité de données à partir d'un
DataFrame d'interviews (une ligne = une interview) et, si disponible,
d'un DataFrame de réponses au niveau variable.

Toutes les fonctions sont conçues pour être robustes à l'absence de
certaines colonnes (elles renvoient alors des indicateurs neutres plutôt
que de planter), afin de fonctionner aussi bien avec un export réel
Survey Solutions qu'avec des données de démonstration.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


REQUIRED_COLUMNS_HINT = {
    "interviewer": ["ResponsibleName", "interviewer", "responsible"],
    "status": ["Status", "InterviewStatus", "status"],
    "duration_minutes": ["duration_minutes", "InterviewDuration", "duration"],
    "n_missing": ["n_missing", "missing_count"],
    "n_answered": ["n_answered", "answered_count"],
    "latitude": ["gps_lat", "Latitude", "lat"],
    "longitude": ["gps_lon", "Longitude", "lon"],
    "rejected": ["rejected", "is_rejected"],
}


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
    return df


def missing_rate(df: pd.DataFrame) -> pd.DataFrame:
    """Taux de valeurs manquantes par interview, agrégé ensuite par enquêteur."""
    df = df.copy()
    if "n_missing" in df.columns and "n_answered" in df.columns:
        total = (df["n_missing"].fillna(0) + df["n_answered"].fillna(0)).replace(0, np.nan)
        df["missing_rate"] = df["n_missing"].fillna(0) / total
    else:
        df["missing_rate"] = np.nan
    return df


def duplicate_flags(df: pd.DataFrame, key_columns: list[str] | None = None) -> pd.DataFrame:
    """Marque les interviews potentiellement dupliquées sur des colonnes clés."""
    df = df.copy()
    key_columns = key_columns or [c for c in ["household_id", "respondent_name", "gps_lat", "gps_lon"] if c in df.columns]
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
            # distance approximative en mètres (approximation plane, suffisante à cette échelle)
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
    """Détecte les valeurs aberrantes (z-score) sur les colonnes numériques choisies."""
    df = df.copy()
    numeric_columns = numeric_columns or df.select_dtypes(include=[np.number]).columns.tolist()
    numeric_columns = [c for c in numeric_columns if c in df.columns]
    df["n_outliers"] = 0
    for col in numeric_columns:
        series = df[col]
        std = series.std(ddof=0)
        if not std or np.isnan(std):
            continue
        z = (series - series.mean()) / std
        df["n_outliers"] += (z.abs() > z_threshold).astype(int).fillna(0)
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
