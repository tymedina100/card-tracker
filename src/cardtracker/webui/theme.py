"""Visual theme for the dashboard: a restrained, high-end financial aesthetic.

Everything here is presentation only. It injects one global stylesheet and
provides small helpers (branded sidebar, consistent page headers) so every view
shares the same typography, spacing, and surface treatment. No business logic
lives in this module.
"""

import streamlit as st

# Palette. Deep navy surfaces with a single champagne-gold accent, tuned for a
# premium, understated look rather than the default bright Streamlit chrome.
INK = "#0a0e16"          # app background
SURFACE = "#111a29"      # cards, sidebar
SURFACE_2 = "#16223a"    # raised elements, inputs
BORDER = "#243247"       # hairline borders
BORDER_SOFT = "#1c2842"
TEXT = "#e9eef6"         # primary text
MUTED = "#8695ab"        # secondary text
GOLD = "#d3a84c"         # accent
GOLD_SOFT = "#e6c877"    # accent hover / highlight
POS = "#3ecb7a"          # gains
NEG = "#e5605a"          # losses

_GLOBAL_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Fraunces:opsz,wght@9..144,500;9..144,600&display=swap');

:root {{
  --ct-ink: {INK};
  --ct-surface: {SURFACE};
  --ct-surface-2: {SURFACE_2};
  --ct-border: {BORDER};
  --ct-text: {TEXT};
  --ct-muted: {MUTED};
  --ct-gold: {GOLD};
  --ct-gold-soft: {GOLD_SOFT};
}}

/* ---- Base typography & canvas ------------------------------------------ */
html, body, [class*="css"], .stMarkdown, .stApp {{
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  -webkit-font-smoothing: antialiased;
}}
.stApp {{
  background:
    radial-gradient(1200px 600px at 85% -10%, rgba(211,168,76,0.06), transparent 60%),
    {INK};
  color: {TEXT};
}}
[data-testid="stAppViewContainer"] {{ color: {TEXT}; }}

/* Roomier main content column */
.block-container {{ padding-top: 2.4rem; padding-bottom: 4rem; max-width: 1180px; }}

/* Kill the default top ribbon so the app reads like a product, not a script */
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stToolbar"] {{ right: 0.75rem; }}

h1, h2, h3 {{ letter-spacing: -0.01em; }}

/* ---- Page header helper ------------------------------------------------- */
.ct-page-header {{ margin: 0 0 1.6rem 0; }}
.ct-kicker {{
  display: inline-block;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: {GOLD};
  margin-bottom: 0.35rem;
}}
.ct-page-title {{
  font-family: 'Fraunces', Georgia, serif !important;
  font-size: 2.15rem !important;
  font-weight: 600 !important;
  line-height: 1.1;
  color: {TEXT};
  margin: 0;
  padding: 0;
}}
/* Streamlit adds an anchor link to markdown headings; hide it on our headers */
.ct-page-title + a, .ct-page-header a[href^="#"] {{ display: none !important; }}
.ct-page-sub {{
  color: {MUTED};
  font-size: 0.98rem;
  margin: 0.45rem 0 0 0;
  max-width: 60ch;
}}
.ct-rule {{
  height: 2px; width: 46px; margin-top: 0.9rem;
  background: linear-gradient(90deg, {GOLD}, rgba(211,168,76,0));
  border-radius: 2px;
}}

/* ---- Sidebar ------------------------------------------------------------ */
[data-testid="stSidebar"] {{
  background: {SURFACE};
  border-right: 1px solid {BORDER_SOFT};
}}
[data-testid="stSidebar"] .block-container {{ padding-top: 1.4rem; }}

.ct-brand {{
  display: flex; align-items: center; gap: 0.7rem;
  padding: 0.2rem 0.2rem 1.1rem 0.2rem;
  border-bottom: 1px solid {BORDER_SOFT};
  margin-bottom: 1.1rem;
}}
.ct-brand-mark {{
  display: grid; place-items: center;
  width: 42px; height: 42px; border-radius: 11px;
  background: linear-gradient(145deg, {GOLD}, #a9812f);
  color: {INK}; font-family: 'Fraunces', serif; font-weight: 600;
  font-size: 1.15rem; letter-spacing: -0.02em;
  box-shadow: 0 6px 18px rgba(211,168,76,0.22);
}}
.ct-brand-name {{
  font-weight: 600; font-size: 1.02rem; color: {TEXT}; line-height: 1.1;
}}
.ct-brand-tag {{
  font-size: 0.7rem; letter-spacing: 0.14em; text-transform: uppercase;
  color: {MUTED}; margin-top: 2px;
}}
.ct-nav-label {{
  font-size: 0.68rem; letter-spacing: 0.16em; text-transform: uppercase;
  color: {MUTED}; margin: 0.2rem 0 0.5rem 0.2rem;
}}

/* Turn the sidebar radio into a real navigation list */
[data-testid="stSidebar"] [role="radiogroup"] {{ gap: 2px; }}
[data-testid="stSidebar"] [role="radiogroup"] label {{
  display: flex; align-items: center;
  padding: 0.5rem 0.7rem; margin: 0; border-radius: 9px;
  color: {MUTED}; font-weight: 500; font-size: 0.95rem;
  cursor: pointer; transition: background 0.15s ease, color 0.15s ease;
}}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {{
  background: {SURFACE_2}; color: {TEXT};
}}
/* Hide the actual radio dot; the whole row is the target */
[data-testid="stSidebar"] [role="radiogroup"] label > div:first-child {{ display: none; }}
/* Active item */
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
  background: linear-gradient(90deg, rgba(211,168,76,0.16), rgba(211,168,76,0.03));
  color: {TEXT};
  box-shadow: inset 2px 0 0 {GOLD};
}}

/* ---- Metric cards ------------------------------------------------------- */
[data-testid="stMetric"] {{
  background: linear-gradient(180deg, {SURFACE}, {INK});
  border: 1px solid {BORDER};
  border-radius: 14px;
  padding: 1.05rem 1.15rem;
}}
[data-testid="stMetricLabel"] {{
  color: {MUTED}; font-size: 0.78rem; font-weight: 500;
  letter-spacing: 0.04em; text-transform: uppercase;
}}
[data-testid="stMetricValue"] {{
  color: {TEXT}; font-weight: 600; font-size: 1.7rem;
  font-feature-settings: "tnum"; letter-spacing: -0.01em;
}}

/* Bordered containers (used across pages) get the same card treatment */
[data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"] {{
  gap: 0.6rem;
}}
[data-testid="stExpander"] {{
  border: 1px solid {BORDER} !important;
  border-radius: 12px !important;
  background: {SURFACE};
}}

/* ---- Buttons ------------------------------------------------------------ */
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {{
  border-radius: 10px;
  font-weight: 600;
  border: 1px solid {BORDER};
  transition: transform 0.05s ease, box-shadow 0.15s ease, background 0.15s ease;
}}
.stButton > button[kind="primary"],
[data-testid="stFormSubmitButton"] > button[kind="primary"] {{
  background: linear-gradient(180deg, {GOLD_SOFT}, {GOLD});
  color: {INK}; border: none;
  box-shadow: 0 6px 16px rgba(211,168,76,0.20);
}}
.stButton > button[kind="primary"]:hover,
[data-testid="stFormSubmitButton"] > button[kind="primary"]:hover {{
  box-shadow: 0 8px 22px rgba(211,168,76,0.30);
  transform: translateY(-1px);
}}
.stButton > button:hover {{ border-color: {GOLD}; color: {TEXT}; }}

/* ---- Tabs --------------------------------------------------------------- */
[data-testid="stTabs"] [data-baseweb="tab-list"] {{
  gap: 0.4rem; border-bottom: 1px solid {BORDER_SOFT};
}}
[data-testid="stTabs"] [data-baseweb="tab"] {{
  color: {MUTED}; font-weight: 500;
}}
[data-testid="stTabs"] [aria-selected="true"] {{ color: {TEXT}; }}
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {{ background: {GOLD}; }}

/* ---- Inputs ------------------------------------------------------------- */
[data-baseweb="input"], [data-baseweb="select"] > div, .stNumberInput div[data-baseweb="input"] {{
  border-radius: 9px !important;
}}
[data-testid="stWidgetLabel"] p {{ color: {MUTED}; font-weight: 500; font-size: 0.85rem; }}

/* ---- Tables ------------------------------------------------------------- */
[data-testid="stDataFrame"] {{
  border: 1px solid {BORDER}; border-radius: 12px; overflow: hidden;
}}

/* ---- Section subheaders ------------------------------------------------- */
[data-testid="stHeading"] h2, [data-testid="stHeading"] h3 {{
  font-family: 'Inter', sans-serif; font-weight: 600;
}}
hr {{ border-color: {BORDER_SOFT}; }}

/* Caption tone */
[data-testid="stCaptionContainer"], .stCaption {{ color: {MUTED}; }}

/* ---- Landing / hero ----------------------------------------------------- */
.ct-hero {{ padding: 1.5rem 0 1.2rem 0; }}
.ct-hero-mark {{ width: 54px; height: 54px; border-radius: 14px; font-size: 1.5rem;
  margin-bottom: 1.1rem; }}
.ct-hero-title {{
  font-family: 'Fraunces', Georgia, serif !important; font-weight: 600 !important;
  font-size: 3rem !important; line-height: 1.05; margin: 0.3rem 0 0 0; color: {TEXT};
}}
.ct-hero-sub {{ color: {MUTED}; font-size: 1.1rem; max-width: 62ch;
  margin: 0.8rem 0 1.6rem 0; line-height: 1.55; }}
.ct-feature {{
  border: 1px solid {BORDER}; border-top: 2px solid {GOLD};
  border-radius: 12px; padding: 1.1rem 1.15rem; height: 100%;
  background: linear-gradient(180deg, {SURFACE}, {INK});
}}
.ct-feature-head {{ font-weight: 600; color: {TEXT}; margin-bottom: 0.35rem; }}
.ct-feature-body {{ color: {MUTED}; font-size: 0.92rem; line-height: 1.5; }}
</style>
"""


def inject_global_style() -> None:
    """Apply the app-wide stylesheet. Safe to call on every rerun."""
    st.markdown(_GLOBAL_CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str | None = None,
                kicker: str = "Card Tracker") -> None:
    """Render a consistent, branded page header in place of a bare st.title."""
    sub = f'<p class="ct-page-sub">{subtitle}</p>' if subtitle else ""
    st.markdown(
        f'<div class="ct-page-header">'
        f'<span class="ct-kicker">{kicker}</span>'
        f'<h1 class="ct-page-title">{title}</h1>'
        f'{sub}'
        f'<div class="ct-rule"></div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def sidebar_brand() -> None:
    """Render the brand lockup at the top of the sidebar."""
    st.sidebar.markdown(
        '<div class="ct-brand">'
        '<div class="ct-brand-mark">CT</div>'
        '<div><div class="ct-brand-name">Card Tracker</div>'
        '<div class="ct-brand-tag">Collector Intelligence</div></div>'
        '</div>'
        '<div class="ct-nav-label">Navigation</div>',
        unsafe_allow_html=True,
    )
