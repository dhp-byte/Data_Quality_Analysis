"""
Survey Solutions — Data Quality & Interviewer Scoring
======================================================
Application Streamlit pour l'analyse de la qualité des données collectées
via Survey Solutions et le calcul d'un score de qualité par enquêteur.

Lancement :
    streamlit run app.py
"""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.aggregate_report import (
    build_interviewer_table,
    compute_aggregate_scores,
    looks_like_aggregate_report,
)
from src.demo_data import generate_demo_interviews
from src.quality_checks import run_all_checks
from src.scoring import DEFAULT_WEIGHTS, compute_interviewer_scores
from src.survey_client import (
    SurveyCredentials,
    SurveySolutionsAPIError,
    SurveySolutionsClient,
)
from src.ui_style import CUSTOM_CSS, grade_badge, kpi_card

st.set_page_config(
    page_title="Survey Solutions — Data Quality",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ----------------------------------------------------------------------
# État de session
# ----------------------------------------------------------------------
for key, default in {
    "client": None, "raw_df": None, "mode": None, "agg_files": [],
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ----------------------------------------------------------------------
# En-tête
# ----------------------------------------------------------------------
st.markdown(
    """
    <div class="app-header">
        <h1>📊 Survey Solutions — Contrôle Qualité & Score par Enquêteur</h1>
        <p>Connexion au serveur, analyse de la qualité des données collectées et classement des enquêteurs.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ----------------------------------------------------------------------
# SIDEBAR — Source des données
# ----------------------------------------------------------------------
with st.sidebar:
    st.header("🔐 Source des données")

    data_source = st.radio(
        "Choisir une source",
        options=[
            "Démonstration",
            "Connexion au serveur (API)",
            "Rapport agrégé 'Enquêtes et Statuts' (1 fichier par enquêteur)",
            "Export détaillé (CSV/Excel, 1 ligne = 1 interview)",
        ],
        index=0,
    )

    # ------------------------------------------------------------
    # MODE 1 — Démonstration
    # ------------------------------------------------------------
    if data_source == "Démonstration":
        st.info("Données simulées pour tester l'application sans serveur.")
        n_int = st.slider("Nombre d'enquêteurs (démo)", 3, 25, 10)
        n_per = st.slider("Interviews par enquêteur (démo)", 10, 100, 40)
        if st.button("🎲 Générer les données de démonstration", type="primary", use_container_width=True):
            st.session_state.raw_df = generate_demo_interviews(n_int, n_per)
            st.session_state.mode = "demo"
            st.success("Données de démonstration générées.")

    # ------------------------------------------------------------
    # MODE 2 — Connexion API (GraphQL, Basic Auth)
    # ------------------------------------------------------------
    elif data_source == "Connexion au serveur (API)":
        st.caption(
            "Authentification **Basic** avec un compte de rôle *API User* "
            "(créé par l'administrateur du serveur). Le workspace doit être "
            "renseigné exactement comme il apparaît dans l'URL de votre "
            "espace de travail (souvent `primary`)."
        )
        server_url = st.text_input("URL du serveur", placeholder="https://survey.monorganisation.org")
        workspace = st.text_input("Workspace", value="primary")
        username = st.text_input("Identifiant API")
        password = st.text_input("Mot de passe", type="password")

        col_a, col_b = st.columns(2)
        connect_clicked = col_a.button("🔌 Se connecter", type="primary", use_container_width=True)
        disconnect_clicked = col_b.button("⏻ Déconnexion", use_container_width=True)

        if disconnect_clicked:
            st.session_state.client = None
            st.session_state.raw_df = None
            st.session_state.mode = None
            st.success("Déconnecté.")

        if connect_clicked:
            if not server_url or not username or not password:
                st.error("Veuillez renseigner l'URL du serveur, l'identifiant et le mot de passe.")
            else:
                creds = SurveyCredentials(
                    server_url=server_url.strip(),
                    workspace=(workspace or "primary").strip(),
                    username=username.strip(),
                    password=password,
                )
                client = SurveySolutionsClient(creds)
                with st.spinner("Test de connexion (GraphQL)..."):
                    try:
                        client.test_connection()
                        st.session_state.client = client
                        st.session_state.mode = "server"
                        st.success("✅ Connexion réussie.")
                    except SurveySolutionsAPIError as exc:
                        st.error(f"❌ Échec de connexion : {exc}")
                        st.caption(
                            "Vérifications à faire : l'URL est-elle correcte et accessible "
                            "publiquement (https, sans slash final superflu) ? Le compte est-il "
                            "bien de type *API User* (ou administrateur) ? Le nom du workspace "
                            "est-il exact (sensible à la casse) ?"
                        )

        st.divider()

        if st.session_state.client:
            st.subheader("📋 Questionnaire")
            try:
                with st.spinner("Chargement des questionnaires..."):
                    quest_df = st.session_state.client.list_questionnaires()
                if quest_df.empty:
                    st.warning("Aucun questionnaire trouvé sur ce workspace.")
                else:
                    choice = st.selectbox("Sélectionner un questionnaire", quest_df["title"].tolist())
                    selected_row = quest_df[quest_df["title"] == choice].iloc[0]
                    q_id = selected_row["questionnaireId"]
                    q_version = int(selected_row["version"])

                    max_n = st.number_input(
                        "Nombre maximal d'interviews à charger", min_value=100, max_value=20000,
                        value=3000, step=100,
                    )

                    if st.button("📥 Charger les interviews", type="primary", use_container_width=True):
                        progress = st.progress(0.0, text="Récupération des interviews...")

                        def _update_progress(done, total):
                            progress.progress(min(done / total, 1.0), text=f"{done}/{total} interviews récupérées")

                        try:
                            interviews = st.session_state.client.list_interviews(
                                q_id, q_version, max_interviews=int(max_n),
                                progress_callback=_update_progress,
                            )
                            progress.empty()
                            if interviews.empty:
                                st.warning("Aucune interview trouvée pour ce questionnaire.")
                            else:
                                st.session_state.raw_df = interviews
                                st.session_state.mode = "server"
                                st.success(f"{len(interviews)} interviews chargées.")
                        except SurveySolutionsAPIError as exc:
                            progress.empty()
                            st.error(f"Erreur lors du chargement : {exc}")
            except SurveySolutionsAPIError as exc:
                st.error(f"Impossible de récupérer les questionnaires : {exc}")

    # ------------------------------------------------------------
    # MODE 3 — Rapport agrégé "Enquêtes et Statuts"
    # ------------------------------------------------------------
    elif data_source == "Rapport agrégé 'Enquêtes et Statuts' (1 fichier par enquêteur)":
        st.caption(
            "Dans **Rapports > Enquêtes et Statuts**, sélectionnez un enquêteur à la fois "
            "dans le filtre, téléchargez le fichier XLSX, et répétez l'opération pour "
            "chaque enquêteur. Importez ensuite tous les fichiers ici."
        )
        uploaded_agg = st.file_uploader(
            "Fichiers 'Enquêtes et Statuts' (un par enquêteur)",
            type=["xlsx", "csv"], accept_multiple_files=True,
        )

        if uploaded_agg:
            st.write("Associez chaque fichier à son enquêteur :")
            files_with_names = []
            for f in uploaded_agg:
                default_name = f.name.rsplit(".", 1)[0]
                name = st.text_input(f"Enquêteur pour « {f.name} »", value=default_name, key=f"agg_name_{f.name}")
                try:
                    df_f = pd.read_csv(f) if f.name.endswith(".csv") else pd.read_excel(f)
                except Exception as exc:
                    st.error(f"Impossible de lire {f.name} : {exc}")
                    continue
                if not looks_like_aggregate_report(df_f):
                    st.warning(f"{f.name} ne ressemble pas à un export 'Enquêtes et Statuts' standard.")
                files_with_names.append((f.name, df_f, name))

            if st.button("📊 Construire le tableau par enquêteur", type="primary", use_container_width=True):
                st.session_state.agg_files = files_with_names
                st.session_state.mode = "aggregate"
                st.success(f"{len(files_with_names)} fichier(s) pris en compte.")

    # ------------------------------------------------------------
    # MODE 4 — Export détaillé manuel
    # ------------------------------------------------------------
    else:
        st.caption(
            "Importez un export contenant une ligne par interview, avec au minimum "
            "une colonne identifiant l'enquêteur (`interviewer` / `ResponsibleName`)."
        )
        uploaded = st.file_uploader("Fichier CSV/Excel détaillé", type=["csv", "xlsx"])
        if uploaded is not None:
            try:
                df_uploaded = pd.read_csv(uploaded) if uploaded.name.endswith(".csv") else pd.read_excel(uploaded)
                st.session_state.raw_df = df_uploaded
                st.session_state.mode = "upload"
                st.success(f"Fichier chargé : {len(df_uploaded)} lignes.")
            except Exception as exc:
                st.error(f"Erreur de lecture du fichier : {exc}")

    st.divider()
    st.subheader("⚙️ Pondération du score")
    st.caption("Utilisée pour les modes Démonstration / API / Export détaillé (pas pour le rapport agrégé, qui utilise le taux de rejet directement).")
    weights = {}
    weights["missing_rate"] = st.slider("Valeurs manquantes", 0, 50, DEFAULT_WEIGHTS["missing_rate"])
    weights["duplicate_rate"] = st.slider("Doublons", 0, 50, DEFAULT_WEIGHTS["duplicate_rate"])
    weights["duration_rate"] = st.slider("Durée anormale", 0, 50, DEFAULT_WEIGHTS["duration_rate"])
    weights["gps_rate"] = st.slider("Anomalies GPS", 0, 50, DEFAULT_WEIGHTS["gps_rate"])
    weights["outlier_rate"] = st.slider("Valeurs aberrantes / erreurs", 0, 50, DEFAULT_WEIGHTS["outlier_rate"])
    weights["rejection_rate"] = st.slider("Interviews rejetées", 0, 50, DEFAULT_WEIGHTS["rejection_rate"])


# ----------------------------------------------------------------------
# CORPS PRINCIPAL — Chemin "rapport agrégé"
# ----------------------------------------------------------------------
if st.session_state.mode == "aggregate":
    if not st.session_state.agg_files:
        st.info("👈 Importez au moins un fichier 'Enquêtes et Statuts' dans la barre latérale.")
        st.stop()

    agg_table = build_interviewer_table(st.session_state.agg_files)
    if agg_table.empty:
        st.warning("Aucune donnée exploitable dans les fichiers importés.")
        st.stop()

    scores_df = compute_aggregate_scores(agg_table)

    st.subheader("👤 Score de qualité par enquêteur — rapport agrégé")
    st.caption(
        "Score basé sur le taux de rejet (Chef d'Equipe + HQ) rapporté au total des "
        "interviews de chaque enquêteur : score = 100 × (1 − taux de rejet)."
    )

    c1, c2, c3 = st.columns(3)
    c1.markdown(kpi_card("Enquêteurs", f"{len(scores_df)}"), unsafe_allow_html=True)
    c2.markdown(kpi_card("Score moyen", f"{scores_df['score_qualite'].mean():.1f} / 100"), unsafe_allow_html=True)
    c3.markdown(kpi_card("Total interviews", f"{int(scores_df['Total'].sum()):,}".replace(",", " ")), unsafe_allow_html=True)

    fig = px.bar(
        scores_df, x="score_qualite", y="interviewer", orientation="h",
        color="score_qualite", color_continuous_scale=["#F87171", "#FCD34D", "#4ADE80"],
        range_color=[0, 100], text="score_qualite",
    )
    fig.update_traces(texttemplate="%{text:.0f}", textposition="outside")
    fig.update_layout(
        yaxis={"categoryorder": "total ascending"},
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font_color="#FAFAFA", coloraxis_showscale=False, height=420,
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    display_cols = [
        "rang", "interviewer", "Total", "Achevé", "score_qualite", "grade",
        "taux_rejet", "taux_approbation", "taux_en_attente", "taux_achevement",
    ]
    st.dataframe(
        scores_df[display_cols].rename(columns={
            "rang": "Rang", "interviewer": "Enquêteur", "score_qualite": "Score", "grade": "Grade",
            "taux_rejet": "% Rejet", "taux_approbation": "% Approuvé",
            "taux_en_attente": "% En attente", "taux_achevement": "% Achevé",
        }),
        use_container_width=True, hide_index=True,
        column_config={
            "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f"),
            "% Rejet": st.column_config.NumberColumn(format="%.1%"),
            "% Approuvé": st.column_config.NumberColumn(format="%.1%"),
            "% En attente": st.column_config.NumberColumn(format="%.1%"),
            "% Achevé": st.column_config.NumberColumn(format="%.1%"),
        },
    )

    csv_scores = scores_df.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Télécharger les scores (CSV)", csv_scores,
                       file_name="scores_enqueteurs_agrege.csv", mime="text/csv")
    st.stop()


# ----------------------------------------------------------------------
# CORPS PRINCIPAL — Chemins "démo / API / export détaillé"
# ----------------------------------------------------------------------
if st.session_state.raw_df is None:
    st.info(
        "👈 Choisissez une source de données dans la barre latérale pour commencer : "
        "démonstration, connexion au serveur, rapport agrégé ou export détaillé."
    )
    st.stop()

with st.spinner("Calcul des indicateurs de qualité..."):
    df = run_all_checks(st.session_state.raw_df)
    scores_df = compute_interviewer_scores(df, weights)

if scores_df["manquants_est_relatif"].any():
    st.info(
        "ℹ️ Les données chargées ne permettent pas de calculer un vrai taux de valeurs "
        "manquantes (pas de total de questions répondues). Le critère 'valeurs manquantes' "
        "est donc un **classement relatif** entre enquêteurs (0 = meilleur du groupe, "
        "1 = moins bon du groupe sur ce critère), pas un pourcentage absolu."
    )

tabs = st.tabs([
    "🏠 Vue générale",
    "👤 Score par enquêteur",
    "❌ Valeurs manquantes",
    "🔁 Doublons & aberrants",
    "⏱️ Durée des interviews",
    "📍 GPS",
    "📥 Export",
])

# ------------------------------------------------------------------
# TAB 1 — Vue générale
# ------------------------------------------------------------------
with tabs[0]:
    n_interviews = len(df)
    n_interviewers = df["interviewer"].nunique() if "interviewer" in df.columns else 0
    avg_score = scores_df["score_qualite"].mean() if not scores_df.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(kpi_card("Interviews analysées", f"{n_interviews:,}".replace(",", " ")), unsafe_allow_html=True)
    c2.markdown(kpi_card("Enquêteurs", f"{n_interviewers}"), unsafe_allow_html=True)
    c3.markdown(kpi_card("Score qualité moyen", f"{avg_score:.1f} / 100"), unsafe_allow_html=True)
    if "completion_rate" in scores_df.columns and scores_df["completion_rate"].notna().any():
        comp_display = f"{scores_df['completion_rate'].mean()*100:.1f}%"
    else:
        comp_display = "N/A"
    c4.markdown(kpi_card("Taux d'achèvement moyen", comp_display), unsafe_allow_html=True)

    st.markdown("####")
    col1, col2 = st.columns([1.3, 1])

    with col1:
        st.subheader("Score de qualité — classement des enquêteurs")
        fig = px.bar(
            scores_df, x="score_qualite", y="interviewer", orientation="h",
            color="score_qualite", color_continuous_scale=["#F87171", "#FCD34D", "#4ADE80"],
            range_color=[0, 100], text="score_qualite",
        )
        fig.update_traces(texttemplate="%{text:.0f}", textposition="outside")
        fig.update_layout(
            yaxis={"categoryorder": "total ascending"},
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            font_color="#FAFAFA", coloraxis_showscale=False, height=420,
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("Répartition des interviews par statut")
        if "status" in df.columns and df["status"].notna().any():
            status_counts = df["status"].value_counts().reset_index()
            status_counts.columns = ["status", "count"]
            fig2 = px.pie(status_counts, names="status", values="count", hole=0.55,
                          color_discrete_sequence=["#4ADE80", "#F87171", "#FCD34D", "#60A5FA", "#A78BFA", "#F472B6"])
            fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color="#FAFAFA",
                               margin=dict(l=10, r=10, t=10, b=10), height=420)
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Colonne de statut non disponible dans les données.")

# ------------------------------------------------------------------
# TAB 2 — Score par enquêteur (coeur de l'application)
# ------------------------------------------------------------------
with tabs[1]:
    st.subheader("👤 Score de qualité par enquêteur")
    st.caption("Score composite (0–100) basé sur les indicateurs pondérés — voir réglages dans la barre latérale.")

    display_df = scores_df.copy()
    display_df["Grade"] = display_df["grade"].astype(str)

    col_table, col_detail = st.columns([1.4, 1])

    with col_table:
        st.dataframe(
            display_df[[
                "rang", "interviewer", "n_interviews", "score_qualite", "Grade",
                "taux_manquants", "taux_doublons", "taux_duree_anormale",
                "taux_anomalies_gps", "taux_aberrants", "taux_rejet",
            ]].rename(columns={
                "rang": "Rang", "interviewer": "Enquêteur", "n_interviews": "Nb. interviews",
                "score_qualite": "Score", "taux_manquants": "Manquants",
                "taux_doublons": "% Doublons", "taux_duree_anormale": "% Durée anormale",
                "taux_anomalies_gps": "% Anomalies GPS", "taux_aberrants": "Aberrants/erreurs",
                "taux_rejet": "% Rejetées",
            }),
            use_container_width=True, hide_index=True,
            column_config={
                "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f"),
                "Manquants": st.column_config.NumberColumn(format="%.1%", help="Taux réel si disponible, sinon classement relatif 0–1"),
                "% Doublons": st.column_config.NumberColumn(format="%.1%"),
                "% Durée anormale": st.column_config.NumberColumn(format="%.1%"),
                "% Anomalies GPS": st.column_config.NumberColumn(format="%.1%"),
                "Aberrants/erreurs": st.column_config.NumberColumn(format="%.1%", help="Classement relatif 0–1"),
                "% Rejetées": st.column_config.NumberColumn(format="%.1%"),
            },
        )

    with col_detail:
        selected_interviewer = st.selectbox("Voir le détail d'un enquêteur", scores_df["interviewer"].tolist())
        row = scores_df[scores_df["interviewer"] == selected_interviewer].iloc[0]

        st.markdown(
            f"**{selected_interviewer}** — Score : **{row['score_qualite']:.1f}/100** "
            + grade_badge(str(row["grade"])),
            unsafe_allow_html=True,
        )

        radar_categories = ["Manquants", "Doublons", "Durée anormale", "Anomalies GPS", "Aberrants/erreurs", "Rejet"]
        radar_values = [
            row["taux_manquants"] * 100, row["taux_doublons"] * 100, row["taux_duree_anormale"] * 100,
            row["taux_anomalies_gps"] * 100, row["taux_aberrants"] * 100, row["taux_rejet"] * 100,
        ]
        fig_radar = go.Figure()
        fig_radar.add_trace(go.Scatterpolar(
            r=radar_values + [radar_values[0]],
            theta=radar_categories + [radar_categories[0]],
            fill="toself", line_color="#F87171", name=selected_interviewer,
        ))
        fig_radar.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, max(20, max(radar_values) * 1.2)],
                                        gridcolor="rgba(255,255,255,0.15)"),
                       bgcolor="rgba(0,0,0,0)"),
            paper_bgcolor="rgba(0,0,0,0)", font_color="#FAFAFA",
            showlegend=False, margin=dict(l=30, r=30, t=20, b=20), height=340,
        )
        st.plotly_chart(fig_radar, use_container_width=True)
        st.caption("Chaque axe représente un taux d'anomalie (%) — plus la surface est petite, meilleure est la qualité.")

# ------------------------------------------------------------------
# TAB 3 — Valeurs manquantes
# ------------------------------------------------------------------
with tabs[2]:
    st.subheader("❌ Analyse des valeurs manquantes")
    if "missing_rate" in df.columns and df["missing_rate"].notna().any():
        fig3 = px.box(df, x="interviewer", y="missing_rate", points="all",
                      color_discrete_sequence=["#2E86AB"])
        fig3.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           font_color="#FAFAFA", yaxis_tickformat=".0%", height=450,
                           xaxis_title="Enquêteur", yaxis_title="Taux de valeurs manquantes")
        st.plotly_chart(fig3, use_container_width=True)
    elif "n_missing_raw" in df.columns and df["n_missing_raw"].notna().any():
        fig3b = px.box(df, x="interviewer", y="n_missing_raw", points="all",
                       color_discrete_sequence=["#2E86AB"])
        fig3b.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                            font_color="#FAFAFA", height=450,
                            xaxis_title="Enquêteur", yaxis_title="Nb. de questions sans réponse (par interview)")
        st.plotly_chart(fig3b, use_container_width=True)
        st.caption("Compte brut renvoyé par l'API (pas de total de questions disponible pour calculer un pourcentage).")
    else:
        st.warning("Les colonnes de comptage des réponses/manquants ne sont pas présentes dans ce jeu de données.")

# ------------------------------------------------------------------
# TAB 4 — Doublons & aberrants
# ------------------------------------------------------------------
with tabs[3]:
    st.subheader("🔁 Doublons détectés")
    if "is_duplicate" in df.columns:
        dup_df = df[df["is_duplicate"]]
        st.metric("Interviews potentiellement dupliquées", len(dup_df))
        if not dup_df.empty:
            st.dataframe(dup_df, use_container_width=True, hide_index=True)
    st.divider()
    st.subheader("⚠️ Valeurs aberrantes / erreurs de validation")
    if "n_outliers" in df.columns:
        outlier_summary = df.groupby("interviewer")["n_outliers"].sum().sort_values(ascending=False).reset_index()
        fig4 = px.bar(outlier_summary, x="interviewer", y="n_outliers", color_discrete_sequence=["#FCD34D"])
        fig4.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           font_color="#FAFAFA", height=400, xaxis_title="Enquêteur", yaxis_title="Nb. valeurs aberrantes / erreurs")
        st.plotly_chart(fig4, use_container_width=True)

# ------------------------------------------------------------------
# TAB 5 — Durée des interviews
# ------------------------------------------------------------------
with tabs[4]:
    st.subheader("⏱️ Durée des interviews")
    if "duration_minutes" in df.columns and df["duration_minutes"].notna().any():
        fig5 = px.violin(df, x="interviewer", y="duration_minutes", box=True, points=False,
                         color_discrete_sequence=["#60A5FA"])
        fig5.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           font_color="#FAFAFA", height=450, xaxis_title="Enquêteur", yaxis_title="Durée (minutes)")
        st.plotly_chart(fig5, use_container_width=True)

        flag_counts = df.groupby(["interviewer", "duration_flag"]).size().reset_index(name="count")
        fig6 = px.bar(flag_counts, x="interviewer", y="count", color="duration_flag", barmode="stack",
                     color_discrete_map={"normale": "#4ADE80", "trop_courte": "#F87171", "trop_longue": "#FCD34D", "inconnue": "#6B7280"})
        fig6.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           font_color="#FAFAFA", height=380, xaxis_title="Enquêteur", yaxis_title="Nb. interviews")
        st.plotly_chart(fig6, use_container_width=True)
    else:
        st.warning(
            "La durée d'interview n'est pas disponible via la connexion API standard "
            "(elle nécessite un export paradata avancé). Importez un export tabulaire "
            "détaillé ou un fichier CSV/Excel contenant une colonne de durée pour "
            "activer cette analyse."
        )

# ------------------------------------------------------------------
# TAB 6 — GPS
# ------------------------------------------------------------------
with tabs[5]:
    st.subheader("📍 Localisation des interviews")
    if "latitude" in df.columns and "longitude" in df.columns and df["latitude"].notna().any():
        map_df = df.dropna(subset=["latitude", "longitude"])
        fig7 = px.scatter_mapbox(
            map_df, lat="latitude", lon="longitude", color="gps_flag" if "gps_flag" in map_df.columns else None,
            hover_name="interviewer" if "interviewer" in map_df.columns else None,
            zoom=9, height=520,
            color_discrete_map={"ok": "#4ADE80", "manquant": "#6B7280", "points_suspects_identiques": "#F87171"},
        )
        fig7.update_layout(mapbox_style="carto-darkmatter", paper_bgcolor="rgba(0,0,0,0)",
                           font_color="#FAFAFA", margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig7, use_container_width=True)
    else:
        st.warning(
            "Les coordonnées GPS ne sont pas disponibles via la connexion API standard. "
            "Elles proviennent d'une variable GPS dans le questionnaire, exportable via "
            "l'export tabulaire (onglet avancé) ou un fichier CSV/Excel dédié."
        )

# ------------------------------------------------------------------
# TAB 7 — Export
# ------------------------------------------------------------------
with tabs[6]:
    st.subheader("📥 Export des résultats")
    st.write("Téléchargez le tableau des scores par enquêteur ou le jeu de données enrichi (indicateurs qualité inclus).")

    csv_scores = scores_df.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Télécharger les scores par enquêteur (CSV)", csv_scores,
                       file_name="scores_enqueteurs.csv", mime="text/csv", type="primary")

    csv_full = df.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Télécharger le jeu de données enrichi (CSV)", csv_full,
                       file_name="donnees_qualite_enrichies.csv", mime="text/csv")
