"""Génère un jeu de données d'interviews synthétique pour le mode démo."""

from __future__ import annotations

import numpy as np
import pandas as pd


def generate_demo_interviews(n_interviewers: int = 10, interviews_per_interviewer: int = 40, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    names = [f"Enquêteur {chr(65 + i)}" for i in range(n_interviewers)]
    # Chaque enquêteur a un "profil de qualité" propre pour rendre le classement réaliste
    profiles = rng.uniform(0.3, 1.0, size=n_interviewers)  # 1.0 = très bon

    base_lat, base_lon = 12.1348, 15.0557  # N'Djamena
    rows = []
    interview_id = 1
    for i, name in enumerate(names):
        quality = profiles[i]
        for _ in range(interviews_per_interviewer):
            duration = rng.normal(45 * quality + 15, 8)
            n_answered = rng.integers(60, 120)
            n_missing = max(0, int(rng.poisson((1 - quality) * 8)))
            is_dup_candidate = rng.random() < (1 - quality) * 0.08
            lat = base_lat + (rng.normal(0, 0.05) if rng.random() < quality else rng.normal(0, 0.0005))
            lon = base_lon + (rng.normal(0, 0.05) if rng.random() < quality else rng.normal(0, 0.0005))
            rejected = rng.random() < (1 - quality) * 0.1

            rows.append({
                "interview_id": interview_id,
                "interviewer": name,
                "duration_minutes": max(3, round(duration, 1)),
                "n_answered": n_answered,
                "n_missing": n_missing,
                "household_id": f"HH_{interview_id}" if not is_dup_candidate else f"HH_DUP_{i}",
                "gps_lat": lat,
                "gps_lon": lon,
                "rejected": rejected,
                "status": "Rejected" if rejected else "Completed",
            })
            interview_id += 1
    df = pd.DataFrame(rows)
    df = df.rename(columns={"gps_lat": "latitude", "gps_lon": "longitude"})
    return df
