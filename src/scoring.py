"""
scoring.py
----------
Calcule un score de qualité (0-100) par enquêteur à partir des indicateurs
produits par quality_checks.run_all_checks().

Le score est une moyenne pondérée de pénalités (chaque indicateur ramené à
un taux entre 0 et 1), avec des poids ajustables depuis l'interface. Un
enquêteur sans aucune anomalie obtient 100 ; chaque taux d'anomalie réduit
le score proportionnellement à son poids.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_WEIGHTS = {
    "missing_rate": 25,      # taux de valeurs manquantes
    "duplicate_rate": 20,    # taux de doublons
    "duration_rate": 20,     # interviews trop courtes/longues
    "gps_rate": 20,          # anomalies GPS
    "outlier_rate": 10,      # valeurs aberrantes
    "rejection_rate": 5,     # interviews rejetées par le contrôle HQ
}


def _safe_rate(series: pd.Series) -> float:
    if series is None or len(series) == 0:
        return 0.0
    val = series.mean()
    return float(val) if pd.notna(val) else 0.0


def compute_interviewer_scores(df: pd.DataFrame, weights: dict | None = None) -> pd.DataFrame:
    """
    df : DataFrame déjà passé par quality_checks.run_all_checks()
    weights : dict de poids (somme idéalement = 100, mais renormalisé si besoin)
    """
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    total_weight = sum(weights.values()) or 1
    weights = {k: v / total_weight for k, v in weights.items()}

    if "interviewer" not in df.columns:
        df = df.copy()
        df["interviewer"] = "Inconnu"

    rows = []
    for interviewer, sub in df.groupby("interviewer"):
        n = len(sub)

        missing_r = _safe_rate(sub.get("missing_rate"))
        duplicate_r = _safe_rate(sub.get("is_duplicate").astype(float)) if "is_duplicate" in sub.columns else 0.0
        duration_r = _safe_rate((sub.get("duration_flag") != "normale").astype(float)) if "duration_flag" in sub.columns else 0.0
        gps_r = _safe_rate((~sub.get("gps_flag").isin(["ok"])).astype(float)) if "gps_flag" in sub.columns else 0.0
        outlier_r = _safe_rate((sub.get("n_outliers") > 0).astype(float)) if "n_outliers" in sub.columns else 0.0
        rejection_r = _safe_rate(sub.get("rejected").astype(float)) if "rejected" in sub.columns else 0.0

        penalty = (
            weights["missing_rate"] * missing_r
            + weights["duplicate_rate"] * duplicate_r
            + weights["duration_rate"] * duration_r
            + weights["gps_rate"] * gps_r
            + weights["outlier_rate"] * outlier_r
            + weights["rejection_rate"] * rejection_r
        )
        score = max(0.0, 100.0 * (1 - penalty))

        rows.append({
            "interviewer": interviewer,
            "n_interviews": n,
            "taux_manquants": missing_r,
            "taux_doublons": duplicate_r,
            "taux_duree_anormale": duration_r,
            "taux_anomalies_gps": gps_r,
            "taux_aberrants": outlier_r,
            "taux_rejet": rejection_r,
            "score_qualite": round(score, 1),
        })

    result = pd.DataFrame(rows).sort_values("score_qualite", ascending=False).reset_index(drop=True)
    result["rang"] = np.arange(1, len(result) + 1)
    result["grade"] = pd.cut(
        result["score_qualite"],
        bins=[-1, 50, 65, 80, 90, 100],
        labels=["E", "D", "C", "B", "A"],
    )
    return result
