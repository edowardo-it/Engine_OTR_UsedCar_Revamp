from datetime import datetime
from pathlib import Path
from io import StringIO

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Pricing - Feedback", page_icon="💬", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
    <style>
    h1 {
        padding-bottom: 1px !important;
        margin-bottom: 0.5rem !important;
        line-height: 1.25 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = BASE_DIR / "Master_Live.csv"
FEEDBACK_FILE = BASE_DIR / "feedback.csv"

st.markdown("""
<style>
.block-container {padding-top: 1.6rem; padding-bottom: 3rem;}
[data-testid="stSidebar"] {border-right: 1px solid rgba(128, 128, 128, .28);}
.page-title {font-size: 2rem; font-weight: 700; margin-bottom: .15rem;}
.page-subtitle {color: var(--text-color); opacity: .72; margin-bottom: 1.4rem;}
</style>
""", unsafe_allow_html=True)



@st.cache_data(show_spinner=False)
def load_data():
    if not DATA_FILE.exists():
        raise FileNotFoundError("Master.csv tidak ditemukan pada folder utama aplikasi.")
    def robust_read_csv(path):
        try:
            return pd.read_csv(path)
        except UnicodeDecodeError:
            try:
                return pd.read_csv(path, encoding="utf-8-sig", engine="python", on_bad_lines='skip')
            except Exception:
                with open(path, "rb") as f:
                    content = f.read().decode("utf-8", errors="replace")
                return pd.read_csv(StringIO(content))

    df = robust_read_csv(DATA_FILE)
    for col in ["Brand", "Model"]:
        if col in df.columns:
            df[col] = df[col].astype("string").str.strip()
    return df


def sorted_text(series):
    return sorted(series.dropna().astype(str).unique().tolist())


try:
    df = load_data()
except Exception as exc:
    st.error(str(exc)); st.stop()

st.markdown('<div class="page-title">Feedback</div>', unsafe_allow_html=True)
st.markdown('<div class="page-subtitle">Catat evaluasi pengguna terhadap hasil pricing engine sebagai bahan kalibrasi berikutnya.</div>', unsafe_allow_html=True)

with st.form("feedback_form", clear_on_submit=True):
    c1, c2 = st.columns(2)
    with c1:
        # engine = st.selectbox("Engine", ["Engine OTR", "Engine Lelang"])
        # brand = st.selectbox("Merk", ["-"] + sorted_text(df["Brand"]))
        rating = st.slider("Rating hasil", min_value=1, max_value=10, value=8)
    with c2:
        # model_options = ["-"] + sorted_text(df[df["Brand"] == brand]["Model"]) if brand != "-" else ["-"]
        # model = st.selectbox("Model", model_options)
        category = st.selectbox("Kategori Feedback", ["Harga terlalu tinggi", "Harga terlalu rendah", "Harga sudah sesuai", "Data kurang lengkap", "UI / UX", "Lainnya"])
    comment = st.text_area("Komentar", placeholder="Tuliskan detail feedback, contoh kasus, atau hasil observasi lapangan.", height=140)
    submitted = st.form_submit_button("Simpan Feedback", width="stretch")

if submitted:
    row = pd.DataFrame([{
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        # "engine": engine,
        # "brand": brand,
        # "model": model,
        "rating": rating,
        "category": category,
        "comment": comment,
    }])
    try:
        if FEEDBACK_FILE.exists():
            # read feedback file robustly to avoid decode errors
            def robust_read_csv(path):
                try:
                    return pd.read_csv(path)
                except UnicodeDecodeError:
                    try:
                        return pd.read_csv(path, encoding="utf-8-sig", engine="python", on_bad_lines='skip')
                    except Exception:
                        with open(path, "rb") as f:
                            content = f.read().decode("utf-8", errors="replace")
                        return pd.read_csv(StringIO(content))

            existing = robust_read_csv(FEEDBACK_FILE)
            row = pd.concat([existing, row], ignore_index=True)
        row.to_csv(FEEDBACK_FILE, index=False)
        st.success("Feedback berhasil disimpan ke feedback.csv.")
    except Exception as exc:
        st.error(f"Feedback belum dapat disimpan: {exc}")

st.markdown("### Feedback Terbaru")
if FEEDBACK_FILE.exists():
    try:
        def robust_read_csv(path):
            try:
                return pd.read_csv(path)
            except UnicodeDecodeError:
                try:
                    return pd.read_csv(path, encoding="utf-8-sig", engine="python", on_bad_lines='skip')
                except Exception:
                    with open(path, "rb") as f:
                        content = f.read().decode("utf-8", errors="replace")
                    return pd.read_csv(StringIO(content))

        feedback_df = robust_read_csv(FEEDBACK_FILE)
        st.dataframe(
            feedback_df.sort_values("timestamp", ascending=False).head(20),
            width="stretch",
            hide_index=True,
        )
    except Exception as exc:
        st.warning(f"Gagal membaca feedback.csv: {exc}")
else:
    st.info("Belum ada feedback yang tersimpan.")
