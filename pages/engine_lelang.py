from pathlib import Path
import csv
import json
import logging
from logging.handlers import RotatingFileHandler

import pandas as pd
import plotly.express as px
import streamlit as st


# =========================================================
# PAGE CONFIG
# =========================================================
st.set_page_config(
    page_title="Pricing - Engine Lelang",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

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

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.6rem;
        padding-bottom: 3rem;
    }
    [data-testid="stSidebar"] {
        border-right: 1px solid rgba(128, 128, 128, .28);
    }
    .page-title {
        font-size: 2rem;
        font-weight: 700;
        margin-bottom: .15rem;
        line-height: 1.25;
    }
    .page-subtitle {
        color: var(--text-color);
        opacity: .72;
        margin-bottom: 1.4rem;
    }
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
    """,
    unsafe_allow_html=True,
)


# =========================================================
# CONFIG
# =========================================================
# Script Anda kemungkinan berada di folder pages/, sedangkan CSV berada
# di root project. Agar lebih aman, cek kedua lokasi.
SCRIPT_DIR = Path(__file__).resolve().parent
DATA_CANDIDATES = [
    SCRIPT_DIR / "Lelang_Live.csv",
    SCRIPT_DIR.parent / "Lelang_Live.csv",
]
DATA_FILE = next((path for path in DATA_CANDIDATES if path.exists()), DATA_CANDIDATES[-1])

MASTER_DATA_CANDIDATES = [
    SCRIPT_DIR / "master_JBA_IBID.csv",
    SCRIPT_DIR.parent / "master_JBA_IBID.csv",
]
MASTER_DATA_FILE = next(
    (path for path in MASTER_DATA_CANDIDATES if path.exists()),
    MASTER_DATA_CANDIDATES[-1],
)

LOG_DIR = SCRIPT_DIR.parent / "logs"
LOG_FILE = LOG_DIR / "engine_lelang.log"

FILTER_COLUMNS = {
    "brand": "Brand_Norm",
    "model": "Model_Norm",
    "type": "main_type_Norm",
    "type_tag": "type_tags_Norm",
    "year": "Tahun",
    "cc": "CC_Norm",
    "transmission": "Transmission_Norm",
    "region_code": "KodeDaerah",
}

PRICE_COLUMN = "saleprice"

REQUIRED_COLUMNS = [
    FILTER_COLUMNS["brand"],
    FILTER_COLUMNS["model"],
    FILTER_COLUMNS["type"],
    FILTER_COLUMNS["type_tag"],
    FILTER_COLUMNS["year"],
    FILTER_COLUMNS["cc"],
    FILTER_COLUMNS["transmission"],
    FILTER_COLUMNS["region_code"],
    PRICE_COLUMN,
]

MASTER_FILTER_COLUMNS = {
    "brand": "Brand",
    "model": "Model",
    "type": "Type",
    "year": "Year",
    "cc": "CC",
    "transmission": "Transmission",
}

MASTER_PRICE_COLUMNS = ["ibid_new", "ibid_hp", "ibid_rv", "price_curr"]
MASTER_REQUIRED_COLUMNS = list(MASTER_FILTER_COLUMNS.values()) + MASTER_PRICE_COLUMNS


# =========================================================
# FILTER LOGGING
# =========================================================
@st.cache_resource
def get_filter_logger():
    """Siapkan logger berotasi untuk aktivitas filter Engine Lelang."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("engine_lelang.filter")
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


def log_filter_result(selection, lelang_count, master_count):
    """Catat parameter pilihan user beserta jumlah hasil dari kedua sumber."""
    payload = {
        "event": "filter_applied",
        "parameters": selection,
        "output_counts": {
            "lelang_live": int(lelang_count),
            "master_jba_ibid": int(master_count),
        },
    }
    get_filter_logger().info(
        json.dumps(payload, ensure_ascii=False, default=str)
    )


# =========================================================
# DATA LOADER
# =========================================================
def read_lelang_live_csv(file_path: Path):
    """
    Membaca Lelang_Live.csv.

    Mendukung file dengan delimiter koma maupun titik koma. Format lama juga
    dapat memiliki outer quote di level satu baris, sementara field note_csis
    sendiri dapat mengandung quote dan koma.

    Return:
        dataframe, skipped_rows
    """
    if not file_path.exists():
        raise FileNotFoundError(
            f"{file_path.name} tidak ditemukan. "
            f"Lokasi yang dicek: {', '.join(str(p) for p in DATA_CANDIDATES)}"
        )

    rows = []
    skipped_rows = 0

    with file_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
        header_line = f.readline().rstrip("\r\n")
        if not header_line:
            raise ValueError("File Lelang_Live.csv kosong.")

        try:
            delimiter = csv.Sniffer().sniff(
                header_line,
                delimiters=",;\t|",
            ).delimiter
        except csv.Error:
            delimiter = ","

        header = next(csv.reader([header_line], delimiter=delimiter))
        expected_columns = len(header)

        for line_number, line in enumerate(f, start=2):
            raw = line.rstrip("\r\n")

            if not raw.strip():
                continue

            # Pada Lelang_Live.csv, satu data row dibungkus quote.
            # Contoh: "1000,...,""note, text"",toyota,..."
            if raw.startswith('"') and raw.endswith('"'):
                raw = raw[1:-1].replace('""', '"')

            try:
                parsed = next(csv.reader([raw], delimiter=delimiter))
            except csv.Error:
                skipped_rows += 1
                continue

            if len(parsed) != expected_columns:
                skipped_rows += 1
                continue

            rows.append(parsed)

    df = pd.DataFrame(rows, columns=header)
    return df, skipped_rows


@st.cache_data(show_spinner=False)
def load_data(file_path: Path, file_version):
    # file_version membuat cache otomatis diperbarui ketika CSV diganti.
    _ = file_version
    df, skipped_rows = read_lelang_live_csv(file_path)

    # Bersihkan nama kolom untuk mencegah masalah BOM/spasi tersembunyi.
    df.columns = df.columns.astype(str).str.strip()

    missing_columns = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_columns:
        raise ValueError(
            "Kolom wajib tidak ditemukan: "
            + ", ".join(missing_columns)
            + f". Kolom yang tersedia: {', '.join(df.columns.tolist())}"
        )

    text_columns = [
        "Merk",
        "ModelName",
        #"Tipe",
        "Warna",
        "KodeDaerah",
        "BalaiLelang",
        "lokasi",
        "Transmisi",
        "kilometer2",
        "grade_overrall_csis",
        "note_csis",
        "Brand_Norm",
        "Model_Norm",
        "Transmission_Norm",
        "Type_Norm",
        "main_type_Norm",
        "type_tags_Norm",
    ]

    for col in text_columns:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype("string")
                .str.strip()
                .replace("", pd.NA)
            )

    numeric_columns = [
        "Tahun",
        "Year",
        "cc",
        "CC_Norm",
        "kilometer1",
        "saleprice",
        "lelang_price",
    ]

    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "SaleDate" in df.columns:
        df["SaleDate"] = pd.to_datetime(df["SaleDate"], errors="coerce")

    # Hanya gunakan record dengan identitas kendaraan dan harga transaksi
    # lelang yang valid. Nilai kosong pada Brand_Norm/Model_Norm/Tipe sudah
    # dinormalisasi menjadi pd.NA pada proses pembersihan kolom teks di atas.
    brand_col = FILTER_COLUMNS["brand"]
    model_col = FILTER_COLUMNS["model"]
    type_col = FILTER_COLUMNS["type"]
    df = df[
        df[brand_col].notna()
        & df[model_col].notna()
        & df[type_col].notna()
        & df[PRICE_COLUMN].notna()
        & (df[PRICE_COLUMN] > 0)
    ].copy()

    return df, skipped_rows


@st.cache_data(show_spinner=False)
def load_master_jba_ibid():
    """Memuat referensi gabungan JBA dan IBID dari CSV master."""
    if not MASTER_DATA_FILE.exists():
        raise FileNotFoundError(
            f"{MASTER_DATA_FILE.name} tidak ditemukan. "
            "Lokasi yang dicek: "
            + ", ".join(str(path) for path in MASTER_DATA_CANDIDATES)
        )

    master = pd.read_csv(MASTER_DATA_FILE, encoding="utf-8-sig")
    master.columns = master.columns.astype(str).str.strip()

    missing_columns = [
        column for column in MASTER_REQUIRED_COLUMNS if column not in master.columns
    ]
    if missing_columns:
        raise ValueError(
            "Kolom wajib master JBA/IBID tidak ditemukan: "
            + ", ".join(missing_columns)
        )

    text_columns = ["Brand", "Model", "Transmission", "Type"]
    for column in text_columns:
        if column in master.columns:
            master[column] = (
                master[column].astype("string").str.strip().replace("", pd.NA)
            )

    numeric_columns = ["Year", "CC", *MASTER_PRICE_COLUMNS]
    for column in numeric_columns:
        master[column] = pd.to_numeric(master[column], errors="coerce")

    return master


# =========================================================
# HELPERS
# =========================================================
def compact_money(value):
    if pd.isna(value):
        return "-"

    value = float(value)
    sign = "-" if value < 0 else ""
    n = abs(value)

    if n >= 1_000_000_000_000:
        scaled, unit, decimals = n / 1_000_000_000_000, "triliun", 2
    elif n >= 1_000_000_000:
        scaled, unit, decimals = n / 1_000_000_000, "milyar", 2 if n < 10_000_000_000 else 1
    elif n >= 1_000_000:
        scaled, unit, decimals = n / 1_000_000, "jt", 2 if n < 100_000_000 else 1
    elif n >= 1_000:
        scaled, unit, decimals = n / 1_000, "rb", 1
    else:
        return f"{sign}{n:,.0f}".replace(",", ".")

    text = f"{scaled:.{decimals}f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{sign}{text} {unit}"


def full_money(value):
    if pd.isna(value):
        return "-"
    return "Rp " + f"{float(value):,.0f}".replace(",", ".")


def sorted_text(series):
    return sorted(
        series.dropna().astype(str).str.strip().unique().tolist(),
        key=str.casefold,
    )


def valid_years(dataframe):
    year_col = FILTER_COLUMNS["year"]
    return (
        dataframe.loc[dataframe[year_col].between(1900, 2100), year_col]
        .dropna()
        .astype(int)
        .sort_values(ascending=False)
        .unique()
        .tolist()
    )


def cc_label(value):
    if value == "Semua CC":
        return value
    return f"{float(value):g} L"


def title_label(value):
    if isinstance(value, str) and value.startswith("Semua "):
        return value
    return str(value).title()


def normalized_match_text(series):
    """Buat kunci teks yang tahan terhadap kapital, spasi, dan tanda baca."""
    return (
        series.astype("string")
        .str.upper()
        .str.replace(r"[^A-Z0-9]+", "", regex=True)
    )


def normalized_grade(series):
    """Samakan format grade agar pengelompokan harga dan note identik."""
    return (
        series.astype("string")
        .str.strip()
        .str.upper()
        .str.replace(r"\s+", "_", regex=True)
    )


def random_notes_by_grade(dataframe, grade_column, note_column, grade_order):
    """Ambil satu note acak dari hasil filter untuk setiap grade yang tersedia."""
    note_source = pd.DataFrame(
        {
            "Grade": normalized_grade(dataframe[grade_column]),
            "Contoh note": dataframe[note_column].astype("string").str.strip(),
        }
    )

    invalid_notes = note_source["Contoh note"].str.lower().isin(
        ["", "-", "nan", "none", "null", "<na>"]
    )
    valid_notes = note_source.loc[
        note_source["Grade"].isin(grade_order)
        & note_source["Contoh note"].notna()
        & ~invalid_notes.fillna(True),
        ["Grade", "Contoh note"],
    ]

    if valid_notes.empty:
        return {}

    sampled_notes = valid_notes.groupby(
        "Grade", group_keys=False, observed=True
    ).sample(n=1)
    return sampled_notes.set_index("Grade")["Contoh note"].to_dict()


def mean_unique(series):
    """Rata-ratakan nilai referensi unik agar duplikasi transaksi tidak membobotinya."""
    values = pd.to_numeric(series, errors="coerce").dropna().drop_duplicates()
    return values.mean() if not values.empty else pd.NA


def summarize_jba_ibid_detail(matched_master):
    """Ringkas transaksi berdasarkan identitas spesifikasi kendaraan yang sama."""
    detail = matched_master.copy()
    model_parts = (
        detail[["Model", "Type"]]
        .fillna("")
        .astype(str)
        .apply(
            lambda column: column.str.replace(",", "", regex=False)
            .str.replace(r"\s+", " ", regex=True)
            .str.strip()
        )
    )
    detail["Model"] = model_parts.agg(
        lambda values: " ".join(value for value in values if value),
        axis=1,
    )
    detail = detail[detail["Model"].ne("")].copy()

    return (
        detail.groupby(
            ["Brand", "Model", "Year", "Transmission", "CC"],
            as_index=False,
            dropna=False,
        )
        .agg(
            **{
                "Rata-rata harga JBA": ("price_curr", "mean"),
                "Rata-rata harga pasar IBID": ("ibid_hp", mean_unique),
                "RV IBID (%)": ("ibid_rv", mean_unique),
            },
        )
        .rename(columns={"Year": "Tahun", "Transmission": "Transmisi"})
        .sort_values(
            ["Brand", "Model", "Tahun", "Transmisi", "CC"],
            kind="stable",
        )
    )


def filter_master_by_selection(master, selection):
    """Terapkan parameter kendaraan terpilih ke master JBA/IBID."""
    filtered_master = master.copy()

    text_filters = {
        "brand": "Semua Merk",
        "model": "Semua Model",
        "type": "Semua Tipe",
        "transmission": "Semua Transmisi",
    }
    for key, all_label in text_filters.items():
        selected_value = selection[key]
        if selected_value != all_label:
            column = MASTER_FILTER_COLUMNS[key]
            selected_key = normalized_match_text(pd.Series([selected_value])).iloc[0]
            filtered_master = filtered_master[
                normalized_match_text(filtered_master[column]) == selected_key
            ]

    if selection["year"] != "Semua Tahun":
        filtered_master = filtered_master[
            filtered_master[MASTER_FILTER_COLUMNS["year"]] == int(selection["year"])
        ]

    if selection["cc"] != "Semua CC":
        cc_column = MASTER_FILTER_COLUMNS["cc"]
        filtered_master = filtered_master[
            (filtered_master[cc_column] - float(selection["cc"])).abs() < 0.001
        ]

    return filtered_master.copy()


def render_jba_ibid_analysis(matched_master):
    """Tampilkan ringkasan dan visualisasi master JBA/IBID yang sudah cocok."""
    st.markdown("## Hasil Matching Data JBA/IBID")
    st.caption(
        "Data di bawah memakai parameter kendaraan yang sama dengan filter di atas. "
        "Harga IBID pada file master dikonversi dari juta rupiah ke rupiah."
    )

    if matched_master.empty:
        st.info("Untuk model ini belum tersedia data pada IBID dan JBA.")
        return

    jba_prices = matched_master["price_curr"].dropna()
    jba_prices = jba_prices[jba_prices > 0]

    ibid_columns = [
        "Brand",
        "Model",
        "Year",
        "Transmission",
        "CC",
        "Type",
        "ibid_hp",
        "ibid_rv",
    ]
    # Satu spesifikasi dapat berulang untuk beberapa transaksi JBA. Hilangkan
    # duplikasi agar nilai referensi IBID tidak terbobot oleh jumlah transaksi.
    ibid_reference = matched_master[ibid_columns].drop_duplicates()

    ibid_hp = ibid_reference.loc[ibid_reference["ibid_hp"] > 0, "ibid_hp"] * 1_000_000
    ibid_rv = ibid_reference.loc[ibid_reference["ibid_rv"] > 0, "ibid_rv"]

    jba_median = jba_prices.median() if not jba_prices.empty else pd.NA
    ibid_hp_median = ibid_hp.median() if not ibid_hp.empty else pd.NA
    ibid_rv_median = ibid_rv.median() if not ibid_rv.empty else pd.NA
    total_jba_ibid = len(jba_prices) + len(ibid_hp)

    kpi_1, kpi_2, kpi_3, kpi_4 = st.columns(4)
    kpi_1.metric(
        "Total data JBA & IBID",
        f"{total_jba_ibid:,}".replace(",", "."),
    )
    kpi_2.metric("Median harga JBA", compact_money(jba_median))
    kpi_3.metric("Median harga pasar IBID", compact_money(ibid_hp_median))
    kpi_4.metric(
        "Median RV IBID",
        "-" if pd.isna(ibid_rv_median) else f"{ibid_rv_median:.2f}%".replace(".", ","),
    )

    comparison_rows = [
        {"Sumber harga": "harga Pasar JBA", "Harga": jba_median},
        {"Sumber harga": "harga Pasar IBID", "Harga": ibid_hp_median},
    ]
    comparison = pd.DataFrame(comparison_rows).dropna(subset=["Harga"])

    if not comparison.empty:
        comparison["Label harga"] = comparison["Harga"].apply(compact_money)
        comparison_chart = px.bar(
            comparison,
            x="Sumber harga",
            y="Harga",
            color="Sumber harga",
            text="Label harga",
            title="Perbandingan median harga JBA dan IBID",
            color_discrete_map={
                "JBA - harga transaksi": "#2563eb",
                "IBID - harga pasar": "#f59e0b",
            },
        )
        comparison_chart.update_traces(
            textposition="outside",
            hovertemplate=(
                "<b>%{x}</b><br>Harga: Rp %{y:,.0f}<extra></extra>"
            ),
        )
        comparison_chart.update_layout(
            xaxis_title=None,
            yaxis_title="Harga (Rp)",
            showlegend=False,
        )
        st.plotly_chart(comparison_chart)

    with st.expander("Lihat detail hasil matching JBA/IBID"):
        detail = summarize_jba_ibid_detail(matched_master)
        detail["Rata-rata harga pasar IBID"] *= 1_000_000
        for price_column in [
            "Rata-rata harga JBA",
            "Rata-rata harga pasar IBID",
        ]:
            detail[price_column] = detail[price_column].apply(compact_money)
        detail["RV IBID (%)"] = detail["RV IBID (%)"].apply(
            lambda value: "-" if pd.isna(value) else f"{float(value):.2f}%"
        )
        detail = detail[
            [
                "Brand",
                "Model",
                "Tahun",
                "Transmisi",
                "CC",
                "Rata-rata harga JBA",
                "Rata-rata harga pasar IBID",
                "RV IBID (%)",
            ]
        ]
        st.dataframe(
            detail,
            hide_index=True,
            height=400,
        )


# =========================================================
# FILTER PANEL
# =========================================================
def vehicle_filter_panel(dataframe):
    st.markdown("### Input Parameter Kendaraan")

    brand_col = FILTER_COLUMNS["brand"]
    model_col = FILTER_COLUMNS["model"]
    type_col = FILTER_COLUMNS["type"]
    year_col = FILTER_COLUMNS["year"]
    cc_col = FILTER_COLUMNS["cc"]
    transmission_col = FILTER_COLUMNS["transmission"]
    region_code_col = FILTER_COLUMNS["region_code"]

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        brand = st.selectbox(
            "Merk",
            ["Semua Merk"] + sorted_text(dataframe[brand_col]),
            format_func=title_label,
        )

    d1 = dataframe if brand == "Semua Merk" else dataframe[dataframe[brand_col] == brand]

    with c2:
        model = st.selectbox(
            "Model",
            ["Semua Model"] + sorted_text(d1[model_col]),
            format_func=title_label,
        )
        
    d2 = d1 if model == "Semua Model" else d1[d1[model_col] == model]
    
    with c3:
        type = st.selectbox(
            "Tipe",
            ["Semua Tipe"] + sorted_text(d2[type_col]),
            format_func=title_label,
        )    

    d3 = d2 if type == "Semua Tipe" else d2[d2[type_col] == type]

    with c4:
        year = st.selectbox(
            "Tahun",
            ["Semua Tahun"] + valid_years(d3),
        )

    d4 = d3 if year == "Semua Tahun" else d3[d3[year_col] == int(year)]

    c4, c5, c6 = st.columns(3)

    cc_values = (
        d4[cc_col]
        .dropna()
        .sort_values()
        .unique()
        .tolist()
    )

    with c4:
        cc = st.selectbox(
            "CC",
            ["Semua CC"] + cc_values,
            format_func=cc_label,
        )

    d5 = d4 if cc == "Semua CC" else d4[d4[cc_col] == float(cc)]

    with c5:
        transmission = st.selectbox(
            "Transmisi",
            ["Semua Transmisi"] + sorted_text(d5[transmission_col]),
            format_func=title_label,
        )

    d6 = (
        d5
        if transmission == "Semua Transmisi"
        else d5[d5[transmission_col] == transmission]
    )

    with c6:
        region_code = st.selectbox(
            "KodeDaerah",
            ["Semua KodeDaerah"] + sorted_text(d6[region_code_col]),
        )

    filtered = (
        d6
        if region_code == "Semua KodeDaerah"
        else d6[d6[region_code_col] == region_code]
    )

    submitted = st.button("Terapkan Filter", type="primary")
    selection = {
        "brand": brand,
        "model": model,
        "type": type,
        "year": year,
        "cc": cc,
        "transmission": transmission,
        "region_code": region_code,
    }
    return filtered, selection, submitted


# =========================================================
# LOAD DATA
# =========================================================
try:
    data_file_version = DATA_FILE.stat().st_mtime_ns if DATA_FILE.exists() else None
    df, skipped_rows = load_data(DATA_FILE, data_file_version)
    master_jba_ibid = load_master_jba_ibid()
except Exception as exc:
    st.error(str(exc))
    st.stop()


# =========================================================
# PAGE HEADER
# =========================================================
st.markdown(
    '<div class="page-title">Engine Lelang</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="page-subtitle">Analisis histori harga lelang dan referensi kendaraan comparable dari JBA serta IBID.</div>',
    unsafe_allow_html=True,
)

if skipped_rows > 0:
    st.warning(f"{skipped_rows:,} baris CSV tidak dapat diparsing dan dilewati.".replace(",", "."))


# =========================================================
# FILTER
# =========================================================
filtered, selection, submitted = vehicle_filter_panel(df)

if not submitted:
    st.info("Pilih parameter lalu klik 'Terapkan Filter' untuk melihat hasil analisa.")
    st.stop()

matched_master = filter_master_by_selection(master_jba_ibid, selection)
log_filter_result(
    selection,
    lelang_count=len(filtered),
    master_count=len(matched_master),
)

if filtered.empty:
    st.warning("Tidak ada data untuk parameter yang dipilih.")
    st.stop()


# =========================================================
# SINGLE-SOURCE AUCTION PRICE ANALYSIS
# =========================================================
auction = filtered[PRICE_COLUMN].dropna()
auction = auction[auction > 0]

if auction.empty:
    st.info("Data harga lelang belum tersedia untuk parameter yang dipilih.")
    st.stop()

auction_count = len(auction)
auction_median = auction.median()
auction_mean = auction.mean()
auction_q1 = auction.quantile(0.25)
auction_q3 = auction.quantile(0.75)
auction_min = auction.min()
auction_max = auction.max()

# Prototype rekomendasi single-source: median transaksi comparable.
suggested_floor = auction_median


# =========================================================
# METRICS
# =========================================================
st.markdown("## Hasil Matching Data Aplikasi Lelang")

k1, k2, k3 = st.columns(3)

k1.metric("Jumlah Data Ditemukan", f"{auction_count:,}".replace(",", "."))
k2.metric("Median Harga Lelang", compact_money(auction_median))
k3.metric("Rata-rata Harga Lelang", compact_money(auction_mean))


# =========================================================
# RECOMMENDATION
# =========================================================
st.markdown("### Prototype Rekomendasi")

st.success(
    f"**Indikasi harga dasar lelang: {compact_money(suggested_floor)}**\n\n"
)

st.caption(
    f"Engine lelang hanya sebagai alat bantu, sebaiknya decision tetap mempertimbangkan kilometer, "
    "grade kondisi, recency transaksi, dan lokasi/balai lelang."
)


# =========================================================
# PRICE SUMMARY CHART
# =========================================================
chart_df = pd.DataFrame(
    {
        "Statistik": ["Q1", "Median", "Q3"],
        "Harga": [auction_q1, auction_median, auction_q3],
    }
)

fig = px.bar(
    chart_df,
    x="Statistik",
    y="Harga",
    text=chart_df["Harga"].apply(compact_money),
    title="Rentang Harga Lelang Kendaraan Comparable",
)
fig.update_traces(textposition="outside")
fig.update_layout(yaxis_title="Harga Lelang", xaxis_title=None)
st.plotly_chart(fig)


# =========================================================
# GRADE PRICE ANALYSIS
# =========================================================
grade_column = "grade_overrall_csis"
note_column = "note_csis"
grade_order = ["GOOD", "VERY_GOOD", "BAD"]

if grade_column in filtered.columns:
    grade_analysis = filtered[[grade_column, PRICE_COLUMN]].copy()
    grade_analysis["Grade"] = normalized_grade(grade_analysis[grade_column])
    grade_analysis = grade_analysis[grade_analysis["Grade"].isin(grade_order)]

    if note_column in filtered.columns:
        grade_note_map = random_notes_by_grade(
            filtered,
            grade_column,
            note_column,
            grade_order,
        )
    else:
        grade_note_map = {}

    if not grade_analysis.empty:
        grade_summary = (
            grade_analysis.groupby("Grade", as_index=False, observed=True)
            .agg(
                **{
                    "Rata-rata Harga Lelang": (PRICE_COLUMN, "mean"),
                    "Jumlah Data": (PRICE_COLUMN, "size"),
                }
            )
        )
        grade_summary["Contoh note"] = grade_summary["Grade"].map(grade_note_map).fillna("-")
        grade_summary["Grade"] = pd.Categorical(
            grade_summary["Grade"], categories=grade_order, ordered=True
        )
        grade_summary = grade_summary.sort_values("Grade")
        grade_summary["Label Harga"] = grade_summary["Rata-rata Harga Lelang"].apply(
            compact_money
        )

        st.markdown("### Rata-rata harga lelang per grade")
        grade_fig = px.bar(
            grade_summary,
            x="Grade",
            y="Rata-rata Harga Lelang",
            color="Grade",
            text="Label Harga",
            category_orders={"Grade": grade_order},
            color_discrete_map={
                "GOOD": "#16a34a",
                "VERY_GOOD": "#2563eb",
                "BAD": "#dc2626",
            },
            title="Rata-rata harga lelang berdasarkan grade kondisi (hover pada barchart untuk contoh note)",
            custom_data=["Label Harga", "Jumlah Data", "Contoh note"],
        )
        grade_fig.update_traces(
            textposition="outside",
            hovertemplate=(
                "<b>Grade: %{x}</b><br>"
                "Rata-rata harga: %{customdata[0]}<br>"
                "Jumlah data: %{customdata[1]}<br>"
                "Contoh note: %{customdata[2]}<extra></extra>"
            ),
        )
        grade_fig.update_layout(
            xaxis_title="Grade kondisi",
            yaxis_title="Rata-rata harga lelang",
            showlegend=False,
        )
        st.plotly_chart(grade_fig)


# =========================================================
# DETAIL DATA
# =========================================================
st.markdown("### Detail Data")

detail_display = filtered.copy()

# Bentuk label tipe untuk tabel dari model dan main type yang sudah dinormalisasi.
model_display = detail_display["Model_Norm"].fillna("").astype("string").str.strip()
main_type_display = (
    detail_display["main_type_Norm"].fillna("").astype("string").str.strip()
)
detail_display["Tipe"] = (
    (model_display + " " + main_type_display)
    .str.replace(r"\s+", " ", regex=True)
    .str.strip()
)

# Format hanya pada copy untuk display agar data asli tetap numerik.
detail_display[PRICE_COLUMN] = detail_display[PRICE_COLUMN].apply(compact_money)

if "CC_Norm" in detail_display.columns:
    detail_display["CC_Norm"] = detail_display["CC_Norm"].apply(
        lambda x: "-" if pd.isna(x) else f"{x:g} L"
    )

if "SaleDate" in detail_display.columns:
    detail_display["SaleDate"] = detail_display["SaleDate"].dt.strftime("%Y-%m-%d")

if "kilometer1" in detail_display.columns:
    detail_display["kilometer1"] = detail_display["kilometer1"].apply(
        lambda x: "-" if pd.isna(x) else f"{x:,.0f}".replace(",", ".")
    )

# Kolom detail sesuai struktur Lelang_Live.csv.
detail_columns = [
    "Brand_Norm",
    "Tipe",
    "Type_Tag_Norm",
    "Tahun",
    "CC_Norm",
    "Transmission_Norm",
    "KodeDaerah",
    "saleprice",
    "SaleDate",
    "kilometer1",
    "grade_overrall_csis",
    "BalaiLelang",
    "lokasi",
]

detail_display = detail_display[
    [col for col in detail_columns if col in detail_display.columns]
]

detail_display = detail_display.rename(
    columns={
        "Brand_Norm": "Merk",
        "Tipe": "Tipe",
        "Type_Tag_Norm": "TypeTag",
        "Tahun": "Tahun",
        "CC_Norm": "CC",
        "Transmission_Norm": "Transmisi",
        "saleprice": "Harga Lelang",
        "SaleDate": "Tanggal Lelang",
        "kilometer1": "Kilometer",
        "grade_overrall_csis": "Grade",
        "BalaiLelang": "Balai Lelang",
        "lokasi": "Lokasi",
    }
)

st.dataframe(
    detail_display,
    hide_index=True,
    height=500,
)


# =========================================================
# JBA / IBID REFERENCE
# =========================================================
render_jba_ibid_analysis(matched_master)
