"""Dashboard del nowcast del PIL italiano. Avvio: streamlit run app/streamlit_app.py"""

from __future__ import annotations

import streamlit as st

from nowcast.dashboard import pages

st.set_page_config(page_title="Nowcast PIL Italia", layout="wide")
st.navigation(
    [
        st.Page(pages.page_current, title="Stima corrente", url_path="stima", default=True),
        st.Page(pages.page_history, title="Storico", url_path="storico"),
        st.Page(pages.page_comparison, title="Confronto tra modelli", url_path="confronto"),
        st.Page(pages.page_method, title="Metodo e limiti", url_path="metodo"),
    ]
).run()
