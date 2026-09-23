from pathlib import Path
from io import StringIO
import argparse
import sys
import time

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "Master_Live.csv"

PRICE_COLUMNS = {"OLX": "price_olx", "CSU": "price_csu", "KKB ATT": "price_kkb_att", "KKB Current": "price_kkb_curr"}


def robust_read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except UnicodeDecodeError:
        try:
            return pd.read_csv(path, encoding="utf-8-sig", engine="python", on_bad_lines='skip')
        except Exception:
            with open(path, "rb") as f:
                content = f.read().decode("utf-8", errors="replace")
            return pd.read_csv(StringIO(content))


def load_data() -> pd.DataFrame:
    if not DATA_FILE.exists():
        raise FileNotFoundError(f"{DATA_FILE} not found")
    df = robust_read_csv(DATA_FILE)
    for col in ["Brand", "Model", "Transmission", "main_type", "type_tags"]:
        if col in df.columns:
            df[col] = df[col].astype("string").str.strip().str.title()
    for col in ["Year", "CC_Norm", *PRICE_COLUMNS.values()]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def generate_min_max_avg_prices(df: pd.DataFrame, olx_col: str, csu_col: str, lelang_col: str) -> pd.DataFrame:
    df = df.copy()
    has_olx = df[olx_col].notna() & (df[olx_col] > 0)
    has_csu = df[csu_col].notna() & (df[csu_col] > 0)
    has_lelang = df[lelang_col].notna() & (df[lelang_col] > 0)

    default_series = pd.Series(np.nan, index=df.index, dtype=float)

    # avg logic: prefer olx, else csu*0.8, else lelang*1.1
    df["avg"] = default_series
    df.loc[has_olx, "avg"] = df.loc[has_olx, olx_col]
    df.loc[~has_olx & has_csu, "avg"] = (df.loc[~has_olx & has_csu, csu_col] * 0.8).round()
    df.loc[~has_olx & ~has_csu & has_lelang, "avg"] = (df.loc[~has_olx & ~has_csu & has_lelang, lelang_col] * 1.1).round()

    has_avg = df["avg"].notna() & (df["avg"] > 0)
    df["min"] = default_series
    df.loc[has_lelang, "min"] = df.loc[has_lelang, lelang_col]
    df.loc[~has_lelang & has_avg, "min"] = (df.loc[~has_lelang & has_avg, "avg"] * 0.9).round()

    df["max"] = (df["avg"] * 1.1).round()

    return df


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


def build_information_display(df: pd.DataFrame) -> pd.DataFrame:
    filtered = df.copy()
    # exclude empty Brand/Model and price_olx==0 if present
    if "Brand" in filtered.columns:
        filtered = filtered[filtered["Brand"].fillna("").astype(str).str.strip() != ""]
    if "Model" in filtered.columns:
        filtered = filtered[filtered["Model"].fillna("").astype(str).str.strip() != ""]
    if "price_olx" in filtered.columns:
        filtered = filtered[filtered["price_olx"] != 0]

    # compute min/avg/max
    information_display = generate_min_max_avg_prices(filtered, "price_olx", "price_csu", "price_lelang")

    # Vehicle composite
    cc_col = "CC_Norm" if "CC_Norm" in information_display.columns else "CC" if "CC" in information_display.columns else None
    def make_vehicle(row):
        parts = []
        parts.append(str(row.get("Model", "")).strip().title())
        if cc_col and pd.notna(row.get(cc_col)):
            parts.append(f"{row.get(cc_col):g}")
        parts.append(str(row.get("main_type", "")).strip().upper())
        parts.append(str(row.get("type_tags", "")).strip().title())
        s = " ".join([p for p in parts if p and p != "nan"]).replace(",", " ")
        return " ".join(s.split())

    information_display["Vehicle"] = information_display.apply(make_vehicle, axis=1)

    # HargaBaru columns
    if "price_kkb_att" in filtered.columns:
        information_display["HargaBaru_ATT"] = filtered["price_kkb_att"].where(filtered["price_kkb_att"].notna() & (filtered["price_kkb_att"] != 0))
    if "price_kkb_curr" in filtered.columns:
        information_display["HargaBaru_Curr"] = filtered["price_kkb_curr"].where(filtered["price_kkb_curr"].notna() & (filtered["price_kkb_curr"] != 0))

    # select and rename columns similar to UI
    information_columns = ["Brand", "Vehicle", "Year", "Transmission", "min", "avg", "max", "HargaBaru_ATT", "HargaBaru_Curr"]
    cols = [c for c in information_columns if c in information_display.columns]
    information_display = information_display[cols]

    # add formatted display columns (compact)
    for col in ["min", "avg", "max", "HargaBaru_ATT", "HargaBaru_Curr"]:
        if col in information_display.columns:
            information_display[col + "_formatted"] = information_display[col].apply(lambda v: compact_money(v) if pd.notna(v) and v != 0 else "-")

    return information_display


def save_to_excel(df: pd.DataFrame, out_path: Path):
    # Write dataframe to excel; include both raw and formatted columns
    with pd.ExcelWriter(out_path, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="information_display")


def parse_args(argv):
    p = argparse.ArgumentParser(description="Generate Excel from information_display")
    p.add_argument("--brand", help="Filter Brand", default=None)
    p.add_argument("--model", help="Filter Model", default=None)
    p.add_argument("--year", help="Filter Year", type=int, default=None)
    p.add_argument("--main_type", help="Filter main_type", default=None)
    p.add_argument("--cc", help="Filter CC (numeric)", type=float, default=None)
    p.add_argument("--transmission", help="Filter Transmission", default=None)
    p.add_argument("--out", help="Output xlsx path", default=None)
    return p.parse_args(argv)


def apply_filters(df: pd.DataFrame, args) -> pd.DataFrame:
    d = df.copy()
    if args.brand:
        d = d[d["Brand"] == args.brand]
    if args.model:
        d = d[d["Model"] == args.model]
    if args.year:
        d = d[d["Year"] == args.year]
    if args.main_type:
        d = d[d["main_type"] == args.main_type]
    if args.cc is not None:
        cc_col = "CC_Norm" if "CC_Norm" in d.columns else "CC" if "CC" in d.columns else None
        if cc_col:
            d = d[d[cc_col] == float(args.cc)]
    if args.transmission:
        d = d[d["Transmission"] == args.transmission]
    return d


def main(argv):
    args = parse_args(argv)
    df = load_data()
    df_filtered = apply_filters(df, args)
    info = build_information_display(df_filtered)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    out = Path(args.out) if args.out else BASE_DIR / f"information_display_export_{timestamp}.xlsx"
    save_to_excel(info, out)
    print(f"Saved {len(info)} rows to {out}")


if __name__ == "__main__":
    main(sys.argv[1:])
