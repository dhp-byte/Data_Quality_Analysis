"""Styles CSS injectés dans l'application Streamlit."""

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');

html, body, [class*="css"]  {
    font-family: 'Inter', sans-serif;
}

/* En-tête */
.app-header {
    background: linear-gradient(135deg, #0F2027 0%, #203A43 45%, #2E86AB 100%);
    padding: 1.6rem 2rem;
    border-radius: 16px;
    margin-bottom: 1.4rem;
    border: 1px solid rgba(255,255,255,0.08);
}
.app-header h1 {
    color: #FFFFFF;
    font-size: 1.7rem;
    font-weight: 800;
    margin: 0;
}
.app-header p {
    color: #C9D6DF;
    margin: 0.3rem 0 0 0;
    font-size: 0.95rem;
}

/* Cartes KPI */
.kpi-card {
    background: #1B1F27;
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 14px;
    padding: 1.1rem 1.3rem;
    text-align: left;
}
.kpi-card .kpi-label {
    color: #9AA5B1;
    font-size: 0.8rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
}
.kpi-card .kpi-value {
    color: #FAFAFA;
    font-size: 1.9rem;
    font-weight: 800;
    margin-top: 0.2rem;
}
.kpi-card .kpi-delta-good { color: #4ADE80; font-size: 0.85rem; font-weight: 600; }
.kpi-card .kpi-delta-bad { color: #F87171; font-size: 0.85rem; font-weight: 600; }

/* Badge de grade */
.grade-badge {
    display: inline-block;
    padding: 0.15rem 0.6rem;
    border-radius: 999px;
    font-weight: 800;
    font-size: 0.85rem;
}
.grade-A { background: #14532D; color: #86EFAC; }
.grade-B { background: #1E3A5F; color: #93C5FD; }
.grade-C { background: #78350F; color: #FCD34D; }
.grade-D { background: #7C2D12; color: #FDBA74; }
.grade-E { background: #7F1D1D; color: #FCA5A5; }

section[data-testid="stSidebar"] {
    border-right: 1px solid rgba(255,255,255,0.06);
}
</style>
"""


def kpi_card(label: str, value: str, delta: str | None = None, good: bool = True) -> str:
    delta_html = ""
    if delta:
        cls = "kpi-delta-good" if good else "kpi-delta-bad"
        delta_html = f'<div class="{cls}">{delta}</div>'
    return f"""
    <div class="kpi-card">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
        {delta_html}
    </div>
    """


def grade_badge(grade: str) -> str:
    return f'<span class="grade-badge grade-{grade}">{grade}</span>'
