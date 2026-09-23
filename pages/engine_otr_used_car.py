from pathlib import Path
from io import StringIO
import json
import logging
from logging.handlers import RotatingFileHandler

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Pricing - Engine OTR", page_icon="🚘", layout="wide", initial_sidebar_state="expanded")

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
LELANG_DATA_FILE = BASE_DIR / "Lelang_Live.csv"
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "engine_otr_usedcar.log"
PRICE_COLUMNS = {"OLX": "price_olx", "CSU": "price_csu", "KKB ATT": "price_kkb_att", "KKB Current": "price_kkb_curr"}
#UNIT_COLUMNS = {"OLX": "units_olx", "CSU": "units_csu", "KKB ATT": "units_kkb_att", "KKB Current": "units_kkb_curr"}

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


# =========================================================
# FILTER LOGGING
# =========================================================
@st.cache_resource
def get_filter_logger():
    """Siapkan logger berotasi untuk aktivitas filter Engine OTR Used Car."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("engine_otr_used_car.filter")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    log_path = str(LOG_FILE.resolve())
    handler_exists = any(
        isinstance(handler, RotatingFileHandler)
        and handler.baseFilename == log_path
        for handler in logger.handlers
    )
    if not handler_exists:
        handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=5_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)

    return logger


def log_filter_result(parameters, result_count):
    """Catat parameter pilihan user dan jumlah hasil Engine OTR Used Car."""
    payload = {
        "event": "filter_applied",
        "parameters": parameters,
        "output_counts": {
            "master_live": int(result_count),
        },
    }
    get_filter_logger().info(
        json.dumps(payload, ensure_ascii=False, default=str)
    )



@st.cache_data(show_spinner=False)
def load_data() -> pd.DataFrame:
    if not DATA_FILE.exists():
        raise FileNotFoundError("Master_Live.csv tidak ditemukan pada folder utama aplikasi.")
    # robust CSV read to avoid UnicodeDecodeError on files with irregular encoding
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
    for col in ["Brand", "Model", "Transmission", "main_type", "type_tags"]:
        if col in df.columns:
            # normalize text fields and capitalize each word for Brand and others
            df[col] = df[col].astype("string").str.strip().str.title()
    for col in ["Year", "CC_Norm", *PRICE_COLUMNS.values()]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


@st.cache_data(show_spinner=False)
def load_lelang_data(file_path: Path, file_version: int | None) -> pd.DataFrame:
    """Muat data transaksi lelang dengan delimiter titik koma."""
    _ = file_version
    if not file_path.exists():
        raise FileNotFoundError(
            "Lelang_Live.csv tidak ditemukan pada folder utama aplikasi."
        )

    df = pd.read_csv(
        file_path,
        sep=";",
        encoding="utf-8-sig",
        low_memory=False,
    )
    df.columns = df.columns.astype(str).str.strip()

    required_columns = [
        "Brand_Norm",
        "Model_Norm",
        "Tahun",
        "main_type_Norm",
        "CC_Norm",
        "Transmission_Norm",
        "saleprice",
    ]
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(
            "Kolom wajib Lelang_Live.csv tidak ditemukan: "
            + ", ".join(missing_columns)
        )

    text_columns = [
        "Brand_Norm",
        "Model_Norm",
        "main_type_Norm",
        "type_tags_Norm",
        "Transmission_Norm",
        "KodeDaerah",
        "BalaiLelang",
        "lokasi",
        "grade_overrall_csis",
        "note_csis",
    ]
    for column in text_columns:
        if column in df.columns:
            df[column] = (
                df[column].astype("string").str.strip().replace("", pd.NA)
            )

    for column in ["Tahun", "CC_Norm", "saleprice", "kilometer1"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    if "SaleDate" in df.columns:
        df["SaleDate"] = pd.to_datetime(df["SaleDate"], errors="coerce")

    return df


def compact_money(value) -> str:
    if pd.isna(value): return "-"
    value = float(value); sign = "-" if value < 0 else ""; n = abs(value)
    if n >= 1_000_000_000_000: scaled, unit, decimals = n / 1_000_000_000_000, "triliun", 2
    elif n >= 1_000_000_000: scaled, unit, decimals = n / 1_000_000_000, "miliar", 2 if n < 10_000_000_000 else 1
    elif n >= 1_000_000: scaled, unit, decimals = n / 1_000_000, "jt", 2 if n < 100_000_000 else 1
    elif n >= 1_000: scaled, unit, decimals = n / 1_000, "rb", 1
    else: return f"{sign}{n:,.0f}".replace(",", ".")
    text = f"{scaled:.{decimals}f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{sign}{text} {unit}"


def sorted_text(series):
    s = series.dropna().astype(str).str.strip()
    s = s[s != ""]
    return sorted(s.unique().tolist())


def valid_years(df):
    return df.loc[df["Year"].between(1900, 2100), "Year"].dropna().astype(int).sort_values(ascending=False).unique().tolist()


def normalized_text(series):
    """Normalisasi teks untuk matching lintas Master_Live dan Lelang_Live."""
    return series.astype("string").str.strip().str.casefold()


def filter_lelang_by_params(lelang_df, params):
    """Terapkan parameter pilihan user ke data transaksi lelang."""
    result = lelang_df.copy()
    text_filters = [
        ("brand", "Semua Merk", "Brand_Norm"),
        ("model", "Semua Model", "Model_Norm"),
        ("main_type", "Semua Varian", "main_type_Norm"),
        ("transmission", "Semua Transmisi", "Transmission_Norm"),
    ]

    for parameter, all_label, column in text_filters:
        selected = params[parameter]
        if selected != all_label:
            result = result[
                normalized_text(result[column]) == str(selected).strip().casefold()
            ]

    if params["year"] != "Semua Tahun":
        result = result[result["Tahun"] == int(params["year"])]

    if params["cc"] != "Semua CC":
        result = result[(result["CC_Norm"] - float(params["cc"])).abs() < 0.001]

    return result.copy()


def build_lelang_display(lelang_df):
    """Siapkan kolom dan format tabel DATA LELANG."""
    display = lelang_df.copy()
    cc_text = display["CC_Norm"].apply(
        lambda value: "" if pd.isna(value) else f"{value:g}"
    )
    display["Vehicle"] = (
        display["Model_Norm"].fillna("").astype(str).str.title()
        + " "
        + cc_text
        + " "
        + display["main_type_Norm"].fillna("").astype(str).str.upper()
        + " "
        + display.get("type_tags_Norm", pd.Series("", index=display.index))
        .fillna("")
        .astype(str)
        .str.title()
    )
    display["Vehicle"] = (
        display["Vehicle"]
        .str.replace(r"\s+", " ", regex=True)
        .str.replace(",", " ", regex=False)
        .str.strip()
    )

    display["Brand_Norm"] = display["Brand_Norm"].astype("string").str.title()
    display["saleprice"] = display["saleprice"].apply(compact_money)
    if "SaleDate" in display.columns:
        display["SaleDate"] = display["SaleDate"].dt.strftime("%Y-%m-%d")
    if "kilometer1" in display.columns:
        display["kilometer1"] = display["kilometer1"].apply(
            lambda value: "-"
            if pd.isna(value)
            else f"{value:,.0f}".replace(",", ".")
        )
    if "grade_overrall_csis" in display.columns:
        display["grade_overrall_csis"] = (
            display["grade_overrall_csis"]
            .astype("string")
            .str.replace("_", " ", regex=False)
            .str.title()
        )

    columns = [
        "Brand_Norm",
        "Vehicle",
        "Tahun",
        "Transmission_Norm",
        "saleprice",
        "SaleDate",
        "kilometer1",
        "grade_overrall_csis",
        "BalaiLelang",
    ]
    display = display[[column for column in columns if column in display.columns]]
    return display.rename(
        columns={
            "Brand_Norm": "Brand",
            "Vehicle": "Model / Tipe",
            "Tahun": "Tahun",
            "Transmission_Norm": "Transmisi",
            "saleprice": "Harga Lelang",
            "SaleDate": "Tanggal Lelang",
            "kilometer1": "Kilometer",
            "grade_overrall_csis": "Grade",
            "BalaiLelang": "Balai Lelang",
        }
    )


def vehicle_filter_panel(df):
    st.markdown("### Input Parameter Kendaraan")
    # interactive cascading selects (each dropdown depends on previous choice)
    c1, c2, c3 = st.columns(3)
    with c1:
        brand = st.selectbox("Merk", ["Semua Merk"] + sorted_text(df["Brand"]))
    d1 = df if brand == "Semua Merk" else df[df["Brand"] == brand]

    with c2:
        model = st.selectbox("Model", ["Semua Model"] + sorted_text(d1["Model"]))
    d2 = d1 if model == "Semua Model" else d1[d1["Model"] == model]

    with c3:
        year = st.selectbox("Tahun", ["Semua Tahun"] + valid_years(d2))
    d3 = d2 if year == "Semua Tahun" else d2[d2["Year"] == int(year)]

    c4, c5, c6 = st.columns(3)
    with c4:
        main_type = st.selectbox("Varian / Tipe", ["Semua Varian"] + sorted_text(d3["main_type"]))
    d4 = d3 if main_type == "Semua Varian" else d3[d3["main_type"] == main_type]

    # prefer CC_Norm column from CSV; fallback to CC if present
    cc_col = "CC_Norm" if "CC_Norm" in d4.columns else "CC"
    cc_values = d4[cc_col].dropna().sort_values().unique().tolist()
    with c5:
        cc = st.selectbox("CC", ["Semua CC"] + cc_values, format_func=lambda x: "Semua CC" if x == "Semua CC" else f"{x:g} L")
    d5 = d4 if cc == "Semua CC" else d4[d4[cc_col] == float(cc)]

    with c6:
        transmission = st.selectbox("Transmisi", ["Semua Transmisi"] + sorted_text(d5["Transmission"]))

    # submit button to apply the filters and trigger logging
    submitted = st.button("Terapkan Filter", type="primary")

    result = d5 if transmission == "Semua Transmisi" else d5[d5["Transmission"] == transmission]
    params = {
        "brand": brand,
        "model": model,
        "year": year,
        "main_type": main_type,
        "cc": cc,
        "transmission": transmission,
    }
    return result, params, submitted


# def build_summary(df, sources):
#     rows = []
#     for source in sources:
#         pcol= PRICE_COLUMNS[source]
#         prices = df[pcol].dropna(); prices = prices[prices > 0]
#         if prices.empty: continue
#         rows.append({"Sumber": source, "Median Harga": prices.median(), "Rata-rata Harga": prices.mean(), "Harga Minimum": prices.min(), "Harga Maximum": prices.max()})
#     return pd.DataFrame(rows)


try:
    df = load_data()
    lelang_file_version = (
        LELANG_DATA_FILE.stat().st_mtime_ns if LELANG_DATA_FILE.exists() else None
    )
    lelang_df = load_lelang_data(LELANG_DATA_FILE, lelang_file_version)
except Exception as exc:
    st.error(str(exc)); st.stop()

st.markdown('<div class="page-title">Engine OTR Used Car</div>', unsafe_allow_html=True)
st.markdown('<div class="page-subtitle">Analisis benchmark harga kendaraan berdasarkan data Financore, OLX, dan Lelang.</div>', unsafe_allow_html=True)

search_df = df.copy()

# get filtered dataframe and selected params from panel
filtered, params, submitted = vehicle_filter_panel(search_df)

if not submitted:
    st.info("Pilih parameter lalu klik 'Terapkan Filter' untuk melihat hasil analisa.")
    st.stop()

filtered_lelang = filter_lelang_by_params(lelang_df, params)

# exclude rows where Brand is missing/empty
if "Brand" in filtered.columns:
    filtered = filtered[filtered["Brand"].fillna("").astype(str).str.strip() != ""]
# exclude rows where Model is missing/empty
if "Model" in filtered.columns:
    filtered = filtered[filtered["Model"].fillna("").astype(str).str.strip() != ""]
# exclude rows where price_olx is 0
if "price_olx" in filtered.columns:
    filtered = filtered[filtered["price_olx"] != 0]

# Logging: write params + result_count when user submitted
try:
    log_filter_result(params, result_count=len(filtered))
except Exception as exc:
    st.error(f"Gagal menyimpan log: {exc}")

if filtered.empty:
    st.warning("Tidak ada data yang sesuai dengan parameter yang dipilih."); st.stop()

# Define function calculate min max avg
def generate_min_max_avg_prices(
    df: pd.DataFrame, olx_col: str, csu_col: str, lelang_col: str
) -> pd.DataFrame:
    """
    Take price data from OLX, CSU and Lelang to get Min, Max, Avg.

    inputs:
        df: Prices Dataframe.
        olx_col: olx price column name.
        csu_col: csu price column name.
        lelang_col: lelang price column name.

    output:
        df: Price DataFrame with min, max, avg columns.

    logic:
        avg =
            if olx: olx
            elif csu: csu * 0.8
            elif lelang * 1.1
        min =
            if lelang: lelang
            elif avg: avg * 0.9
        max = avg * 1.1
    """
    df = df.copy()

    # Masks to check available data
    has_olx = df[olx_col].notna() & (df[olx_col] > 0)
    has_csu = df[csu_col].notna() & (df[csu_col] > 0)
    has_lelang = df[lelang_col].notna() & (df[lelang_col] > 0)

    default_series = pd.Series(np.nan, index=df.index, dtype=float)

    # Calculate min, max, avg
    df["avg"] = default_series.case_when(
        [
            (has_olx, df[olx_col]),
            (has_csu, df[csu_col] * 0.8),
            (has_lelang, df[lelang_col] * 1.1),
        ]
    ).round()

    has_avg = df["avg"].notna() & (df["avg"] > 0)
    df["min"] = default_series.case_when(
        [
            (has_lelang, df[lelang_col]),
            (has_avg, df["avg"] * 0.9),
        ]
    ).round()

    df["max"] = (df["avg"] * 1.1).round()

    return df



sources = PRICE_COLUMNS.keys()

# summary = build_summary(filtered, sources)
all_prices = pd.concat([filtered[PRICE_COLUMNS[s]] for s in sources], ignore_index=True).dropna()
all_prices = all_prices[all_prices > 0]

# k1, k2, k3, k4 = st.columns(4)
# k1.metric("Median Benchmark", compact_money(all_prices.median() if not all_prices.empty else None))
# k2.metric("Rata-rata", compact_money(all_prices.mean() if not all_prices.empty else None))
# k3.metric("Harga Minimum", compact_money(all_prices.min() if not all_prices.empty else None))
# k4.metric("Harga Maximum", compact_money(all_prices.max() if not all_prices.empty else None))


# st.markdown("### Detail Data")            --uncomment untuk testing

# Make a display copy for both the main detail table and the renamed Information Data table

detail_display = filtered.copy()
information_display = filtered.copy()

# Ensure Brand column displays with uppercase initial on each word
for df_ in (detail_display, information_display):
    if "Brand" in df_.columns:
        df_["Brand"] = df_["Brand"].astype(str).str.title()



# =========================================================
# BUILD DISPLAY VEHICLE NAME
# Model + CC + main_type + type_tags
# =========================================================
# prefer CC_Norm from CSV if present
cc_col_display = "CC_Norm" if "CC_Norm" in detail_display.columns else "CC"
detail_display["Vehicle"] = (
    detail_display["Model"]
    .fillna("")
    .astype(str)
    .str.strip()
    .str.title()
    + " "
    + detail_display[cc_col_display]
    .apply(
        lambda x: (
            ""
            if pd.isna(x)
            else f"{x:g}"
        )
    )
    + " "
    + detail_display["main_type"]
    .fillna("")
    .astype(str)
    .str.strip()
    .str.upper()
    + " "
    + detail_display["type_tags"]
    .fillna("")
    .astype(str)
    .str.strip()
    .str.title()
)

# Bersihkan spasi berlebih
detail_display["Vehicle"] = (
    detail_display["Vehicle"]
    .str.replace(r"\s+", " ", regex=True)
    .str.replace(",", " ", regex=True)
    .str.strip()
)


#information display

information_display["Vehicle"] = (
    information_display["Model"]
    .fillna("")
    .astype(str)
    .str.strip()
    .str.title()
    + " "
    + information_display[cc_col_display]
    .apply(
        lambda x: (
            ""
            if pd.isna(x)
            else f"{x:g}"
        )
    )
    + " "
    + information_display["main_type"]
    .fillna("")
    .astype(str)
    .str.strip()
    .str.upper()
    + " "
    + information_display["type_tags"]
    .fillna("")
    .astype(str)
    .str.strip()
    .str.title()
)

# Bersihkan spasi berlebih
information_display["Vehicle"] = (
    information_display["Vehicle"]
    .str.replace(r"\s+", " ", regex=True)
    .str.replace(",", " ", regex=True)
    .str.strip()
)



# =========================================================
# FORMAT PRICE COLUMNS
# =========================================================
price_columns = [
    "price_olx",
    "price_csu",
    "price_kkb_att",
    "price_kkb_curr",
    "price_lelang"
]

for col in price_columns:
    if col in detail_display.columns:
        detail_display[col] = (
            detail_display[col]
            .apply(compact_money)
        )
        
#information display

price_columns = [
    "price_olx",
    "price_csu",
    "price_kkb_att",
    "price_kkb_curr",
    "price_lelang"
]

for col in price_columns:
    if col in information_display.columns:
        information_display[col] = (
            information_display[col]
            .apply(compact_money)
        )        


# =========================================================
# SELECT & ORDER COLUMNS
# =========================================================
detail_columns = [
    "Brand",             # kolom 1
    "Vehicle",           # kolom 2: Model + CC + Type
    "Year",              # kolom 3
    "Transmission",      # kolom 4
    "price_olx",         # kolom 5
    "price_csu",         # kolom 6
    "price_kkb_att",     # kolom 7
    "price_kkb_curr",    # kolom 8
    "price_lelang"
]

detail_display = detail_display[
    [
        col
        for col in detail_columns
        if col in detail_display.columns
    ]
]


#information display
information_columns = [
    "Brand",             # kolom 1
    "Vehicle",           # kolom 2: Model + CC + Type
    "Year",              # kolom 3
    "Transmission",      # kolom 4
    "min",               # kolom 5
    "avg",               # kolom 6
    "max",               # kolom 7
    "HargaBaru_ATT",     # kolom 8
    "HargaBaru_Curr",    # kolom 9
]

information_display = generate_min_max_avg_prices(
    filtered,
    "price_olx",
    "price_csu",
    "price_lelang"
)

# If `Vehicle` was built earlier on `detail_display`, bring it into `information_display`
# so the information table can show the composed Model / Tipe column.
if "Vehicle" not in information_display.columns and "Vehicle" in detail_display.columns:
    information_display["Vehicle"] = detail_display["Vehicle"]

if "price_kkb_att" in filtered.columns:
    information_display["HargaBaru_ATT"] = filtered.apply(
        lambda row: (
            row["price_kkb_att"]
            if pd.notna(row.get("price_kkb_att")) and row.get("price_kkb_att") != 0
            else pd.NA
        ),
        axis=1,
    )

if "price_kkb_curr" in filtered.columns:
    information_display["HargaBaru_Curr"] = filtered.apply(
        lambda row: (
            row["price_kkb_curr"]
            if pd.notna(row.get("price_kkb_curr")) and row.get("price_kkb_curr") != 0
            else pd.NA
        ),
        axis=1,
    )

information_display = information_display[
    [col for col in information_columns if col in information_display.columns]
]

for col in ["min", "avg", "max", "HargaBaru_ATT", "HargaBaru_Curr"]:
    if col in information_display.columns:
        information_display[col] = information_display[col].apply(
            lambda value: compact_money(value) if pd.notna(value) and value != 0 and value != '-' else '-'
        )


# =========================================================
# RENAME COLUMN FOR DISPLAY
# =========================================================
detail_display = detail_display.rename(
    columns={
        "Brand": "Brand",
        "Vehicle": "Model / Tipe",
        "Year": "Tahun",
        "Transmission": "Transmisi",
        "price_olx": "OLX",
        "price_csu": "CSU",
        "price_kkb_att": "KKB ATT",
        "price_kkb_curr": "KKB Current",
        "price_lelang": "Lelang",
    }
)

information_display = information_display.rename(
    columns={
        "Brand": "Brand",
        "Vehicle": "Model / Tipe",
        "Year": "Tahun",
        "Transmission": "Transmisi",
        "min": "Min",
        "avg": "Avg",
        "max": "Max",
        "HargaBaru_ATT": "Harga Baru ATT",
        "HargaBaru_Curr": "Harga Baru Current",
        "price_csu": "CSU",
        "price_kkb_att": "KKB ATT",
        "price_kkb_curr": "KKB Current",
        "price_lelang": "Lelang",
    }
)


# =========================================================
# DISPLAY
# =========================================================
# st.dataframe(                     --uncomment untuk testing
#     detail_display,
#     width="stretch",
#     hide_index=True,
#     height=500,
# )
st.markdown("#### LEGENDS")
st.markdown("""
            HargaBaruATT: Harga Baru at that time\n
            HargaBaruCurrent: Harga Baru saat ini
""")


st.markdown("### OTR DATA")
st.dataframe(
    information_display,
    width="stretch",
    hide_index=True,
    height=500,
)


st.markdown("### DATA LELANG")
if filtered_lelang.empty:
    st.info("Tidak ada data lelang yang sesuai dengan parameter yang dipilih.")
else:
    lelang_display = build_lelang_display(filtered_lelang)
    st.caption(
        f"{len(lelang_display):,} transaksi lelang ditemukan.".replace(",", ".")
    )
    st.dataframe(
        lelang_display,
        width="stretch",
        hide_index=True,
        height=500,
    )
