import os
import pandas as pd

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_FILE_OLD = os.path.join(_DATA_DIR, "Fallzahlen&HZ 2015-2024.xlsx")
_FILE_NEW = os.path.join(_DATA_DIR, "Fallzahlen&HZ 2016-2025.xlsx")

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


def fetch_crime_data():
    """Return DataFrame with combined Moabit West+Ost Fallzahlen, 2015-2025."""
    xl_old = pd.ExcelFile(_FILE_OLD)
    xl_new = pd.ExcelFile(_FILE_NEW)

    rows = [_parse_year(xl_old, 2015)]
    for year in range(2016, 2026):
        rows.append(_parse_year(xl_new, year))

    df = pd.DataFrame(rows).set_index("year")
    return df


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

    return bezirke_f.reset_index(drop=True), bezirke_h.reset_index(drop=True)


def fetch_crime_data_by_area():
    """Return dict {year: {'Moabit West': {cat: val}, 'Moabit Ost': {cat: val}}} for 2015-2025."""
    xl_old = pd.ExcelFile(_FILE_OLD)
    xl_new = pd.ExcelFile(_FILE_NEW)

    data = {2015: _parse_year_by_area(xl_old, 2015)}
    for year in range(2016, 2026):
        data[year] = _parse_year_by_area(xl_new, year)
    return data


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


def fetch_mitte_lor_data():
    """Return (fallzahlen_df, hz_df) for all LOR areas in Mitte, 2015-2025.

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


def fetch_bezirk_comparison():
    """Return (fallzahlen_df, hz_df) for all 12 Bezirke, 2015-2025."""
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
