"""
aggregate_report.py
--------------------
Gère le format du rapport "Enquêtes et Statuts" téléchargeable depuis le
menu Rapports > Enquêtes et Statuts de Survey Solutions Headquarters (voir
capture d'écran fournie). Ce rapport est agrégé PAR QUESTIONNAIRE : il ne
contient pas de colonne "enquêteur". Le filtre "Enquêteur (équipe)" à
l'écran ne fait que restreindre les comptages à la personne choisie — il
faut donc exporter une fois par enquêteur pour reconstituer un tableau
comparatif.

Colonnes exactes du fichier XLSX exporté (français, avec accents) :
    Titre du questionnaire, Version du questionnaire,
    Affecté au Chef d'Equipe, Affecté à l'Enquêteur, Achevé,
    Rejeté par le Chef d'Equipe, Approuvé par le Chef d'Equipe,
    Rejeté par le HQ, Approuvé par le HQ, Total
"""

from __future__ import annotations

import pandas as pd

EXPECTED_COLUMNS = [
    "Titre du questionnaire",
    "Affecté au Chef d'Equipe",
    "Affecté à l'Enquêteur",
    "Achevé",
    "Rejeté par le Chef d'Equipe",
    "Approuvé par le Chef d'Equipe",
    "Rejeté par le HQ",
    "Approuvé par le HQ",
    "Total",
]


def looks_like_aggregate_report(df: pd.DataFrame) -> bool:
    """Détecte si un fichier importé correspond au format 'Enquêtes et Statuts'."""
    cols = set(df.columns)
    hits = sum(1 for c in EXPECTED_COLUMNS if c in cols)
    return hits >= 6  # tolérant aux petites variations de colonnes annexes


def build_interviewer_table(uploaded_files: list[tuple[str, pd.DataFrame, str]]) -> pd.DataFrame:
    """
    Combine plusieurs exports 'Enquêtes et Statuts' (un par enquêteur) en un
    tableau unique.

    uploaded_files : liste de tuples (nom_fichier, dataframe, nom_enqueteur)
    """
    rows = []
    for filename, df, interviewer_name in uploaded_files:
        if df.empty:
            continue
        # Le rapport peut contenir une ligne par questionnaire : on les somme
        # toutes pour cet enquêteur (utile si plusieurs questionnaires actifs).
        agg = {col: pd.to_numeric(df[col], errors="coerce").sum() for col in EXPECTED_COLUMNS[1:]}
        agg["interviewer"] = interviewer_name
        agg["source_file"] = filename
        rows.append(agg)

    result = pd.DataFrame(rows)
    return result


def compute_aggregate_scores(agg_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcule un score de qualité par enquêteur à partir des comptages de
    statuts (rapport agrégé, sans données au niveau interview).

    Formule, volontairement simple et transparente vu le niveau de détail
    disponible :
        taux_rejet       = (Rejeté Chef d'Equipe + Rejeté HQ) / Total
        taux_approbation  = (Approuvé Chef d'Equipe + Approuvé HQ) / Total
        taux_en_attente   = (Affecté Chef d'Equipe + Affecté Enquêteur) / Total
        score_qualite     = 100 x (1 - taux_rejet)
    """
    df = agg_df.copy()
    df["Total"] = df["Total"].replace(0, pd.NA)

    df["rejetes"] = df["Rejeté par le Chef d'Equipe"] + df["Rejeté par le HQ"]
    df["approuves"] = df["Approuvé par le Chef d'Equipe"] + df["Approuvé par le HQ"]
    df["en_attente"] = df["Affecté au Chef d'Equipe"] + df["Affecté à l'Enquêteur"]

    df["taux_rejet"] = (df["rejetes"] / df["Total"]).fillna(0)
    df["taux_approbation"] = (df["approuves"] / df["Total"]).fillna(0)
    df["taux_en_attente"] = (df["en_attente"] / df["Total"]).fillna(0)
    df["taux_achevement"] = (df["Achevé"] / df["Total"]).fillna(0)

    df["score_qualite"] = (100 * (1 - df["taux_rejet"])).round(1)

    df = df.sort_values("score_qualite", ascending=False).reset_index(drop=True)
    df["rang"] = range(1, len(df) + 1)
    df["grade"] = pd.cut(
        df["score_qualite"], bins=[-1, 50, 65, 80, 90, 100], labels=["E", "D", "C", "B", "A"]
    )
    return df
