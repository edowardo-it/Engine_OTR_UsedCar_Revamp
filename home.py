from pathlib import Path
from io import StringIO
import csv

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Pricing - Beranda", page_icon="🚗", layout="wide", initial_sidebar_state="expanded")

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

MASTER_DATA_FILE = Path(__file__).with_name("Master_Live.csv")
AUCTION_DATA_FILE = Path(__file__).with_name("Lelang_Live.csv")
PRICE_COLUMNS = {
    "OLX": "price_olx",
    "CSU": "price_csu",
    "KKB ATT": "price_kkb_att",
    "KKB Current": "price_kkb_curr",
    "Lelang": "price_lelang",
}
UNIT_COLUMNS = {
    "OLX": "units_olx",
    "CSU": "units_csu",
    "KKB ATT": "units_kkb_att",
    "KKB Current": "units_kkb_curr",
    "Lelang": "units_lelang",
}

st.markdown("""
<style>
.block-container {padding-top: 1.6rem; padding-bottom: 3rem;}
[data-testid="stSidebar"] {border-right: 1px solid rgba(128, 128, 128, .28);}
.page-title {font-size: 2rem; font-weight: 700; margin-bottom: .15rem;}
.page-subtitle {color: var(--text-color); opacity: .72; margin-bottom: 1.4rem;}
div[data-testid="stMetric"] {
    border: 1px solid rgba(128, 128, 128, .28);
    border-radius: 12px;
    padding: .75rem .9rem;
    background: var(--secondary-background-color);
    color: var(--text-color);
}
div[data-testid="stMetric"] [data-testid="stMetricLabel"],
div[data-testid="stMetric"] [data-testid="stMetricValue"] {
    color: var(--text-color);
}
</style>
""", unsafe_allow_html=True)



def robust_read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except UnicodeDecodeError:
        try:
            return pd.read_csv(
                path,
                encoding="utf-8-sig",
                engine="python",
                on_bad_lines="skip",
            )
        except Exception:
            with path.open("rb") as file:
                content = file.read().decode("utf-8", errors="replace")
            return pd.read_csv(StringIO(content))


@st.cache_data(show_spinner=False)
def load_master_data() -> pd.DataFrame:
    if not MASTER_DATA_FILE.exists():
        raise FileNotFoundError(
            "Master_Live.csv tidak ditemukan di folder aplikasi."
        )

    df = robust_read_csv(MASTER_DATA_FILE)
    for col in ["Brand", "Model", "Transmission", "main_type", "type_tags"]:
        if col in df.columns:
            df[col] = df[col].astype("string").str.strip().replace("", pd.NA)
    for col in ["Year", "CC_Norm", *PRICE_COLUMNS.values(), *UNIT_COLUMNS.values()]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def read_lelang_live_csv(file_path: Path) -> tuple[pd.DataFrame, int]:
    """Baca Lelang_Live.csv dengan delimiter titik koma."""
    if not file_path.exists():
        raise FileNotFoundError(
            "Lelang_Live.csv tidak ditemukan di folder aplikasi."
        )

    rows = []
    skipped_rows = 0
    with file_path.open(
        "r", encoding="utf-8-sig", errors="replace", newline=""
    ) as file:
        header_line = file.readline().rstrip("\r\n")
        if not header_line:
            raise ValueError("Lelang_Live.csv kosong.")

        header = next(csv.reader([header_line], delimiter=";"))
        expected_columns = len(header)
        for line in file:
            raw = line.rstrip("\r\n")
            if not raw.strip():
                continue
            if raw.startswith('"') and raw.endswith('"'):
                raw = raw[1:-1].replace('""', '"')

            try:
                parsed = next(csv.reader([raw], delimiter=";"))
            except csv.Error:
                skipped_rows += 1
                continue

            if len(parsed) != expected_columns:
                skipped_rows += 1
                continue
            rows.append(parsed)

    return pd.DataFrame(rows, columns=header), skipped_rows


@st.cache_data(show_spinner=False)
def load_auction_data() -> tuple[pd.DataFrame, int]:
    df, skipped_rows = read_lelang_live_csv(AUCTION_DATA_FILE)
    df.columns = df.columns.astype(str).str.strip()

    required_columns = ["Brand_Norm", "Model_Norm", "Tahun"]
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(
            "Kolom wajib Lelang_Live.csv tidak ditemukan: "
            + ", ".join(missing_columns)
        )

    for col in ["Brand_Norm", "Model_Norm"]:
        df[col] = df[col].astype("string").str.strip().replace("", pd.NA)
    df["Tahun"] = pd.to_numeric(df["Tahun"], errors="coerce")
    return df, skipped_rows


def compact_money(value) -> str:
    if pd.isna(value):
        return "-"
    value = float(value)
    sign = "-" if value < 0 else ""
    n = abs(value)
    if n >= 1_000_000_000_000:
        scaled, unit, decimals = n / 1_000_000_000_000, "triliun", 2
    elif n >= 1_000_000_000:
        scaled, unit, decimals = n / 1_000_000_000, "miliar", 2 if n < 10_000_000_000 else 1
    elif n >= 1_000_000:
        scaled, unit, decimals = n / 1_000_000, "jt", 2 if n < 100_000_000 else 1
    elif n >= 1_000:
        scaled, unit, decimals = n / 1_000, "rb", 1
    else:
        return f"{sign}{n:,.0f}".replace(",", ".")
    text = f"{scaled:.{decimals}f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{sign}{text} {unit}"


def format_number(value) -> str:
    if pd.isna(value):
        return "-"
    return f"{value:,.0f}".replace(",", ".")


def price_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for source, price_col in PRICE_COLUMNS.items():
        unit_col = UNIT_COLUMNS[source]
        prices = df[price_col].dropna()
        prices = prices[prices > 0]
        if prices.empty:
            continue
        rows.append({
            "Sumber": source,
            "Median Harga": prices.median(),
            "Rata-rata Harga": prices.mean(),
            "Harga Minimum": prices.min(),
            "Harga Maximum": prices.max(),
            "Total Unit": df[unit_col].fillna(0).sum(),
        })
    return pd.DataFrame(rows)


def render_data_summary(
    dataframe: pd.DataFrame,
    source_name: str,
    brand_column: str,
    model_column: str,
    year_column: str,
    chart_key: str,
) -> None:
    """Render KPI dan chart untuk satu sumber tanpa mencampur data sumber lain."""
    st.markdown(f"### Ringkasan {source_name}")

    kpi_1, kpi_2, kpi_3 = st.columns(3)
    kpi_1.metric(f"Total data {source_name}", format_number(len(dataframe)))
    kpi_2.metric(
        f"Jumlah merk {source_name}",
        format_number(dataframe[brand_column].nunique(dropna=True)),
    )
    kpi_3.metric(
        f"Jumlah model {source_name}",
        format_number(dataframe[model_column].nunique(dropna=True)),
    )

    chart_1, chart_2 = st.columns(2)
    with chart_1:
        brand_count = (
            dataframe.dropna(subset=[brand_column])
            .groupby(brand_column, as_index=False)
            .size()
            .rename(columns={brand_column: "Brand", "size": "Jumlah"})
            .sort_values("Jumlah", ascending=False)
            .head(10)
        )
        brand_chart = px.bar(
            brand_count.sort_values("Jumlah"),
            x="Jumlah",
            y="Brand",
            orientation="h",
            title=f"Top 10 merk pada {source_name}",
        )
        st.plotly_chart(
            brand_chart,
            width="stretch",
            key=f"brand_chart_{chart_key}",
        )

    with chart_2:
        valid_years = dataframe[dataframe[year_column].between(1900, 2100)]
        year_count = (
            valid_years.groupby(year_column, as_index=False)
            .size()
            .rename(columns={year_column: "Tahun", "size": "Jumlah"})
            .sort_values("Tahun")
        )
        year_chart = px.line(
            year_count,
            x="Tahun",
            y="Jumlah",
            markers=True,
            title=f"Distribusi record {source_name} berdasarkan tahun",
        )
        st.plotly_chart(
            year_chart,
            width="stretch",
            key=f"year_chart_{chart_key}",
        )



try:
    master_df = load_master_data()
    auction_df, skipped_auction_rows = load_auction_data()
except Exception as exc:
    st.error(str(exc))
    st.stop()

st.markdown('<div class="page-title">Beranda</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="page-subtitle">Ringkasan untuk masing-masing Engine OTR Used Car dan Engine Lelang.</div>',
    unsafe_allow_html=True,
)

# st.markdown("### Ringkasan Sumber Harga")
# summary = price_summary(master_df)
# if not summary.empty:
#     display = summary.copy()
#     for col in ["Median Harga", "Rata-rata Harga", "Harga Minimum", "Harga Maximum"]:
#         display[col] = display[col].apply(compact_money)
#     display["Total Unit"] = display["Total Unit"].apply(format_number)
#     st.dataframe(display, hide_index=True)

render_data_summary(
    master_df,
    source_name="Engine OTR Used Car",
    brand_column="Brand",
    model_column="Model",
    year_column="Year",
    chart_key="master_live",
)

st.divider()

render_data_summary(
    auction_df,
    source_name="Engine Lelang",
    brand_column="Brand_Norm",
    model_column="Model_Norm",
    year_column="Tahun",
    chart_key="lelang_live",
)

if skipped_auction_rows > 0:
    st.warning(
        f"{format_number(skipped_auction_rows)} baris Engine Lelang "
        "tidak dapat diparsing dan dilewati."
    )

st.markdown("### Cara Menggunakan")
st.info("Gunakan **Engine OTR Used Car** untuk benchmark harga pasar used car, **Engine Lelang** untuk rekomendasi harga lelang based on Data Aplikasi Lelang, IBID dan JBA. Menu **Feedback** untuk mencatat evaluasi pengguna.")
