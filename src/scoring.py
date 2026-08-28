"""
scoring.py
----------
Calcule un score de qualité (0-100) par enquêteur à partir des indicateurs
produits par quality_checks.run_all_checks().

Deux types d'indicateurs sont combinés :
- des TAUX déjà compris entre 0 et 1 (ex : missing_rate calculé sur un
  export détaillé, taux de doublons, taux de durée anormale...) ;
- des COMPTES BRUTS (ex : notAnsweredCount / errorsCount renvoyés par l'API
  GraphQL, sans total de référence pour en faire un vrai pourcentage). Pour
  ceux-ci, on calcule un taux RELATIF par normalisation min-max entre les
  enquêteurs du jeu de données : 0 = l'enquêteur le "mieux classé" du groupe
  sur ce critère, 1 = le "moins bien classé". C'est cohérent avec l'objectif
  (comparer les enquêteurs entre eux) même quand le pourcentage absolu n'est
  pas calculable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_WEIGHTS = {
    "missing_rate": 25,      # valeurs manquantes (taux réel ou relatif)
    "duplicate_rate": 20,    # doublons
    "duration_rate": 20,     # interviews trop courtes/longues
    "gps_rate": 20,          # anomalies GPS
    "outlier_rate": 10,      # valeurs aberrantes / erreurs de validation
    "rejection_rate": 5,     # interviews rejetées (superviseur ou HQ)
}


def _safe_mean(series: pd.Series | None) -> float:
    if series is None or len(series) == 0:
        return np.nan
    val = series.mean()
    return float(val) if pd.notna(val) else np.nan


def _minmax_normalize(values: pd.Series) -> pd.Series:
    """Ramène une série à [0, 1], 1 = valeur la plus défavorable (la plus haute)."""
    if values.isna().all():
        return pd.Series(0.0, index=values.index)
    vmin, vmax = values.min(), values.max()
    if vmax == vmin:
        return pd.Series(0.0, index=values.index)
    return (values - vmin) / (vmax - vmin)


def compute_interviewer_scores(df: pd.DataFrame, weights: dict | None = None) -> pd.DataFrame:
    """
    df : DataFrame déjà passé par quality_checks.run_all_checks()
    weights : dict de poids (somme non contrainte, renormalisée automatiquement)
    """
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    total_weight = sum(weights.values()) or 1
    weights = {k: v / total_weight for k, v in weights.items()}

    if "interviewer" not in df.columns:
        df = df.copy()
        df["interviewer"] = "Inconnu"

    per_interviewer = []
    for interviewer, sub in df.groupby("interviewer"):
        n = len(sub)
        row = {"interviewer": interviewer, "n_interviews": n}

        # --- Valeurs manquantes : taux réel si possible, sinon compte brut ---
        if "missing_rate" in sub.columns and sub["missing_rate"].notna().any():
            row["missing_rate_real"] = _safe_mean(sub["missing_rate"])
            row["missing_raw"] = np.nan
        else:
            row["missing_rate_real"] = np.nan
            row["missing_raw"] = _safe_mean(sub.get("n_missing_raw"))

        # --- Doublons ---
        row["duplicate_rate"] = _safe_mean(sub["is_duplicate"].astype(float)) if "is_duplicate" in sub.columns else 0.0

        # --- Durée anormale ---
        row["duration_rate"] = (
            _safe_mean((sub["duration_flag"] != "normale").astype(float))
            if "duration_flag" in sub.columns and (sub["duration_flag"] != "inconnue").any()
            else 0.0
        )

        # --- Anomalies GPS ---
        row["gps_rate"] = (
            _safe_mean((~sub["gps_flag"].isin(["ok"])).astype(float))
            if "gps_flag" in sub.columns and (sub["gps_flag"] != "inconnu").any()
            else 0.0
        )

        # --- Aberrants / erreurs ---
        row["outlier_raw"] = _safe_mean(sub.get("n_outliers"))

        # --- Rejets ---
        row["rejection_rate"] = _safe_mean(sub["rejected"].astype(float)) if "rejected" in sub.columns else 0.0

        # --- Achèvement (indicateur informatif, pas de pénalité) ---
        row["completion_rate"] = _safe_mean(sub["completed"].astype(float)) if "completed" in sub.columns else np.nan

        per_interviewer.append(row)

    result = pd.DataFrame(per_interviewer)

    # Normalisation relative des indicateurs "bruts" (comptes sans total de référence)
    if result["missing_raw"].notna().any():
        result["missing_rate_norm"] = _minmax_normalize(result["missing_raw"].fillna(result["missing_raw"].mean()))
    else:
        result["missing_rate_norm"] = result["missing_rate_real"].fillna(0)

    result["outlier_rate_norm"] = _minmax_normalize(result["outlier_raw"].fillna(0))

    # --- Score composite ---
    penalty = (
        weights["missing_rate"] * result["missing_rate_norm"].fillna(0)
        + weights["duplicate_rate"] * result["duplicate_rate"].fillna(0)
        + weights["duration_rate"] * result["duration_rate"].fillna(0)
        + weights["gps_rate"] * result["gps_rate"].fillna(0)
        + weights["outlier_rate"] * result["outlier_rate_norm"].fillna(0)
        + weights["rejection_rate"] * result["rejection_rate"].fillna(0)
    )
    result["score_qualite"] = (100 * (1 - penalty)).clip(lower=0).round(1)

    # colonnes d'affichage lisibles (taux réel si dispo, sinon indicateur relatif)
    result["taux_manquants"] = result["missing_rate_real"].fillna(result["missing_rate_norm"])
    result["manquants_est_relatif"] = result["missing_rate_real"].isna()
    result["taux_doublons"] = result["duplicate_rate"]
    result["taux_duree_anormale"] = result["duration_rate"]
    result["taux_anomalies_gps"] = result["gps_rate"]
    result["taux_aberrants"] = result["outlier_rate_norm"]
    result["taux_rejet"] = result["rejection_rate"]

    result = result.sort_values("score_qualite", ascending=False).reset_index(drop=True)
    result["rang"] = np.arange(1, len(result) + 1)
    result["grade"] = pd.cut(
        result["score_qualite"],
        bins=[-1, 50, 65, 80, 90, 100],
        labels=["E", "D", "C", "B", "A"],
    )
    return result
