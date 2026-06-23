import os
import re
import pandas as pd

CSV_PATH = "data/EWR_L21_202412E_Matrix.csv"
XLSX_DIR = "data"

# Moabit: Bezirk 1 (Mitte)
# Post-2021 LOR: BZR 4 and 5
# Pre-2021 LOR:  BZR 21 and 22
MOABIT_BEZ = "01"
MOABIT_BZR_NEW = [4.0, 5.0]
MOABIT_BZR_OLD = [21.0, 22.0]

AGE_BANDS = {
    "0–5":   ["E_EU1", "E_E1U6"],
    "6–14":  ["E_E6U15"],
    "15–17": ["E_E15U18"],
    "18–24": ["E_E18U25"],
    "25–54": ["E_E25U55"],
    "55–64": ["E_E55U65"],
    "65–79": ["E_E65U80"],
    "80+":   ["E_E80U110"],
}

# (fragment, display, exact) — if exact=True, the cell must contain ONLY this
# fragment (after stripping) rather than just containing it anywhere.
# This prevents "Syrien" matching "Islamische Länder einschl. Syrien" etc.
T4_TARGETS = [
    ("Frank",        "France",               False),
    ("Griechen",     "Greece",               False),
    ("Italien",      "Italy",                False),
    ("Öster",        "Austria",              False),
    ("Spanien",      "Spain",                False),
    ("Polen",        "Poland",               False),
    ("Bulgar",       "Bulgaria",             False),
    ("Rumän",        "Romania",              False),
    ("Kroat",        "Croatia",              False),
    ("Königreich",   "UK",                   False),
    ("Bosnien",      "Bosnia & Herz.",       False),
    ("Serbien",      "Serbia",               False),
    ("Russi",        "Russia",               False),
    ("Ukraine",      "Ukraine",              False),
    ("Kasach",       "Kazakhstan",           False),
    ("Türkei",       "Turkey",               False),
    ("Afghan",       "Afghanistan",          False),
    ("Iran",         "Iran",                 True),   # avoid matching "Ukraine" etc.
    ("Libanon",      "Lebanon",              False),
    ("Syrien",       "Syria",                True),   # avoid "einschl. Syrien" in group labels
    ("Irak",         "Iraq",                 False),
    ("China",        "China",                False),
    ("Indien",       "India",                False),
    ("Vietnam",      "Vietnam",              False),
    ("Vereinigte",   "USA",                  False),
    ("nicht",        "Other",                False),
]

# Muted earth palette — flat, no semantic grouping, assigned alphabetically.
COUNTRY_COLOURS = {
    "Afghanistan":    "#8B3A3A",
    "Austria":        "#A0522D",
    "Bosnia & Herz.": "#B8860B",
    "Bulgaria":       "#6B8E23",
    "China":          "#2F6B4F",
    "Croatia":        "#2E6B8A",
    "France":         "#3B4D8A",
    "Greece":         "#6A3D8A",
    "India":          "#8A3D6A",
    "Iran":           "#7A3030",
    "Iraq":           "#C06040",
    "Italy":          "#C89030",
    "Kazakhstan":     "#4A8040",
    "Lebanon":        "#308070",
    "Other":          "#78909C",
    "Poland":         "#305090",
    "Romania":        "#604090",
    "Russia":         "#904060",
    "Serbia":         "#A07060",
    "Spain":          "#60A080",
    "Syria":          "#8090C0",
    "Turkey":         "#C080A0",
    "UK":             "#708050",
    "Ukraine":        "#807050",
    "USA":            "#3080A0",
    "Vietnam":        "#546E7A",
}

# --- Current snapshot (from CSV) ---

def load_moabit():
    df = pd.read_csv(CSV_PATH, sep=None, engine="python", encoding="utf-8-sig")
    bzr_vals = [int(v) for v in MOABIT_BZR_NEW]
    return df[(df["BEZ"] == 1) & (df["BZR"].isin(bzr_vals))]

def population_total(df):
    return int(df["E_E"].sum())

def population_by_gender(df):
    return {
        "Male":   int(df["E_EM"].sum()),
        "Female": int(df["E_EW"].sum()),
    }

def population_by_age(df):
    result = {}
    for label, cols in AGE_BANDS.items():
        valid = [c for c in cols if c in df.columns]
        result[label] = int(df[valid].sum().sum())
    return result

# --- XLSX helpers ---

def _sheet(path, name):
    """Return the correct sheet name, handling the 2020 dual-period file."""
    xl = pd.ExcelFile(path)
    if name in xl.sheet_names:
        return name
    # 2020 file uses T2a, T3a, T4a for 31.12.2020
    fallback = name + "a"
    if fallback in xl.sheet_names:
        return fallback
    raise ValueError(f"Sheet '{name}' not found in {path}")

def _moabit_rows(df):
    data = df[pd.to_numeric(df.iloc[:, 4], errors="coerce").notna()].copy()
    data["_bez"] = data.iloc[:, 0].astype(str).str.strip()
    data["_bzr"] = pd.to_numeric(data.iloc[:, 2], errors="coerce")
    # Try post-2021 LOR first, fall back to pre-2021
    result = data[(data["_bez"] == MOABIT_BEZ) & (data["_bzr"].isin(MOABIT_BZR_NEW))]
    if result.empty:
        result = data[(data["_bez"] == MOABIT_BEZ) & (data["_bzr"].isin(MOABIT_BZR_OLD))]
    return result

def _num(series):
    return pd.to_numeric(series, errors="coerce").fillna(0)

def _t4_col_map(df):
    """
    Build a mapping of {col_index: display_name} from the T4 header rows,
    dynamically — so it works regardless of column layout changes between years.
    Excludes the Planungsraum ID column.
    """
    # Concatenate header rows 2–5 per column into a single label string
    label_map = {}
    for col_idx in range(len(df.columns)):
        parts = []
        for row_idx in [2, 3, 4, 5]:
            if row_idx >= len(df):
                continue
            val = df.iloc[row_idx, col_idx]
            if pd.notna(val) and str(val).strip():
                parts.append(str(val).replace("\n", " ").strip())
        if parts:
            label_map[col_idx] = " / ".join(parts)

    # Identify and exclude Planungsraum ID column
    plr_col = next(
        (i for i, v in label_map.items() if "Planungs" in v and "raum" in v.lower()),
        None
    )

    result = {}
    for col_idx, label in label_map.items():
        if col_idx == plr_col:
            continue
        label_lower = label.lower()
        for fragment, display, exact in T4_TARGETS:
            frag_lower = fragment.lower()
            if exact:
                # Match only if the fragment is the entire label (case-insensitive)
                if label.strip().lower() == frag_lower:
                    if display not in result.values():
                        result[col_idx] = display
                    break
            else:
                if frag_lower in label_lower:
                    if display not in result.values():
                        result[col_idx] = display
                    break

    return result

# --- T2: population & age groups ---

def _parse_t2(path):
    df = pd.read_excel(path, sheet_name=_sheet(path, "T2"), header=None)
    m = _moabit_rows(df)
    if m.empty:
        return None
    total   = _num(m.iloc[:, 4]).sum()
    u6      = _num(m.iloc[:, 5]).sum()
    a6_15   = _num(m.iloc[:, 6]).sum()
    a15_18  = _num(m.iloc[:, 7]).sum()
    a18_27  = _num(m.iloc[:, 8]).sum()
    a27_45  = _num(m.iloc[:, 9]).sum()
    a45_55  = _num(m.iloc[:, 10]).sum()
    a55_65  = _num(m.iloc[:, 11]).sum()
    a65p    = _num(m.iloc[:, 12]).sum()
    female  = _num(m.iloc[:, 13]).sum()
    foreign = _num(m.iloc[:, 14]).sum()
    return {
        "total":           int(total),
        "female_pct":      round(female  / total * 100, 1),
        "foreign_pct":     round(foreign / total * 100, 1),
        "young_adult_pct": round((a18_27 + a27_45) / total * 100, 1),
        "u18_pct":         round((u6 + a6_15 + a15_18) / total * 100, 1),
        "senior_pct":      round((a55_65 + a65p) / total * 100, 1),
        "u6":     int(u6),
        "6_15":   int(a6_15),
        "15_18":  int(a15_18),
        "18_27":  int(a18_27),
        "27_45":  int(a27_45),
        "45_55":  int(a45_55),
        "55_65":  int(a55_65),
        "65plus": int(a65p),
    }

# --- T1: migration background ---

def _parse_t1(path):
    df = pd.read_excel(path, sheet_name=_sheet(path, "T1"), header=None)
    m = _moabit_rows(df)
    if m.empty:
        return None
    total         = _num(m.iloc[:, 4]).sum()
    german_no_mig = _num(m.iloc[:, 10]).sum()
    german_mig    = _num(m.iloc[:, 12]).sum()
    foreign       = _num(m.iloc[:, 14]).sum()
    with_mig_bg   = german_mig + foreign
    return {
        "german_no_mig_pct": round(german_no_mig / total * 100, 1),
        "german_mig_pct":    round(german_mig    / total * 100, 1),
        "foreign_pct":       round(foreign        / total * 100, 1),
        "with_mig_bg_pct":   round(with_mig_bg    / total * 100, 1),
    }

def _parse_t4(path):
    df = pd.read_excel(path, sheet_name=_sheet(path, "T4"), header=None)
    m = _moabit_rows(df)
    if m.empty:
        return None
    col_map = _t4_col_map(df)
    if not col_map:
        return None
    result = {}
    for col_idx, display in col_map.items():
        val = int(_num(m.iloc[:, col_idx]).sum())
        if val > 0:
            result[display] = result.get(display, 0) + val
    return result if result else None

# --- Time series ---

def _iter_december_files(min_year=2021):
    pattern = re.compile(r"SB_A01-16-00_(\d{4})h(\d{2})_BE\.xlsx")
    for fname in sorted(os.listdir(XLSX_DIR)):
        m = pattern.match(fname)
        if not m:
            continue
        year, half = int(m.group(1)), int(m.group(2))
        if year >= min_year and half == 2:
            yield year, os.path.join(XLSX_DIR, fname)

CACHE_TREND       = os.path.join(XLSX_DIR, "demographics_trend.json")
CACHE_MIGRATION   = os.path.join(XLSX_DIR, "demographics_migration.json")
CACHE_NATIONALITY = os.path.join(XLSX_DIR, "demographics_nationality.json")

def population_over_time():
    if os.path.exists(CACHE_TREND):
        return pd.read_json(CACHE_TREND, orient="records")
    results = []
    for year, path in _iter_december_files(min_year=2021):
        row = _parse_t2(path)
        if row:
            row["year"] = year
            results.append(row)
    if not results:
        return pd.DataFrame()
    return pd.DataFrame(results).sort_values("year").reset_index(drop=True)

def migration_over_time():
    if os.path.exists(CACHE_MIGRATION):
        return pd.read_json(CACHE_MIGRATION, orient="records")
    results = []
    for year, path in _iter_december_files(min_year=2021):
        row = _parse_t1(path)
        if row:
            row["year"] = year
            results.append(row)
    if not results:
        return pd.DataFrame()
    return pd.DataFrame(results).sort_values("year").reset_index(drop=True)

def nationality_over_time():
    if os.path.exists(CACHE_NATIONALITY):
        return pd.read_json(CACHE_NATIONALITY, orient="records")
    results = []
    for year, path in _iter_december_files(min_year=2021):
        row = _parse_t4(path)
        if row:
            row["year"] = year
            results.append(row)
    if not results:
        return pd.DataFrame()
    df = pd.DataFrame(results).sort_values("year").reset_index(drop=True)
    df = df.set_index("year").fillna(0).astype(int).reset_index()
    return df

def precompute():
    """Run locally to generate JSON caches for deployment."""
    import json
    population_over_time().to_json(CACHE_TREND, orient="records", indent=2)
    migration_over_time().to_json(CACHE_MIGRATION, orient="records", indent=2)
    nat = nationality_over_time()
    if not nat.empty:
        nat.to_json(CACHE_NATIONALITY, orient="records", indent=2)
    print("Precomputed demographics JSON files written to", XLSX_DIR)

