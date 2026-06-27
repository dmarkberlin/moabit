import os
import json
import pandas as pd

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_FILE_OLD = os.path.join(_DATA_DIR, "Fallzahlen&HZ 2015-2024.xlsx")
_FILE_NEW = os.path.join(_DATA_DIR, "Fallzahlen&HZ 2016-2025.xlsx")

# Pre-computed JSON caches (committed for deployment; the source .xlsx are not).
# Regenerate locally with precompute() whenever the source data changes.
_CACHE_CRIME   = os.path.join(_DATA_DIR, "crime_moabit.json")
_CACHE_BY_AREA = os.path.join(_DATA_DIR, "crime_by_area.json")
_CACHE_BEZIRK  = os.path.join(_DATA_DIR, "crime_bezirk.json")
_CACHE_LOR     = os.path.join(_DATA_DIR, "crime_mitte_lor.json")

CATEGORIES = {
    "Straftaten insgesamt":          2,
    "Raub":                          3,
    "Straßenraub / Handtaschenraub": 4,
    "Körperverletzungen insgesamt":  5,
    "Gefährl. Körperverletzung":     6,
    "Bedrohung / Nötigung":          7,
    "Diebstahl insgesamt":           8,
    "Kfz-Diebstahl":                 9,
    "Diebstahl an/aus Kfz":         10,
    "Fahrraddiebstahl":             11,
    "Wohnraumeinbruch":             12,
    "Branddelikte insgesamt":       13,
    "Brandstiftung":                14,
    "Sachbeschädigung insgesamt":   15,
    "Graffiti":                     16,
    "Rauschgiftdelikte":            17,
    "Kieztaten":                    18,
}

# Subset shown by default in the trend chart (most neighbourhood-relevant)
DEFAULT_CATEGORIES = [
    "Straftaten insgesamt",
    "Körperverletzungen insgesamt",
    "Diebstahl insgesamt",
    "Fahrraddiebstahl",
    "Wohnraumeinbruch",
    "Kieztaten",
]


def _parse_year(xl, year):
    df = xl.parse(f"Fallzahlen_{year}", header=None)
    rows = df[df[1].astype(str).str.contains("Moabit", na=False)]
    combined = {}
    for cat, col in CATEGORIES.items():
        combined[cat] = int(rows.iloc[:, col].sum())
    combined["year"] = year
    return combined


def _parse_year_by_area(xl, year):
    df = xl.parse(f"Fallzahlen_{year}", header=None)
    rows = df[df[1].astype(str).str.contains("Moabit", na=False)].copy()
    result = {}
    for _, row in rows.iterrows():
        area = row[1]
        result[area] = {cat: int(row[col]) for cat, col in CATEGORIES.items()}
        result[area]["year"] = year
    return result


def _parse_bezirk_year(xl, year):
    """Return (fallzahlen_df, hz_df) for all 12 Bezirke for a given year."""
    col = 2  # Straftaten insgesamt

    df_f = xl.parse(f"Fallzahlen_{year}", header=None)
    bezirke_f = df_f[df_f[0].astype(str).str.endswith("0000")][[1, col]].copy()
    bezirke_f.columns = ["Bezirk", "Fallzahlen"]
    bezirke_f["year"] = year

    df_h = xl.parse(f"HZ_{year}", header=None)
    bezirke_h = df_h[df_h[0].astype(str).str.endswith("0000")][[1, col]].copy()
    bezirke_h.columns = ["Bezirk", "HZ"]
    bezirke_h["year"] = year
    bezirke_h["HZ"] = pd.to_numeric(bezirke_h["HZ"], errors="coerce")

    return bezirke_f.reset_index(drop=True), bezirke_h.reset_index(drop=True)


_MITTE_EXCLUDE = {"010000", "019900"}


def _parse_mitte_lor_year(xl, year):
    """Return (fallzahlen_rows, hz_rows) for all LOR areas in Mitte for one year."""
    col = 2  # Straftaten insgesamt

    df_f = xl.parse(f"Fallzahlen_{year}", header=None)
    mitte_f = df_f[
        df_f[0].astype(str).str.match(r"^01") &
        ~df_f[0].astype(str).isin(_MITTE_EXCLUDE)
    ][[1, col]].copy()
    mitte_f.columns = ["Gebiet", "Fallzahlen"]
    mitte_f["year"] = year

    df_h = xl.parse(f"HZ_{year}", header=None)
    mitte_h = df_h[
        df_h[0].astype(str).str.match(r"^01") &
        ~df_h[0].astype(str).isin(_MITTE_EXCLUDE)
    ][[1, col]].copy()
    mitte_h.columns = ["Gebiet", "HZ"]
    mitte_h["year"] = year
    mitte_h["HZ"] = pd.to_numeric(mitte_h["HZ"], errors="coerce")

    return mitte_f.reset_index(drop=True), mitte_h.reset_index(drop=True)


# --- Computation from source .xlsx (used by precompute and as a local fallback) ---

def _compute_crime_data():
    """DataFrame with combined Moabit West+Ost Fallzahlen, 2015-2025 (year index)."""
    xl_old = pd.ExcelFile(_FILE_OLD)
    xl_new = pd.ExcelFile(_FILE_NEW)

    rows = [_parse_year(xl_old, 2015)]
    for year in range(2016, 2026):
        rows.append(_parse_year(xl_new, year))

    return pd.DataFrame(rows).set_index("year")


def _compute_crime_data_by_area():
    """dict {year: {'Moabit West': {cat: val}, 'Moabit Ost': {cat: val}}} for 2015-2025."""
    xl_old = pd.ExcelFile(_FILE_OLD)
    xl_new = pd.ExcelFile(_FILE_NEW)

    data = {2015: _parse_year_by_area(xl_old, 2015)}
    for year in range(2016, 2026):
        data[year] = _parse_year_by_area(xl_new, year)
    return data


def _compute_bezirk_comparison():
    """(fallzahlen_df, hz_df) for all 12 Bezirke, 2015-2025."""
    xl_old = pd.ExcelFile(_FILE_OLD)
    xl_new = pd.ExcelFile(_FILE_NEW)

    f_rows, h_rows = [], []
    f_y, h_y = _parse_bezirk_year(xl_old, 2015)
    f_rows.append(f_y)
    h_rows.append(h_y)
    for year in range(2016, 2026):
        f_y, h_y = _parse_bezirk_year(xl_new, year)
        f_rows.append(f_y)
        h_rows.append(h_y)

    return pd.concat(f_rows, ignore_index=True), pd.concat(h_rows, ignore_index=True)


def _compute_mitte_lor_data():
    """(fallzahlen_df, hz_df) for all LOR areas in Mitte, 2015-2025.

    fallzahlen_df also contains a synthetic 'Moabit (gesamt)' row = West + Ost.
    """
    xl_old = pd.ExcelFile(_FILE_OLD)
    xl_new = pd.ExcelFile(_FILE_NEW)

    f_rows, h_rows = [], []
    f_y, h_y = _parse_mitte_lor_year(xl_old, 2015)
    f_rows.append(f_y); h_rows.append(h_y)
    for year in range(2016, 2026):
        f_y, h_y = _parse_mitte_lor_year(xl_new, year)
        f_rows.append(f_y); h_rows.append(h_y)

    fz_df = pd.concat(f_rows, ignore_index=True)
    hz_df = pd.concat(h_rows, ignore_index=True)

    # Add combined Moabit total for Fallzahlen
    moabit_total = (
        fz_df[fz_df["Gebiet"].isin(["Moabit West", "Moabit Ost"])]
        .groupby("year", as_index=False)["Fallzahlen"].sum()
    )
    moabit_total["Gebiet"] = "Moabit (gesamt)"
    fz_df = pd.concat([fz_df, moabit_total], ignore_index=True)

    return fz_df, hz_df


# --- Public accessors: read committed JSON cache, fall back to .xlsx locally ---

def fetch_crime_data():
    if os.path.exists(_CACHE_CRIME):
        return pd.read_json(_CACHE_CRIME, orient="records").set_index("year")
    return _compute_crime_data()


def fetch_crime_data_by_area():
    if os.path.exists(_CACHE_BY_AREA):
        with open(_CACHE_BY_AREA, encoding="utf-8") as f:
            raw = json.load(f)
        return {int(year): areas for year, areas in raw.items()}
    return _compute_crime_data_by_area()


def fetch_bezirk_comparison():
    if os.path.exists(_CACHE_BEZIRK):
        with open(_CACHE_BEZIRK, encoding="utf-8") as f:
            raw = json.load(f)
        return pd.DataFrame(raw["fallzahlen"]), pd.DataFrame(raw["hz"])
    return _compute_bezirk_comparison()


def fetch_mitte_lor_data():
    if os.path.exists(_CACHE_LOR):
        with open(_CACHE_LOR, encoding="utf-8") as f:
            raw = json.load(f)
        return pd.DataFrame(raw["fallzahlen"]), pd.DataFrame(raw["hz"])
    return _compute_mitte_lor_data()


def precompute():
    """Run locally to generate JSON caches for deployment (requires the .xlsx)."""
    _compute_crime_data().reset_index().to_json(
        _CACHE_CRIME, orient="records", indent=2, force_ascii=False
    )

    with open(_CACHE_BY_AREA, "w", encoding="utf-8") as f:
        json.dump(_compute_crime_data_by_area(), f, ensure_ascii=False, indent=2)

    bz_fall, bz_hz = _compute_bezirk_comparison()
    with open(_CACHE_BEZIRK, "w", encoding="utf-8") as f:
        json.dump(
            {"fallzahlen": bz_fall.to_dict("records"), "hz": bz_hz.to_dict("records")},
            f, ensure_ascii=False, indent=2,
        )

    lor_fall, lor_hz = _compute_mitte_lor_data()
    with open(_CACHE_LOR, "w", encoding="utf-8") as f:
        json.dump(
            {"fallzahlen": lor_fall.to_dict("records"), "hz": lor_hz.to_dict("records")},
            f, ensure_ascii=False, indent=2,
        )

    print("Precomputed crime JSON caches written to", _DATA_DIR)


if __name__ == "__main__":
    precompute()
