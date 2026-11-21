import base64
import json
import os
import pathlib
import re
from datetime import date
from urllib.parse import quote
import pandas as pd
import requests
import streamlit as st

os.chdir(pathlib.Path(__file__).parent)
import folium
from folium.plugins import MarkerCluster, FastMarkerCluster, LocateControl
from folium.template import Template
from branca.element import MacroElement
from streamlit_folium import st_folium

import plotly.graph_objects as go
from layers.transport import fetch_stops, stop_style
from layers.cycling import fetch_cycle_lanes, lane_style, LEGEND as CYCLE_LEGEND
from layers.wohnlagen import fetch_wohnlagen, WOL_STYLE
from layers.rent import YEARS as IBB_YEARS, ASKING_RENTS, BERLIN_MEDIAN_KEY
from layers.greenspace import fetch_greenspaces, FEATURE_STYLE, LEGEND as GREEN_LEGEND, TYPE_LABELS as GREEN_TYPE_LABELS
from layers.trees import fetch_trees, TREE_TYPES, FIELDS as TREE_FIELDS, SPECIES_EN
from layers.amenities import fetch_amenities, AMENITY_STYLE, LEGEND as AMENITY_LEGEND
from layers.routes import fetch_routes, fetch_routes_full, ROUTE_STYLE, LEGEND as ROUTE_LEGEND
from layers.bikeshare import fetch_bikeshare_stations
from layers.noise import (
    fetch_noise_data, THRESHOLDS, DB_BANDS,
    WMS_URL as NOISE_WMS_URL, WMS_LAYERS as NOISE_WMS_LAYERS, LEGEND as NOISE_LEGEND,
    sld_body as noise_sld_body,
)
from layers.noise_2004 import (
    fetch_noise_2004, WMS_URL as NOISE04_WMS_URL, WMS_LAYERS as NOISE04_WMS_LAYERS,
    LEGEND as NOISE04_LEGEND, LEGEND_UNRATED_COLOUR as NOISE04_UNRATED,
)
from layers.crime import fetch_crime_data, fetch_crime_data_by_area, fetch_bezirk_comparison, fetch_mitte_lor_data, CATEGORIES, DEFAULT_CATEGORIES
from layers.airquality import (
    fetch_current, fetch_history,
    STATION_NAME, STATION_LAT, STATION_LON,
    MOABIT_STATIONS, LIMITS, INDEX_LABELS, COMPONENT_COLOURS,
)
from layers.demographics import (
    population_over_time, migration_over_time, nationality_over_time,
    COUNTRY_COLOURS,
)

st.set_page_config(page_title="Moabiter Dashboard", page_icon="images/icon.png", layout="wide")
st.markdown("""
<style>
.block-container { padding-top: 1rem !important; }
h1 { font-weight: 400 !important; letter-spacing: 0.04em; }
[role="tab"], [role="tab"] p, [role="tab"] div { font-size: 1.10rem !important; }
</style>
""", unsafe_allow_html=True)

try:
    _ua = st.context.headers.get("User-Agent", "")
except AttributeError:
    _ua = ""
_is_mobile = any(kw in _ua for kw in ("Mobile", "Android", "iPhone", "iPad"))
_plot_config = {"staticPlot": True} if _is_mobile else {}


# --- Language -----------------------------------------------------------------
# One code base for both languages: every visible string goes through tr(de, en).
# The choice is kept in ?lang=en so English links can be shared. The switch sits
# in the header rather than the sidebar, which is collapsed by default on phones.
_LANG_OPTIONS = ["Deutsch", "English"]
if "lang" not in st.session_state:
    st.session_state.lang = "English" if st.query_params.get("lang", "").lower() == "en" else "Deutsch"

_title_size = "1.3rem" if _is_mobile else "1.8rem"
_hdr_title, _hdr_lang = st.columns([4, 1], vertical_alignment="center")
with _hdr_title:
    st.markdown(f"<h1 style='font-size:{_title_size}; margin-bottom:0.25rem'>Moabiter Dashboard</h1>", unsafe_allow_html=True)
with _hdr_lang:
    st.radio("Sprache / Language", _LANG_OPTIONS, key="lang", horizontal=True, label_visibility="collapsed")

LANG = "en" if st.session_state.lang == "English" else "de"
if LANG == "en":
    st.query_params["lang"] = "en"
elif "lang" in st.query_params:
    del st.query_params["lang"]


def tr(de, en):
    """Return the string for the active language."""
    return en if LANG == "en" else de


# English for labels defined in the layer modules (which stay German-only).
_LABEL_EN = {
    # cycle lanes
    "Fahrradweg": "Cycle path", "Radfahrstreifen": "Painted cycle lane", "Sonstige": "Other",
    # Wohnlagen (Berlin rent-index categories)
    "Einfach": "Simple", "Mittel": "Medium", "Gut": "Good",
    # amenities
    "Schule": "School", "Kita": "Kita (nursery)", "Apotheke": "Pharmacy", "Arzt": "Doctor",
    "Klinik": "Clinic", "Supermarkt": "Supermarket", "Kiosk": "Corner shop (Kiosk)",
    # green spaces
    "Park": "Park", "Garten": "Garden", "Rasenfläche": "Lawn", "Freizeitgelände": "Recreation ground",
    "Spielplatz": "Playground", "Sportstätte": "Sports ground",
    # trees
    "Straßenbaum": "Street tree", "Anlagenbaum": "Park tree",
    # noise map options
    "Gesamt": "All sources", "Straße": "Road", "Tram & U-Bahn": "Tram & U-Bahn",
    "24 h": "24 h", "Nacht": "Night", "Schiene": "Rail", "Tag": "Day",
    # air quality: pollutant label (German decimal comma) and UBA index
    "PM₂,₅": "PM₂.₅",
    "sehr gut": "very good", "gut": "good", "mäßig": "moderate",
    "schlecht": "poor", "sehr schlecht": "very poor", "äußerst schlecht": "extremely poor",
    # noise-sensitive buildings
    "Kitas": "Kitas (nurseries)", "Schulen & Bildung": "Schools & education", "Krankenhäuser": "Hospitals",
    # crime: measures, areas and offence categories (police statistics, PKS)
    "Fallzahlen": "Recorded offences", "HZ (pro 100 000 Einwohner)": "Rate per 100,000 residents",
    "HZ": "Rate per 100,000 residents", "Moabit (gesamt)": "Moabit (total)",
    "Straftaten insgesamt": "All offences",
    "Raub": "Robbery",
    "Straßenraub / Handtaschenraub": "Street robbery / bag snatching",
    "Körperverletzungen insgesamt": "Assault (all)",
    "Gefährl. Körperverletzung": "Aggravated assault",
    "Bedrohung / Nötigung": "Threats / coercion",
    "Diebstahl insgesamt": "Theft (all)",
    "Kfz-Diebstahl": "Vehicle theft",
    "Diebstahl an/aus Kfz": "Theft from vehicles",
    "Fahrraddiebstahl": "Bicycle theft",
    "Wohnraumeinbruch": "Domestic burglary",
    "Branddelikte insgesamt": "Arson offences (all)",
    "Brandstiftung": "Arson",
    "Sachbeschädigung insgesamt": "Criminal damage (all)",
    "Graffiti": "Graffiti",
    "Rauschgiftdelikte": "Drug offences",
    "Kieztaten": "Neighbourhood offences (Kieztaten)",
}


def trl(label):
    """Translate a German label from a layer module, if English is active."""
    return _LABEL_EN.get(label, label) if LANG == "en" else label


# The demographics data keys countries by English name (also the colour keys).
_COUNTRY_DE = {
    "Afghanistan": "Afghanistan", "Austria": "Österreich", "Bosnia & Herz.": "Bosnien-Herz.",
    "Bulgaria": "Bulgarien", "China": "China", "Croatia": "Kroatien", "France": "Frankreich",
    "Greece": "Griechenland", "India": "Indien", "Iran": "Iran", "Iraq": "Irak", "Italy": "Italien",
    "Kazakhstan": "Kasachstan", "Lebanon": "Libanon", "Other": "Sonstige", "Poland": "Polen",
    "Romania": "Rumänien", "Russia": "Russland", "Serbia": "Serbien", "Spain": "Spanien",
    "Syria": "Syrien", "Turkey": "Türkei", "UK": "Ver. Königreich", "Ukraine": "Ukraine",
    "USA": "USA", "Vietnam": "Vietnam",
}


def tr_country(name):
    """Display name for a country key from the demographics data."""
    return name if LANG == "en" else _COUNTRY_DE.get(name, name)


def tr_species(name):
    """English common name for a German tree species, if known and English is active."""
    return SPECIES_EN.get(name, name) if LANG == "en" else name


# --- Noise legend (shared by the sidebar and the on-map legend) ---------------------
# Items are (kind, colour, label): kind "box" = filled square (2022 raster classes),
# "none" = hollow square for the class the map leaves uncoloured, "line" = line
# symbol (2004 draws coloured street/rail lines).

def _swatch_html(kind, colour, size="0.75em"):
    if kind == "line":
        return (f'<span style="display:inline-block;width:1.4em;height:0.22em;background:{colour};'
                f'vertical-align:0.2em;margin-right:0.35em"></span>')
    if kind == "none":
        return (f'<span style="display:inline-block;width:{size};height:{size};box-sizing:border-box;'
                f'border:1px solid rgba(250,250,250,0.6);vertical-align:-0.05em;margin-right:0.35em"></span>')
    return (f'<span style="display:inline-block;width:{size};height:{size};background:{colour};'
            f'vertical-align:-0.05em;margin-right:0.35em"></span>')


def _legend_rows_html(items):
    return "".join(f"<div>{_swatch_html(k, c)}{label}</div>" for k, c, label in items)


class _MapLegend(MacroElement):
    """Legend box that belongs to a feature group.

    st_folium swaps feature groups without rebuilding the map. A plain Leaflet
    control would survive that swap (controls are not layers), so the control is
    wrapped in a tiny layer that adds it when its group joins the map and
    removes it when the group is removed. The legend therefore changes with the
    noise year/options without resetting the view.
    """

    _template = Template("""
        {% macro script(this, kwargs) %}
        var {{ this.get_name() }} = (function () {
            var control = L.control({position: "bottomleft"});
            control.onAdd = function () {
                var div = L.DomUtil.create("div");
                div.innerHTML = {{ this.html|tojson }};
                L.DomEvent.disableClickPropagation(div);
                L.DomEvent.disableScrollPropagation(div);
                return div;
            };
            var Holder = L.Layer.extend({
                onAdd: function (map) { control.addTo(map); },
                onRemove: function (map) { control.remove(); }
            });
            return new Holder();
        })();
        {{ this._parent.get_name() }}.addLayer({{ this.get_name() }});
        {% endmacro %}
    """)

    def __init__(self, html):
        super().__init__()
        self._name = "MapLegend"
        self.html = html


def _tr_delay(text):
    """Station boards report punctuality in German; "+3 min" needs no translation."""
    return tr(text, "on time") if text == "pünktlich" else text

@st.cache_data
def _load_boundary():
    with open("data/moabit_boundary.geojson", encoding="utf-8") as f:
        return json.load(f)

boundary = _load_boundary()

@st.cache_data(ttl=3600)
def get_stops():
    return fetch_stops()

@st.cache_data(ttl=3600)
def get_lanes():
    return fetch_cycle_lanes()

@st.cache_data(ttl=86400)
def get_population_over_time():
    return population_over_time()

@st.cache_data(ttl=86400)
def get_migration_over_time():
    return migration_over_time()

@st.cache_data(ttl=86400)
def get_nationality_over_time():
    return nationality_over_time()

@st.cache_data(ttl=86400)
def get_wohnlagen():
    return fetch_wohnlagen()

@st.cache_data(ttl=86400)
def get_greenspaces():
    return fetch_greenspaces()

@st.cache_data(ttl=86400)
def get_trees():
    return fetch_trees()

@st.cache_data(ttl=86400)
def get_amenities():
    return fetch_amenities()

@st.cache_data(ttl=86400)
def get_routes():
    return fetch_routes()

@st.cache_data(ttl=86400)
def get_routes_full():
    return fetch_routes_full()

@st.cache_data(ttl=300)
def get_bikeshare_stations():
    return fetch_bikeshare_stations()

@st.cache_data(ttl=86400)
def get_noise_data():
    return fetch_noise_data()

@st.cache_data(ttl=86400)
def get_noise_2004():
    return fetch_noise_2004()

@st.cache_data(ttl=3600)
def get_airquality_current():
    return fetch_current()

@st.cache_data(ttl=86400)
def get_airquality_history():
    return fetch_history(days=365)

@st.cache_data(ttl=86400)
def get_crime_data():
    return fetch_crime_data()

@st.cache_data(ttl=86400)
def get_bezirk_comparison():
    return fetch_bezirk_comparison()

@st.cache_data(ttl=86400)
def get_mitte_lor_data():
    return fetch_mitte_lor_data()

@st.cache_data(ttl=86400)
def get_crime_data_by_area():
    return fetch_crime_data_by_area()

def _svg_uri(filename, scale=1.0, title=None):
    path = os.path.join("images", filename)
    with open(path, "r", encoding="utf-8") as f:
        svg = f.read()
    if title:
        svg = re.sub(r'(<svg[^>]*>)', rf'\1<title>{title}</title>', svg, count=1)
    if scale != 1.0:
        # Wrap in a larger canvas so the icon appears smaller within the cell
        pad = (1 - scale) / 2 * 100
        inner = scale * 100
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            f'<title>{title}</title>'
            f'<image href="data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}" '
            f'x="{pad}" y="{pad}" width="{inner}" height="{inner}"/>'
            f'</svg>'
        )
    data = base64.b64encode(svg.encode()).decode()
    return f"data:image/svg+xml;base64,{data}"

_TYPE_ICON = {
    "S":          _svg_uri("S-Bahn-Logo.svg",             title="S-Bahn"),
    "U":          _svg_uri("U-Bahn-Logo-BVG.svg",         title="U-Bahn"),
    "Tram":       _svg_uri("Tram-Logo-BVG.svg",           title="Tram"),
    "Bus":        _svg_uri("BUS-Logo-BVG.svg",            title="Bus"),
    "ExpressBus": _svg_uri("BUS-Logo-BVG.svg",            title="ExpressBus"),
    "NachtBus":   _svg_uri("BUS-Logo-BVG.svg",            title="Nachtbus"),
    "Ferry":      _svg_uri("Fähre-Logo-BVG.svg",          title="Fähre"),
    "RB":         _svg_uri("VBB_Bahn-Regionalverkehr.svg", title="Regionalbahn"),
    "RE":         _svg_uri("VBB_Bahn-Regionalverkehr.svg", title="Regionalexpress"),
    "IC":         _svg_uri("IC-Logo.svg",  scale=0.90,    title="InterCity"),
    "ICE":        _svg_uri("ICE-Logo.svg", scale=0.90,    title="InterCityExpress"),
}

# German: 1.234 · 12,3 % · 4,5 — English: 1,234 · 12.3% · 4.5
def _fmt_int(n) -> str:
    s = f"{int(n):,}"
    return s if LANG == "en" else s.replace(",", ".")

def _fmt_pct(p) -> str:
    return f"{p:.1f}%" if LANG == "en" else f"{p:.1f}".replace(".", ",") + " %"

def _fmt_float(v, decimals=1) -> str:
    s = f"{v:.{decimals}f}"
    return s if LANG == "en" else s.replace(".", ",")

# Single source of truth for the 12 Berlin Bezirke colours, shared by the rent
# chart (Bevölkerung tab) and the crime charts so a Bezirk is never two colours.
BEZIRK_COLOURS = {
    "Charlottenburg-Wilmersdorf": "#1E88E5",
    "Friedrichshain-Kreuzberg":   "#43A047",
    "Lichtenberg":                "#8E24AA",
    "Marzahn-Hellersdorf":        "#00ACC1",
    "Mitte":                      "#C0504D",
    "Neukölln":                   "#FB8C00",
    "Pankow":                     "#6D4C41",
    "Reinickendorf":              "#546E7A",
    "Spandau":                    "#F4511E",
    "Steglitz-Zehlendorf":        "#039BE5",
    "Tempelhof-Schöneberg":       "#7CB342",
    "Treptow-Köpenick":           "#FFB300",
}
# Berlin-wide median is not a Bezirk; rendered as a neutral reference line.
BERLIN_MEDIAN_COLOUR = "#9E9E9E"

def _metrics_2col(items):
    cells = ""
    for item in items:
        delta_html = ""
        if item.get("delta"):
            c = item.get("delta_colour", "#808495")
            delta_html = ('<div style="font-size:0.8rem;color:' + c + ';margin-top:2px">' + item["delta"] + '</div>')
        note_html = ('<div style="font-size:0.8rem;margin-top:2px">' + item["note_html"] + '</div>') if item.get("note_html") else ""
        cells += (
            '<div style="padding:0.4rem 0">'
            + '<div style="font-size:0.8rem;color:rgba(250,250,250,0.6)">' + item["label"] + '</div>'
            + '<div style="font-size:1.75rem;font-weight:600;line-height:1.2;color:#fafafa">' + str(item["value"]) + '</div>'
            + delta_html + note_html
            + '</div>'
        )
    st.html('<div style="display:grid;grid-template-columns:1fr 1fr;gap:0.25rem 1rem;padding:0.25rem 0">' + cells + '</div>')

HBF_STOP_ID = "900003201"
_HAFAS_URL = "https://fahrinfo.vbb.de/bin/mgate.exe"
_HAFAS_BODY = {
    "client": {"id": "VBB", "v": "6000300", "type": "WEB", "name": "webapp"},
    "ver": "1.42",
    "auth": {"type": "AID", "aid": "hafas-vbb-apps"},
    "lang": "de",
}

def _hhmm_to_minutes(s):
    return int(s[:2]) * 60 + int(s[2:4])

def _station_board(stop_id, results, mode, dir_label, time_label):
    """Fetch a HAFAS station board.

    `mode` is "ARR" or "DEP"; the response uses a matching a*/d* field prefix.
    `dir_label` / `time_label` name the two columns that differ between the two
    boards ("Herkunft"/"Ankunft" vs "Richtung"/"Abfahrt").
    """
    p = "a" if mode == "ARR" else "d"
    body = {
        **_HAFAS_BODY,
        "svcReqL": [{"meth": "StationBoard", "req": {
            "stbLoc": {"lid": f"A=1@L={stop_id}@", "type": "S"},
            "type": mode,
            "maxJny": results,
        }}],
    }
    r = requests.post(_HAFAS_URL, json=body, timeout=10)
    r.raise_for_status()
    svc = r.json()["svcResL"][0]
    if svc.get("err", "OK") != "OK" or "res" not in svc:
        return []
    res   = svc["res"]
    prods = res["common"]["prodL"]
    rows  = []
    for j in res.get("jnyL", []):
        prod     = prods[j.get("prodX", 0)]
        name     = prod.get("name") or "?"
        cat      = prod.get("prodCtx", {}).get("catOut", "").strip()
        stop     = j.get("stbStop", {})
        t_plan   = stop.get(f"{p}TimeS", "")
        t_real   = stop.get(f"{p}TimeR", t_plan)
        platform = stop.get(f"{p}PltfR", stop.get(f"{p}PltfS", {})).get("txt", "—")
        time_str = f"{t_plan[:2]}:{t_plan[2:4]}" if len(t_plan) >= 4 else "—"
        if t_plan and t_real and t_real != t_plan and len(t_real) >= 4:
            diff = _hhmm_to_minutes(t_real) - _hhmm_to_minutes(t_plan)
            if diff < -720:
                diff += 1440  # midnight rollover
            delay_str = f"+{diff} min" if diff > 0 else ("pünktlich" if diff == 0 else f"{diff} min")
        else:
            delay_str = "pünktlich"
        rows.append({
            "Icon":       _TYPE_ICON.get(cat, ""),
            "Linie":      name,
            "Typ":        cat,
            dir_label:    j.get("dirTxt") or "?",
            "Gleis":      platform,
            time_label:   time_str,
            "Verspätung": delay_str,
        })
    return rows


@st.cache_data(ttl=60)
def fetch_arrivals(stop_id=HBF_STOP_ID, results=25):
    return _station_board(stop_id, results, "ARR", "Herkunft", "Ankunft")


@st.cache_data(ttl=60)
def fetch_departures(stop_id=HBF_STOP_ID, results=25):
    return _station_board(stop_id, results, "DEP", "Richtung", "Abfahrt")

st.sidebar.title(tr("Ebenen", "Layers"))
show_routes = st.sidebar.checkbox(tr("Verkehrslinien", "Public transport lines"), value=True, key="lyr_routes")
show_routes_full = False
if show_routes:
    legend_html = "".join(
        f'<span style="color:{colour}"><b>&#11834;</b></span> {label}<br>'
        for label, colour in ROUTE_LEGEND.items()
    )
    st.sidebar.markdown(f"<small>{legend_html}</small>", unsafe_allow_html=True)
    show_transport = st.sidebar.checkbox(tr("Haltestellen", "Stops"), value=True, key="lyr_stops")
    show_routes_full = st.sidebar.checkbox(tr("Vollständige Linien (außerhalb Moabits)", "Full routes (beyond Moabit)"),
                                           value=False, key="lyr_routes_full")
else:
    show_transport = False
st.sidebar.markdown("<hr style='margin:4px 0'>", unsafe_allow_html=True)
show_cycling = st.sidebar.checkbox(tr("Radwege", "Cycle lanes"), value=False, key="lyr_cycling")
if show_cycling:
    legend_html = "".join(
        f'<span style="color:{colour}"><b>&#11834;</b></span> {trl(label)}<br>'
        for label, colour in CYCLE_LEGEND.items()
    )
    st.sidebar.markdown(f"<small>{legend_html}</small>", unsafe_allow_html=True)
show_bikeshare = st.sidebar.checkbox(tr("Leihräder", "Bike share"), value=False, key="lyr_bikeshare")
if show_bikeshare:
    st.sidebar.markdown(
        "<small>"
        f'<span style="color:green">&#9679;</span> {tr("Räder verfügbar", "Bikes available")}<br>'
        f'<span style="color:orange">&#9679;</span> {tr("Wenige Räder (1–2)", "Few bikes (1–2)")}<br>'
        f'<span style="color:red">&#9679;</span> {tr("Keine Räder", "No bikes")}'
        "</small>",
        unsafe_allow_html=True,
    )
st.sidebar.markdown("<hr style='margin:4px 0'>", unsafe_allow_html=True)
show_wohnlagen = st.sidebar.checkbox(tr("Wohnlagenkarte", "Residential area rating"), value=False, key="lyr_wohnlagen")
if show_wohnlagen:
    legend_html = "".join(
        f'<span style="color:{v["colour"]}">&#9632;</span> {trl(v["label"])}<br>'
        for v in [WOL_STYLE["gut"], WOL_STYLE["mittel"], WOL_STYLE["einfach"]]
    )
    st.sidebar.markdown(f"<small>{legend_html}</small>", unsafe_allow_html=True)
show_amenities = st.sidebar.checkbox(tr("Nahversorgung", "Local amenities"), value=False, key="lyr_amenities")
if show_amenities:
    legend_html = "".join(
        f'<span style="color:{colour}">&#9632;</span> {trl(label)}<br>'
        for label, colour in AMENITY_LEGEND.items()
    )
    st.sidebar.markdown(f"<small>{legend_html}</small>", unsafe_allow_html=True)
st.sidebar.markdown("<hr style='margin:4px 0'>", unsafe_allow_html=True)
show_greenspaces = st.sidebar.checkbox(tr("Grünflächen", "Green spaces"), value=False, key="lyr_greenspaces")
if show_greenspaces:
    legend_html = "".join(
        f'<span style="color:{colour}">&#9632;</span> {trl(label)}<br>'
        for label, colour in GREEN_LEGEND.items()
    )
    st.sidebar.markdown(f"<small>{legend_html}</small>", unsafe_allow_html=True)
show_trees = st.sidebar.checkbox(tr("Bäume", "Trees"), value=False, key="lyr_trees")
if show_trees:
    legend_html = "".join(
        f'<span style="color:{t["colour"]}">&#9679;</span> {trl(t["label"])}<br>'
        for t in TREE_TYPES.values()
    )
    st.sidebar.markdown(
        f"<small>{legend_html}{tr('Quelle: Baumbestand Berlin (GRIS)', 'Source: Berlin tree register (GRIS)')}</small>",
        unsafe_allow_html=True,
    )
show_airquality = st.sidebar.checkbox(tr("Luftqualität", "Air quality"), value=False, key="lyr_airquality")
show_noise = st.sidebar.checkbox(tr("Lärmkarte", "Noise map"), value=False, key="lyr_noise")
noise_year = "2022"
noise_layer = NOISE_WMS_LAYERS[("Gesamt", "24 h")]
if show_noise:
    noise_year = st.sidebar.radio(tr("Jahr", "Year"), ["2022", "2004"], horizontal=True, key="noise_year")
    # Option values stay German (they key the WMS_LAYERS dicts); only the display is
    # translated. Each year has its own option set, hence separate widget keys.
    if noise_year == "2022":
        noise_source = st.sidebar.radio(tr("Quelle", "Source"), ["Gesamt", "Straße", "Tram & U-Bahn"],
                                        format_func=trl, key="noise_source")
        noise_time   = st.sidebar.radio(tr("Zeit", "Time"), ["24 h", "Nacht"], format_func=trl,
                                        horizontal=True, key="noise_time")
        noise_layer  = NOISE_WMS_LAYERS[(noise_source, noise_time)]
        _metric = "L<sub>DEN</sub>" if noise_time == "24 h" else "L<sub>N</sub> " + tr("(22–6 Uhr)", "(10 pm–6 am)")
        _bands = NOISE_LEGEND[noise_time]
        # The lowest class is transparent on the map (see layers.noise.sld_body),
        # so the legend says so instead of showing the official white swatch.
        _noise_items = [("none", None, f"{_bands[0][0]} dB(A) ({tr('nicht eingefärbt', 'not coloured')})")] + [
            ("box", colour, f"{band} dB(A)") for band, colour in _bands[1:]
        ]
        _noise_source_line = tr("Quelle: Strategische Lärmkarten Berlin 2022", "Source: Berlin strategic noise maps 2022")
    else:
        noise_source = st.sidebar.radio(tr("Quelle", "Source"), ["Straße", "Schiene"],
                                        format_func=trl, horizontal=True, key="noise_source_2004")
        noise_time   = st.sidebar.radio(tr("Zeit", "Time"), ["Tag", "Nacht"], format_func=trl,
                                        horizontal=True, key="noise_time_2004")
        noise_layer  = NOISE04_WMS_LAYERS[(noise_source, noise_time)]
        _metric = tr("Tag (6–22 Uhr)", "Day (6 am–10 pm)") if noise_time == "Tag" else tr("Nacht (22–6 Uhr)", "Night (10 pm–6 am)")
        _noise_items = [("line", colour, f"{band} dB(A)") for band, colour in NOISE04_LEGEND] + [
            ("line", NOISE04_UNRATED, tr("ohne Bewertung", "not rated"))
        ]
        _noise_source_line = tr("Quelle: Umweltatlas Berlin 2004", "Source: Berlin Environmental Atlas 2004")
    st.sidebar.markdown(
        f"<small>{_metric}{_legend_rows_html(_noise_items)}{_noise_source_line}</small>",
        unsafe_allow_html=True,
    )
    # Same legend on the map, next to the colours it explains.
    _map_legend_html = (
        '<div style="background:rgba(14,17,23,0.88);color:#fafafa;padding:6px 9px;border-radius:6px;'
        f'font:{11 if _is_mobile else 12}px/1.45 sans-serif;box-shadow:0 1px 4px rgba(0,0,0,0.5)">'
        f'<div style="font-weight:600;margin-bottom:2px">{tr("Lärm", "Noise")} {noise_year} · {_metric}</div>'
        f"{_legend_rows_html(_noise_items)}</div>"
    )

# --- Tabs ---
tab_map, tab_departures, tab_arrivals, tab_demographics, tab_umwelt, tab_crime, tab_about = st.tabs([
    tr("Karte", "Map"),
    tr("Abfahrten Berlin Hbf", "Departures Berlin Hbf"),
    tr("Ankünfte Berlin Hbf", "Arrivals Berlin Hbf"),
    tr("Bevölkerung", "Population"),
    tr("Umwelt", "Environment"),
    tr("Kriminalität", "Crime"),
    tr("Über Moabit", "About Moabit"),
])

# --- Map tab ---
with tab_map:
    if show_transport:
        with st.spinner(tr("Lade ÖPNV-Daten...", "Loading public transport data…")):
            stops = get_stops()

    if show_cycling:
        with st.spinner(tr("Lade Radwege...", "Loading cycle lanes…")):
            lanes = get_lanes()

    if show_bikeshare:
        with st.spinner(tr("Lade Leihrad-Daten...", "Loading bike share data…")):
            bikeshare_stations = get_bikeshare_stations()

    if show_wohnlagen:
        with st.spinner(tr("Lade Wohnlagenkarte...", "Loading residential area ratings…")):
            wohnlagen = get_wohnlagen()

    if show_greenspaces:
        with st.spinner(tr("Lade Grünflächen...", "Loading green spaces…")):
            greenspaces = get_greenspaces()

    if show_trees:
        with st.spinner(tr("Lade Baumbestand...", "Loading trees…")):
            trees = get_trees()

    if show_amenities:
        with st.spinner(tr("Lade Nahversorgung...", "Loading local amenities…")):
            amenities = get_amenities()

    if show_routes:
        if show_routes_full:
            with st.spinner(tr("Lade vollständige Linien...", "Loading full routes…")):
                routes = get_routes_full()
        else:
            with st.spinner(tr("Lade Verkehrslinien...", "Loading public transport lines…")):
                routes = get_routes()

    # Computed fresh on every run, not stored: the previous version decremented a
    # zoom kept in session state each time air quality was switched on and never
    # restored it, so the map zoomed out one more level with every toggle.
    _map_centre = [52.529, 13.341]
    _base_zoom = 13 if _is_mobile else 14
    # One level out while air quality is on, so the Wedding station is in view.
    # Passed to st_folium(zoom=...), which applies it only when it changes, so it
    # neither rebuilds the map nor overrides the user's zoom on other reruns.
    _map_zoom = _base_zoom - 1 if show_airquality else _base_zoom

    # CARTO basemap tiles need an API key (free for non-commercial use up to
    # 5M requests/month, see carto.com/basemaps/apikey). The key lives in
    # Streamlit secrets — .streamlit/secrets.toml locally (gitignored), App
    # settings → Secrets on Streamlit Cloud — never in the repo. Without a key
    # CARTO serves an "API KEY REQUIRED" watermark, so fall back to keyless
    # OpenStreetMap tiles instead: light rather than dark, but a working map.
    try:
        _carto_key = st.secrets.get("CARTO_API_KEY", "")
    except Exception:  # no secrets file at all
        _carto_key = ""
    if _carto_key:
        _basemap = dict(
            tiles=f"https://basemaps.cartocdn.com/rastertiles/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png?key={_carto_key}",
            attr='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors '
                 '&copy; <a href="https://carto.com/attribution/">CARTO</a>',
        )
    else:
        _basemap = dict(tiles="OpenStreetMap")

    m = folium.Map(
        location=_map_centre,
        zoom_start=_base_zoom,
        **_basemap,
    )

    folium.GeoJson(
        boundary,
        style_function=lambda _: {
            "color": "#43A047",
            "weight": 2.5,
            "fillColor": "#43A047",
            "fillOpacity": 0.08,
        }
    ).add_to(m)

    # Optional layers go into feature groups passed to st_folium(feature_group_to_add=...).
    # st_folium identifies the map by a hash of the *base* map's script; while that
    # stays identical it swaps the feature groups inside the existing Leaflet map
    # instead of rebuilding it, so pan and zoom survive layer toggles and the noise
    # year switch. Only what never changes belongs on `m` itself.
    _layers = []

    def _fg(name):
        fg = folium.FeatureGroup(name=name)
        _layers.append(fg)
        return fg

    # Plugin scripts are only loaded on the map's first render, so the marker-
    # cluster script (stops, trees) must be part of the base map from the start.
    MarkerCluster(name="_cluster_script").add_to(m)

    if show_greenspaces:
        _g = _fg("Grünflächen")
        # Tooltip shows a translated label rather than the raw OSM value in "type".
        _green_features = [
            {**f, "properties": {**f["properties"],
                                 "type_label": trl(GREEN_TYPE_LABELS.get(f["properties"].get("type", ""),
                                                                         f["properties"].get("type", "")))}}
            for f in greenspaces
        ]
        folium.GeoJson(
            {"type": "FeatureCollection", "features": _green_features},
            style_function=lambda f: FEATURE_STYLE.get(
                f["properties"].get("type", ""),
                {"color": "#43A047", "fillColor": "#43A047", "fillOpacity": 0.3, "weight": 1}
            ),
            tooltip=folium.GeoJsonTooltip(
                fields=["name", "type_label"],
                aliases=["Name:", tr("Typ:", "Type:")],
            ),
        ).add_to(_g)

    if show_amenities:
        _g = _fg("Nahversorgung")
        for feature in amenities:
            amenity = feature["amenity"]
            style = AMENITY_STYLE.get(amenity, {"colour": "#888888", "label": amenity})
            name = feature["name"] or trl(style["label"])
            tooltip = f"{name}<br>{feature['address']}" if feature["address"] else name
            folium.CircleMarker(
                location=[feature["lat"], feature["lon"]],
                radius=6,
                color=style["colour"],
                fill=True,
                fill_color=style["colour"],
                fill_opacity=0.9,
                weight=1.5,
                tooltip=tooltip,
            ).add_to(_g)

    if show_routes:
        _g = _fg("Verkehrslinien")
        # Resolve from ROUTE_STYLE rather than the "colour"/"weight"/"opacity"
        # baked into routes.json, so the committed caches stay geometry and a
        # palette change takes effect without regenerating them.
        def _route_style(f):
            return ROUTE_STYLE.get(f["properties"].get("route", "bus"), ROUTE_STYLE["bus"])

        folium.GeoJson(
            {"type": "FeatureCollection", "features": routes},
            style_function=lambda f: {
                "color":   _route_style(f)["colour"],
                "weight":  _route_style(f)["weight"],
                "opacity": _route_style(f)["opacity"],
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["ref", "name"],
                aliases=[tr("Linie:", "Line:"), "Route:"],
            ),
        ).add_to(_g)

    if show_cycling:
        _g = _fg("Radwege")
        cycle_features = []
        for el in lanes:
            if el.get("type") != "way" or "geometry" not in el:
                continue
            tags = el.get("tags", {})
            coords = [[n["lon"], n["lat"]] for n in el["geometry"]]
            cycle_features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "color": lane_style(tags),
                    "name": tags.get("name") or tr("Radweg", "Cycle lane"),
                }
            })
        folium.GeoJson(
            {"type": "FeatureCollection", "features": cycle_features},
            style_function=lambda f: {
                "color":   f["properties"]["color"],
                "weight":  3,
                "opacity": 0.8,
            },
            tooltip=folium.GeoJsonTooltip(fields=["name"], aliases=[tr("Radweg:", "Cycle lane:")]),
        ).add_to(_g)

    if show_bikeshare:
        _g = _fg("Leihräder")
        for station in bikeshare_stations:
            folium.Marker(
                location=[station["lat"], station["lon"]],
                icon=folium.Icon(color=station["colour"], icon="bicycle", prefix="fa"),
                tooltip=folium.Tooltip(
                    f"<span style='font-size:15px'>"
                    f"<b>{station['name']}</b><br>"
                    f"{tr('Fahrräder verfügbar', 'Bikes available')}: {station['bikes']}<br>"
                    f"{tr('Stellplätze frei', 'Free docks')}: {station['docks']}<br>"
                    f"{tr('Kapazität', 'Capacity')}: {station['capacity']}"
                    f"</span>"
                ),
            ).add_to(_g)

    if show_wohnlagen:
        _g = _fg("Wohnlagen")
        wol_colours = {k: v["colour"] for k, v in WOL_STYLE.items()}

        _wol_features = [
            {**f, "properties": {**f["properties"],
                                 "wol_label": trl(WOL_STYLE.get(f["properties"].get("wol", ""), {}).get(
                                     "label", f["properties"].get("wol", "")))}}
            for f in wohnlagen
        ]
        folium.GeoJson(
            {"type": "FeatureCollection", "features": _wol_features},
            style_function=lambda feature: {
                "radius": 4,
                "color": wol_colours.get(feature["properties"].get("wol", ""), "#888888"),
                "fillColor": wol_colours.get(feature["properties"].get("wol", ""), "#888888"),
                "fillOpacity": 0.7,
                "weight": 0,
            },
            marker=folium.CircleMarker(radius=4, weight=0, fill=True, fill_opacity=0.7),
            tooltip=folium.GeoJsonTooltip(
                fields=["strasse", "hnr", "wol_label"],
                aliases=[tr("Straße:", "Street:"), tr("Nr.:", "No.:"), tr("Wohnlage:", "Rating:")],
            ),
        ).add_to(_g)

    if show_transport:
        _g = _fg("Haltestellen")
        cluster = MarkerCluster(name="Transport stops").add_to(_g)
        for stop in stops:
            name   = stop["name"]
            style  = stop_style(stop)
            folium.Marker(
                location=[stop["lat"], stop["lon"]],
                tooltip=name,
                icon=folium.Icon(color=style["color"], icon=style["icon"], prefix="fa"),
            ).add_to(cluster)

    if "selected_stop" not in st.session_state:
        st.session_state.selected_stop = None

    if show_airquality:
        _g = _fg("Luftqualität")
        with st.spinner(tr("Lade Luftqualitätsdaten...", "Loading air quality data…")):
            aq_current = get_airquality_current()
        readings = "<br>".join(
            f"{label}: {_fmt_float(v['value']) if isinstance(v['value'], float) else v['value']} {v['unit']}"
            for label, v in aq_current.items()
        )
        folium.Marker(
            location=[STATION_LAT, STATION_LON],
            icon=folium.Icon(color="lightgray", icon="cloud", prefix="fa"),
            tooltip=folium.Tooltip(
                f"<span style='font-size:15px'>"
                f"<b>{STATION_NAME}</b><br>{readings}"
                f"</span>"
            ),
        ).add_to(_g)
        for s in MOABIT_STATIONS:
            folium.Marker(
                location=[s["lat"], s["lon"]],
                icon=folium.Icon(color="lightgray", icon="cloud", prefix="fa"),
                tooltip=folium.Tooltip(
                    "<span style='font-size:15px'>"
                    "<b>" + s['name'] + "</b>"
                    "<br>" + s['years'] + " · " + tr("Keine Daten verfügbar", "No data available") +
                    "</span>"
                ),
            ).add_to(_g)

    if show_noise and noise_year == "2022":
        _g = _fg("Lärm 2022")
        folium.WmsTileLayer(
            # sld_body goes in the base URL: folium camelCases keyword options
            # (sld_body -> sldBody), which the server silently ignores.
            url=f"{NOISE_WMS_URL}?sld_body={quote(noise_sld_body(noise_layer))}",
            layers=noise_layer,
            fmt="image/png",
            transparent=True,
            version="1.3.0",
            attr=tr("Strategische Lärmkarten Berlin 2022", "Berlin strategic noise maps 2022"),
            opacity=0.7,
        ).add_to(_g)
        _MapLegend(_map_legend_html).add_to(_g)
    elif show_noise:
        _g = _fg("Lärm 2004")
        # 2004 is drawn as coloured street/rail lines on a transparent background,
        # so it needs no restyling.
        folium.WmsTileLayer(
            url=NOISE04_WMS_URL,
            layers=noise_layer,
            fmt="image/png",
            transparent=True,
            version="1.3.0",
            attr=tr("Umweltatlas Berlin 2004", "Berlin Environmental Atlas 2004"),
            opacity=0.8,
        ).add_to(_g)
        _MapLegend(_map_legend_html).add_to(_g)

    if show_trees:
        _g = _fg("Bäume")
        # folium wraps a custom callback as `var callback = <fn>;`, so pass the bare function.
        # ~10,000 trees: FastMarkerCluster ships the rows as one array and builds
        # the markers in the browser, which stays responsive where one Python
        # folium.Marker per tree would not. Row layout: layers.trees.FIELDS.
        _tree_colours = json.dumps({k: v["colour"] for k, v in TREE_TYPES.items()})
        _tree_labels = json.dumps({k: trl(v["label"]) for k, v in TREE_TYPES.items()}, ensure_ascii=False)
        _tw = {
            "planted": tr("Gepflanzt", "Planted"), "years": tr("Jahre", "years"),
            "height": tr("Höhe", "Height"), "trunk": tr("Stamm", "Girth"), "crown": tr("Krone", "Crown"),
        }
        _tree_callback = (
            "function (row) {"
            "  var esc = function (v) { return String(v).replace(/[&<>\"]/g, function (c) {"
            "    return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;'}[c]; }); };"
            f"  var colours = {_tree_colours}, labels = {_tree_labels};"
            "  var c = colours[row[2]];"
            "  var m = L.circleMarker(new L.LatLng(row[0], row[1]),"
            "    {radius: 5, color: c, fillColor: c, fillOpacity: 0.85, weight: 1});"
            "  var h = '<span style=\"font-size:14px\"><b>' + esc(row[3]) + '</b>';"
            "  if (row[4]) h += '<br><i>' + esc(row[4]) + '</i>';"
            f"  if (row[5]) h += '<br>{_tw['planted']} ' + row[5] + ' (' + (new Date().getFullYear() - row[5]) + ' {_tw['years']})';"
            "  var dims = [];"
            f"  if (row[6]) dims.push('{_tw['height']} ' + row[6] + ' m');"
            f"  if (row[7]) dims.push('{_tw['trunk']} ' + row[7] + ' cm');"
            f"  if (row[8]) dims.push('{_tw['crown']} ' + row[8] + ' m');"
            "  if (dims.length) h += '<br>' + dims.join(' · ');"
            "  if (row[9]) h += '<br>' + esc(row[9]) + (row[10] ? ' ' + esc(row[10]) : '');"
            "  h += '<br><small>' + labels[row[2]] + '</small></span>';"
            "  m.bindTooltip(h);"
            "  return m;"
            "}"
        )
        # Green cluster bubbles, so tree clusters can't be mistaken for the
        # transport-stop clusters (Leaflet's default green/yellow/orange).
        _tree_cluster_icon = (
            "function (cluster) {"
            "  var n = cluster.getChildCount();"
            "  var size = n < 100 ? 30 : n < 1000 ? 38 : 46;"
            "  return L.divIcon({"
            "    html: '<div style=\"width:' + size + 'px;height:' + size + 'px;line-height:' + size + 'px;'"
            "      + 'border-radius:50%;background:rgba(67,160,71,0.85);border:2px solid #B6E880;'"
            "      + 'color:#fff;font:bold 12px sans-serif;text-align:center\">' + n + '</div>',"
            "    className: 'tree-cluster', iconSize: L.point(size, size)});"
            "}"
        )
        FastMarkerCluster(
            data=[r[:3] + [tr_species(r[3])] + r[4:] for r in trees] if LANG == "en" else trees,
            callback=_tree_callback,
            icon_create_function=_tree_cluster_icon,
            options={"disableClusteringAtZoom": 18, "chunkedLoading": True, "showCoverageOnHover": False},
            name="Bäume",
        ).add_to(_g)

    LocateControl(
        auto_start=False,
        strings={"title": tr("Meinen Standort anzeigen", "Show my location")},
    ).add_to(m)

    map_data = st_folium(
        m,
        use_container_width=True,
        height=350 if _is_mobile else 500,
        # Deliberately NOT requesting "center"/"zoom". st_folium reruns the script
        # whenever a requested value changes, so asking for the viewport means a
        # rerun on every map movement — and because Leaflet re-reports a slightly
        # different centre after the map is rebuilt at a rounded one, that feeds
        # back on itself and the map refreshes continuously. Persisting the
        # viewport and not rerunning are mutually exclusive with this component,
        # so the map resets to the default view when the script reruns.
        returned_objects=["last_object_clicked"],
        feature_group_to_add=_layers or None,
        zoom=_map_zoom,
        key="moabit_map",
    )

    if show_transport and map_data.get("last_object_clicked"):
        click = map_data["last_object_clicked"]
        clat, clng = click.get("lat"), click.get("lng")
        if clat and clng:
            matched = min(stops, key=lambda s: (s["lat"] - clat) ** 2 + (s["lon"] - clng) ** 2)
            dist = ((matched["lat"] - clat) ** 2 + (matched["lon"] - clng) ** 2) ** 0.5
            if dist < 0.002:
                st.session_state.selected_stop = matched

    if show_transport and st.session_state.selected_stop:
        sel = st.session_state.selected_stop
        st.markdown(f"**{sel['name']}** – {tr('nächste Abfahrten', 'next departures')}")
        with st.spinner(tr("Lade Abfahrtsdaten...", "Loading departures…")):
            try:
                rows = fetch_departures(stop_id=sel["id"], results=12)
            except Exception as e:
                rows = []
                st.error(tr("Abfahrtsdaten konnten nicht geladen werden", "Could not load departures") + f": {e}")
        if not rows:
            st.caption(tr("Keine Abfahrtsdaten für diese Haltestelle verfügbar.",
                          "No departure data available for this stop."))
        else:
            if _is_mobile:
                df_stop = pd.DataFrame([
                    {tr("Linie", "Line"): r["Linie"], tr("Richtung", "Destination"): r["Richtung"],
                     tr("Abfahrt", "Departs"): r["Abfahrt"], tr("Versp.", "Delay"): _tr_delay(r["Verspätung"])}
                    for r in rows
                ])
                st.table(df_stop)
            else:
                st.dataframe(
                    [{**r, "Verspätung": _tr_delay(r["Verspätung"])} for r in rows],
                    width="stretch",
                    hide_index=True,
                    height="content",
                    column_order=["Icon", "Linie", "Typ", "Richtung", "Abfahrt", "Verspätung"],
                    column_config={
                        "Icon":       st.column_config.ImageColumn("", width="small"),
                        "Linie":      st.column_config.TextColumn(tr("Linie", "Line"),             width="small"),
                        "Typ":        st.column_config.TextColumn(tr("Typ", "Type"),               width="small"),
                        "Richtung":   st.column_config.TextColumn(tr("Richtung", "Destination")),
                        "Abfahrt":    st.column_config.TextColumn(tr("Abfahrt", "Departs"),        width="small"),
                        "Verspätung": st.column_config.TextColumn(tr("Verspätung", "Delay"),       width="small"),
                    },
                )

# --- Demographics tab ---
with tab_demographics:
    trend = get_population_over_time()

    _latest_year = int(trend.iloc[-1]["year"]) if not trend.empty else 2025
    st.caption(tr(f"Quelle: Amt für Statistik Berlin-Brandenburg, Einwohnerregisterstatistik 31.12.{_latest_year}",
                  f"Source: Statistical Office for Berlin-Brandenburg, population register, 31 December {_latest_year}"))

    # --- Headline metrics ---
    if not trend.empty:
        latest = trend.iloc[-1]
        if _is_mobile:
            _metrics_2col([
                {"label": tr("Einwohner", "Residents"),                  "value": _fmt_int(latest['total'])},
                {"label": tr("Frauenanteil", "Share of women"),          "value": _fmt_pct(latest['female_pct'])},
                {"label": tr("Ausländeranteil", "Foreign nationals"),     "value": _fmt_pct(latest['foreign_pct'])},
                {"label": tr("18- bis 44-Jährige", "Aged 18 to 44"),     "value": _fmt_pct(latest['young_adult_pct'])},
            ])
        else:
            col1, col2, col3, col4 = st.columns(4)
            col1.metric(tr("Einwohner", "Residents"),              _fmt_int(latest['total']))
            col2.metric(tr("Frauenanteil", "Share of women"),      _fmt_pct(latest['female_pct']))
            col3.metric(tr("Ausländeranteil", "Foreign nationals"), _fmt_pct(latest['foreign_pct']))
            col4.metric(tr("18- bis 44-Jährige", "Aged 18 to 44"), _fmt_pct(latest['young_adult_pct']))

    st.divider()

    # --- Age distribution and population trend side by side ---
    if not trend.empty:
        age_years = sorted(trend["year"].tolist())
        col_sel, _ = st.columns([1, 3])
        with col_sel:
            selected_age_year = st.selectbox(
                tr("Jahr", "Year"), options=age_years, index=len(age_years) - 1,
                key="age_year"
            )
        age_row = trend[trend["year"] == selected_age_year].iloc[0]
        age_data = {
            tr("unter 6", "under 6"):  int(age_row["u6"]),
            "6–14":     int(age_row["6_15"]),
            "15–17":    int(age_row["15_18"]),
            "18–26":    int(age_row["18_27"]),
            "27–44":    int(age_row["27_45"]),
            "45–54":    int(age_row["45_55"]),
            "55–64":    int(age_row["55_65"]),
            "65+":      int(age_row["65plus"]),
        }
        title_year = selected_age_year
    else:
        age_data = {}
        title_year = "–"

    if _is_mobile:
        col_age, col_pop = st.container(), st.container()
    else:
        col_age, col_pop = st.columns(2)

    with col_age:
        st.subheader(tr("Bevölkerung nach Altersgruppe", "Population by age group") + f" ({title_year})")
        if _is_mobile:
            fig_age = go.Figure(go.Bar(
                x=list(age_data.keys()),
                y=list(age_data.values()),
                marker_color="#1E88E5",
                text=[_fmt_int(v) for v in age_data.values()],
                textposition="outside",
            ))
            fig_age.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)"),
                xaxis_title=tr("Altersgruppe", "Age group"),
                yaxis_title=tr("Bevölkerung", "Population"),
                margin=dict(t=20, b=20),
                height=320,
            )
        else:
            fig_age = go.Figure(go.Bar(
                x=list(age_data.values()),
                y=list(age_data.keys()),
                orientation="h",
                marker_color="#1E88E5",
                text=[_fmt_int(v) for v in age_data.values()],
                textposition="outside",
            ))
            fig_age.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)"),
                xaxis_title=tr("Bevölkerung", "Population"),
                yaxis_title=tr("Altersgruppe", "Age group"),
                margin=dict(t=20, b=20, r=60),
            )
        st.plotly_chart(fig_age, width="stretch", config=_plot_config)

    _yr0, _yr1 = "–", "–"
    with col_pop:
        if not trend.empty:
            first, last = trend.iloc[0]["total"], trend.iloc[-1]["total"]
            pct = (last - first) / first * 100
            direction = tr("Anstieg", "An increase") if pct > 0 else tr("Rückgang", "A decrease")
            _yr0, _yr1 = int(trend.iloc[0]["year"]), int(trend.iloc[-1]["year"])
            st.subheader(tr("Bevölkerungsentwicklung", "Population trend") + f" {_yr0}–{_yr1}")
            fig_pop = go.Figure(go.Scatter(
                x=trend["year"], y=trend["total"],
                mode="lines+markers+text",
                line=dict(color="#1E88E5", width=2.5),
                marker=dict(size=8, color="#1E88E5"),
                text=[_fmt_int(v) for v in trend["total"]],
                textposition="top center",
                textfont=dict(size=11),
            ))
            fig_pop.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)"),
                xaxis=dict(tickmode="linear", dtick=1),
                xaxis_title=tr("Jahr", "Year"),
                yaxis_title=tr("Bevölkerung", "Population"),
                margin=dict(t=20, b=20),
            )
            st.plotly_chart(fig_pop, width="stretch", config=_plot_config)
            st.caption(
                tr(
                    f"{direction} um {_fmt_pct(abs(pct))} zwischen {_yr0} ({_fmt_int(first)} Einwohner) "
                    f"und {_yr1} ({_fmt_int(last)} Einwohner). "
                    "Die Zeitreihe beginnt 2021, da Berlins LOR-Planungsraumbezirke am 1. Januar 2021 "
                    "neu strukturiert wurden und ältere Daten für Moabits Planungsräume nicht vergleichbar sind.",
                    f"{direction} of {_fmt_pct(abs(pct))} between {_yr0} ({_fmt_int(first)} residents) "
                    f"and {_yr1} ({_fmt_int(last)} residents). "
                    "The series starts in 2021 because Berlin's LOR planning areas were restructured on "
                    "1 January 2021, so older figures for Moabit's planning areas are not comparable."
                )
            )

    if not trend.empty:
        st.divider()

        if _is_mobile:
            col_stack, col_comp = st.container(), st.container()
        else:
            col_stack, col_comp = st.columns(2)

        # --- Age structure shift (stacked bar) ---
        with col_stack:
            st.subheader(tr("Altersstruktur im Zeitverlauf", "Age structure over time"))
            age_cols = {
                tr("unter 6", "under 6"):  ("u6",     "#FFB300", 8),
                "6–14":     ("6_15",   "#7CB342", 7),
                "15–17":    ("15_18",  "#43A047", 6),
                "18–26":    ("18_27",  "#1E88E5", 5),
                "27–44":    ("27_45",  "#636EFA", 4),
                "45–54":    ("45_55",  "#8E24AA", 3),
                "55–64":    ("55_65",  "#FF6692", 2),
                "65+":      ("65plus", "#C0504D", 1),
            }
            fig_stack = go.Figure()
            for label, (col, color, rank) in age_cols.items():
                fig_stack.add_trace(go.Bar(
                    name=label,
                    x=trend["year"],
                    y=trend[col],
                    marker_color=color,
                    legendrank=rank,
                ))
            fig_stack.update_layout(
                barmode="stack",
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)"),
                xaxis=dict(tickmode="linear", dtick=1),
                xaxis_title=tr("Jahr", "Year"),
                yaxis_title=tr("Bevölkerung", "Population"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                margin=dict(t=40, b=20),
                height=420,
            )
            st.plotly_chart(fig_stack, width="stretch", config=_plot_config)

        # --- Population composition over time ---
        with col_comp:
            st.subheader(tr("Bevölkerungszusammensetzung", "Population composition") + f" (%, {_yr0}–{_yr1})")
            mig_trend = get_migration_over_time()
            fig_ratios = go.Figure()
            ratio_series = {
                tr("Mit Migrationshintergrund", "With migration background"): (mig_trend, "with_mig_bg_pct",   "#C0504D"),
                tr("Ausländer/innen", "Foreign nationals"):                   (mig_trend, "foreign_pct",       "#FB8C00"),
                tr("Deutsche mit MH", "Germans with migration background"):   (mig_trend, "german_mig_pct",    "#6D4C41"),
                tr("Deutsche ohne MH", "Germans without migration background"): (mig_trend, "german_no_mig_pct", "#43A047"),
                tr("18- bis 44-Jährige", "Aged 18 to 44"):                    (trend,     "young_adult_pct",   "#1E88E5"),
                tr("unter 18", "under 18"):                                   (trend,     "u18_pct",           "#FFB300"),
                tr("55 und älter", "55 and over"):                            (trend,     "senior_pct",        "#546E7A"),
            }
            for label, (df, col, color) in ratio_series.items():
                if df.empty or col not in df.columns:
                    continue
                fig_ratios.add_trace(go.Scatter(
                    x=df["year"], y=df[col],
                    mode="lines+markers",
                    name=label,
                    line=dict(color=color, width=2),
                    marker=dict(size=6, color=color),
                ))
            fig_ratios.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(
                    showgrid=True,
                    gridcolor="rgba(255,255,255,0.1)",
                    ticksuffix=tr(" %", "%"),
                ),
                xaxis=dict(tickmode="linear", dtick=1),
                xaxis_title=tr("Jahr", "Year"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                margin=dict(t=60, b=20),
                height=420,
            )
            st.plotly_chart(fig_ratios, width="stretch", config=_plot_config)
            st.caption(
                tr("Migrationshintergrund umfasst sowohl Ausländer/innen als auch Deutsche, "
                   "die selbst oder deren Eltern nach Deutschland zugewandert sind.",
                   "Migration background covers both foreign nationals and Germans "
                   "who themselves, or whose parents, moved to Germany.")
            )

    # --- Nationality breakdown over time ---
    nat_trend = get_nationality_over_time()
    if not nat_trend.empty:
        st.divider()
        st.subheader(tr("Einwohner/innen mit Migrationshintergrund nach Herkunft",
                        "Residents with a migration background by origin") + f" ({_yr0}–{_yr1})")
        st.caption(
            tr("Einzelne Länder-/Regionenzählungen aus T4-Tabelle. "
               "Kategorien sind auf dieser Ebene nicht überlappend. "
               "Einige Länder erscheinen nur in bestimmten Jahren aufgrund von Berichtsänderungen.",
               "Individual country/region counts from table T4. "
               "Categories do not overlap at this level. "
               "Some countries appear only in certain years because of changes in reporting.")
        )

        # Year selector
        years = sorted(nat_trend["year"].tolist())
        col_sel, _ = st.columns([1, 3])
        with col_sel:
            selected_year = st.selectbox(tr("Jahr", "Year"), options=years, index=len(years) - 1, key="nat_year")
        row = nat_trend[nat_trend["year"] == selected_year].iloc[0]
        nat_data = {
            col: int(row[col])
            for col in nat_trend.columns
            if col != "year" and int(row[col]) > 0
        }
        # Sort alphabetically so colour assignment is stable across years
        sorted_nat = dict(sorted(nat_data.items()))

        if _is_mobile:
            col_left, col_right = st.container(), st.container()
        else:
            col_left, col_right = st.columns([1, 1])

        # Donut for selected year
        with col_left:
            st.markdown("**" + tr("Zusammensetzung", "Composition") + f" {selected_year}**")
            # Slices in alphabetical order of the displayed (language-specific) name;
            # colours stay keyed by the English data key.
            _donut_keys = sorted(sorted_nat, key=tr_country)
            fig_donut = go.Figure(go.Pie(
                labels=[tr_country(k) for k in _donut_keys],
                values=[sorted_nat[k] for k in _donut_keys],
                marker=dict(colors=[COUNTRY_COLOURS.get(k, "#CCCCCC") for k in _donut_keys]),
                hole=0.45,
                textinfo="label+percent",
                textposition="outside",
                sort=False,
            ))
            fig_donut.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                showlegend=False,
                margin=dict(t=80, b=80, l=80, r=80),
                height=560,
            )
            st.plotly_chart(fig_donut, width="stretch", config=_plot_config)

        # Top nationalities trend lines
        with col_right:
            st.markdown("**" + tr("Wichtigste Nationalitäten im Zeitverlauf", "Main nationalities over time") + "**")
            # Pick top 8 by latest year value
            latest = nat_trend[nat_trend["year"] == max(years)].iloc[0]
            nat_cols = [c for c in nat_trend.columns if c != "year"]
            top_cols = sorted(nat_cols, key=lambda c: latest.get(c, 0), reverse=True)[:8]

            fig_trend = go.Figure()
            for col in sorted(top_cols, key=tr_country):
                colour = COUNTRY_COLOURS.get(col, "#CCCCCC")
                fig_trend.add_trace(go.Scatter(
                    x=nat_trend["year"],
                    y=nat_trend[col],
                    mode="lines+markers",
                    name=tr_country(col),
                    line=dict(color=colour, width=2),
                    marker=dict(size=6, color=colour),
                ))
            fig_trend.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)"),
                xaxis=dict(tickmode="linear", dtick=1),
                xaxis_title=tr("Jahr", "Year"),
                yaxis_title=tr("Bevölkerung", "Population"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                margin=dict(t=40, b=20),
                height=480,
            )
            st.plotly_chart(fig_trend, width="stretch", config=_plot_config)

        st.caption(
            tr("**Hinweis zu Berichtsänderungen:** Die Ausgabe 2025 hat die T4-Ländergliederung umstrukturiert. "
               "Mehrere aggregierte Gruppen aus 2021–2024 (islamische/OIC-Länder, arabische Länder, "
               "ehemaliges Jugoslawien, ehemalige Sowjetunion) wurden durch einzelne Länderspalten ersetzt, "
               "darunter neue Einträge für Afghanistan, Irak, China und Indien. "
               "Zahlen für Syrien, Iran und einige andere Länder sind daher über die Grenze 2024–2025 "
               "nicht direkt vergleichbar.",
               "**Note on reporting changes:** the 2025 edition restructured the T4 country breakdown. "
               "Several aggregate groups used in 2021–2024 (Islamic/OIC countries, Arab countries, "
               "former Yugoslavia, former Soviet Union) were replaced by individual country columns, "
               "including new entries for Afghanistan, Iraq, China and India. "
               "Figures for Syria, Iran and some other countries are therefore not directly comparable "
               "across the 2024–2025 boundary.")
        )

    # --- IBB asking rent trend ---
    st.divider()
    st.subheader(tr("Angebotsmieten nach Bezirk 2008–2025 (€/m², netto kalt)",
                    "Asking rents by district 2008–2025 (€/m², net of service charges)"))

    fig_rent = go.Figure()
    for bezirk in sorted(ASKING_RENTS):
        is_key = bezirk == "Mitte"
        is_berlin = bezirk == BERLIN_MEDIAN_KEY
        fig_rent.add_trace(go.Scatter(
            x=IBB_YEARS,
            y=ASKING_RENTS[bezirk],
            mode="lines+markers",
            name=bezirk,
            line=dict(
                color=BEZIRK_COLOURS.get(bezirk, BERLIN_MEDIAN_COLOUR),
                width=3 if is_key else 1 if is_berlin else 1.5,
                dash="dash" if is_berlin else "solid",
            ),
            marker=dict(size=5 if is_key else 3),
        ))
    fig_rent.update_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(
            showgrid=True,
            gridcolor="rgba(255,255,255,0.1)",
            tickprefix="€",
            ticksuffix="/m²",
        ),
        xaxis=dict(tickmode="linear", dtick=1, tickangle=-45),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(t=60, b=20),
        height=520,
    )
    st.plotly_chart(fig_rent, width="stretch", config=_plot_config)
    st.caption(
        tr("Moabit gehört zum Bezirk Mitte (rote Linie) – keine moabitspezifischen Mietdaten verfügbar. "
           "Berliner Median als gestrichelte graue Linie. "
           "Frühe Datenpunkte verwenden überlappende Berichtszeiträume (z. B. 2008/09 → 2009); "
           "keine Daten für 2011 und 2014. "
           "Quelle: IBB Wohnungsmarktbericht 2008–2025, Tabellenbände, netto kalt.",
           "Moabit is part of the Mitte district (red line); no rent data is published for Moabit itself. "
           "Berlin median as a dashed grey line. "
           "Early data points use overlapping reporting periods (e.g. 2008/09 → 2009); "
           "no data for 2011 and 2014. "
           "Source: IBB Housing Market Report 2008–2025, table volumes, net of service charges.")
    )

# --- Departures tab ---
with tab_departures:
    col_title, col_btn = st.columns([8, 1])
    col_title.subheader(tr("Abfahrten Berlin Hauptbahnhof", "Departures Berlin Hauptbahnhof"))
    if col_btn.button(tr("Aktualisieren", "Refresh"), width="stretch", key="btn_departures"):
        st.rerun()
    with st.spinner(tr("Lade Abfahrtsdaten...", "Loading departures…")):
        try:
            rows = fetch_departures()
        except Exception as e:
            st.error(tr("Abfahrtsdaten konnten nicht geladen werden", "Could not load departures") + f": {e}")
            rows = []
    if rows:
        _dep_cols = ["Icon", "Linie", "Richtung", "Gleis", "Abfahrt", "Verspätung"] if _is_mobile else ["Icon", "Linie", "Typ", "Richtung", "Gleis", "Abfahrt", "Verspätung"]
        st.dataframe(
            [{**r, "Verspätung": _tr_delay(r["Verspätung"])} for r in rows],
            width="stretch",
            hide_index=True,
            height="content",
            column_order=_dep_cols,
            column_config={
                "Icon":       st.column_config.ImageColumn("", width="small"),
                "Linie":      st.column_config.TextColumn(tr("Linie", "Line"),                 width="small"),
                "Typ":        st.column_config.TextColumn(tr("Typ", "Type"),                   width="small"),
                "Richtung":   st.column_config.TextColumn(tr("Richtung", "Destination")),
                "Gleis":      st.column_config.TextColumn(tr("Gleis", "Platform"),             width="small"),
                "Abfahrt":    st.column_config.TextColumn(tr("Abfahrt", "Departs"),            width="small"),
                "Verspätung": st.column_config.TextColumn(
                    tr("Verspätung", "Delay") if not _is_mobile else tr("Versp.", "Delay"), width="small"),
            },
        )
    else:
        st.info(tr("Keine Abfahrten gefunden.", "No departures found."))

with tab_arrivals:
    col_title, col_btn = st.columns([8, 1])
    col_title.subheader(tr("Ankünfte Berlin Hauptbahnhof", "Arrivals Berlin Hauptbahnhof"))
    if col_btn.button(tr("Aktualisieren", "Refresh"), width="stretch", key="btn_arrivals"):
        st.rerun()
    with st.spinner(tr("Lade Ankunftsdaten...", "Loading arrivals…")):
        try:
            rows = fetch_arrivals()
        except Exception as e:
            st.error(tr("Ankunftsdaten konnten nicht geladen werden", "Could not load arrivals") + f": {e}")
            rows = []
    if rows:
        _arr_cols = ["Icon", "Linie", "Herkunft", "Gleis", "Ankunft", "Verspätung"] if _is_mobile else ["Icon", "Linie", "Typ", "Herkunft", "Gleis", "Ankunft", "Verspätung"]
        st.dataframe(
            [{**r, "Verspätung": _tr_delay(r["Verspätung"])} for r in rows],
            width="stretch",
            hide_index=True,
            height="content",
            column_order=_arr_cols,
            column_config={
                "Icon":       st.column_config.ImageColumn("", width="small"),
                "Linie":      st.column_config.TextColumn(tr("Linie", "Line"),                 width="small"),
                "Typ":        st.column_config.TextColumn(tr("Typ", "Type"),                   width="small"),
                "Herkunft":   st.column_config.TextColumn(tr("Herkunft", "Origin")),
                "Gleis":      st.column_config.TextColumn(tr("Gleis", "Platform"),             width="small"),
                "Ankunft":    st.column_config.TextColumn(tr("Ankunft", "Arrives"),            width="small"),
                "Verspätung": st.column_config.TextColumn(
                    tr("Verspätung", "Delay") if not _is_mobile else tr("Versp.", "Delay"), width="small"),
            },
        )
    else:
        st.info(tr("Keine Ankünfte gefunden.", "No arrivals found."))

# --- Umwelt tab ---
with tab_umwelt:
    st.caption(tr("Messstation", "Monitoring station") + f": {STATION_NAME} (DEBE010) · "
               + tr("Quelle: Umweltbundesamt", "Source: German Environment Agency (UBA)"))

    with st.spinner(tr("Lade Luftqualitätsdaten...", "Loading air quality data…")):
        try:
            aq_current = get_airquality_current()
            aq_history = get_airquality_history()
        except Exception as e:
            st.error(tr("Luftqualitätsdaten konnten nicht geladen werden", "Could not load air quality data") + f": {e}")
            aq_current = {}
            aq_history = pd.DataFrame()

    if aq_current:
        st.subheader(tr("Aktuelle Luftqualität", "Current air quality"))
        if _is_mobile:
            _aq_items = []
            for label, data in aq_current.items():
                idx = data["index"]
                idx_label, idx_colour = INDEX_LABELS.get(idx, ("–", "#9E9E9E"))
                idx_label = trl(idx_label)
                limit = LIMITS.get(label)
                delta = (f"{data['value'] - limit:+.0f} µg/m³ " + tr("ggü. Grenzwert", "vs. limit")) if limit else None
                _delta_colour = "#ff4b4b" if (limit and data["value"] > limit) else "#21c354"
                _aq_items.append({
                    "label": trl(label) + " (" + data["unit"] + ")",
                    "value": data["value"],
                    "delta": delta,
                    "delta_colour": _delta_colour if delta else None,
                    "note_html": '<span style="color:' + idx_colour + '">' + idx_label + '</span>',
                })
            _metrics_2col(_aq_items)
        else:
            cols = st.columns(len(aq_current))
            for col, (label, data) in zip(cols, aq_current.items()):
                idx = data["index"]
                idx_label, idx_colour = INDEX_LABELS.get(idx, ("–", "#9E9E9E"))
                idx_label = trl(idx_label)
                limit = LIMITS.get(label)
                delta = (f"{data['value'] - limit:+.0f} µg/m³ " + tr("ggü. Grenzwert", "vs. limit")) if limit else None
                delta_colour = "inverse" if (limit and data["value"] > limit) else "normal"
                col.metric(
                    label=f"{trl(label)} ({data['unit']})",
                    value=data["value"],
                    delta=delta,
                    delta_color=delta_colour,
                )
                col.markdown(
                    f"<small style='color:{idx_colour}'>{idx_label}</small>",
                    unsafe_allow_html=True,
                )

    if not aq_history.empty:
        st.divider()
        st.subheader(tr("Luftqualität im Jahresverlauf (Tagesmittelwerte)", "Air quality over the year (daily means)"))
        fig_aq = go.Figure()
        colour_map = COMPONENT_COLOURS
        for col in sorted(c for c in aq_history.columns if c != "date"):
            fig_aq.add_trace(go.Scatter(
                x=aq_history["date"],
                y=aq_history[col],
                mode="lines",
                name=trl(col),
                line=dict(color=colour_map.get(col, "#888"), width=1.5),
            ))
        # Add EU limit reference lines
        for label, limit in LIMITS.items():
            if label in colour_map:
                fig_aq.add_hline(
                    y=limit,
                    line_dash="dot",
                    line_color=colour_map[label],
                    opacity=0.4,
                    annotation_text=f"{trl(label)} " + tr("Grenzwert", "limit"),
                    annotation_position="right",
                    annotation_font_size=10,
                )
        fig_aq.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)", title="µg/m³"),
            xaxis_title=tr("Datum", "Date"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            margin=dict(t=40, b=20),
            height=420,
        )
        st.plotly_chart(fig_aq, width="stretch", config=_plot_config)
        st.caption(tr(
            "Gestrichelte Linien zeigen EU-Grenzwerte: NO₂ 40 µg/m³ (Jahresmittel), "
            "PM₁₀ 50 µg/m³ (Tagesmittel), PM₂,₅ 25 µg/m³ (Jahresmittel), O₃ 120 µg/m³ (8-Stunden-Maximum). "
            "O₃ steigt im Sommer — die 8-Stunden-Maxima liegen über den Tagesmitteln. Hinweis: Für den gesamten Dezember 2025 liegt nur ein Datenpunkt vor (am 31. Dezember) – die Messstation war mit ziemlicher Sicherheit aufgrund von Wartungs- oder Reparaturarbeiten außer Betrieb.",
            "Dashed lines show EU limit values: NO₂ 40 µg/m³ (annual mean), "
            "PM₁₀ 50 µg/m³ (daily mean), PM₂.₅ 25 µg/m³ (annual mean), O₃ 120 µg/m³ (8-hour maximum). "
            "O₃ rises in summer, and its 8-hour maxima sit above the daily means. Note: there is only one data point for the whole of December 2025 (on 31 December); the monitoring station was almost certainly out of service for maintenance or repair.",
        ))

    # --- Noise section ---
    st.divider()
    st.subheader(tr("Umgebungslärm (Strategische Lärmkarten 2022)", "Environmental noise (strategic noise maps 2022)"))
    st.caption(tr(
        "Berechnete Pegel an allen Gebäudefassaden in Moabit (alle Quellen). "
        "LDEN = gewichteter 24-Stunden-Mittelwert, LN = Nacht (22–6 Uhr). "
        "Schwellen nach Lärmaktionsplan Berlin 2024–2029: Auslösewerte 65 / 55 dB(A), "
        "Gesundheitsgefährdung ab 70 / 60 dB(A). "
        "Quelle: Senatsverwaltung für Mobilität, Verkehr, Klimaschutz und Umwelt, Umweltatlas.",
        "Calculated levels at every building façade in Moabit (all sources). "
        "LDEN = weighted 24-hour average, LN = night (10 pm–6 am). "
        "Thresholds from the Berlin Noise Action Plan 2024–2029: trigger values 65 / 55 dB(A), "
        "health risk from 70 / 60 dB(A). "
        "Source: Senate Department for Mobility, Transport, Climate Protection and the Environment, Environmental Atlas.",
    ))

    with st.spinner(tr("Lade Lärmdaten...", "Loading noise data…")):
        try:
            noise = get_noise_data()
        except Exception as e:
            st.error(tr("Lärmdaten konnten nicht geladen werden", "Could not load noise data") + f": {e}")
            noise = None

    if noise:
        m_data = noise["metrics"]
        _t, _h = THRESHOLDS["trigger"], THRESHOLDS["health"]

        # Headline metrics
        _noise_items = [
            (tr("Fassadenpunkte", "Façade points"), _fmt_int(m_data["n_points"])),
            ("Median LDEN",    f"{_fmt_float(m_data['median_den'])} dB(A)"),
            ("Median LN",      f"{_fmt_float(m_data['median_n'])} dB(A)"),
            (f"LDEN ≥ {_t['den']} dB(A)", _fmt_pct(m_data["trigger_den_pct"])),
        ]
        if _is_mobile:
            _metrics_2col([{"label": l, "value": v} for l, v in _noise_items])
        else:
            for col, (label, value) in zip(st.columns(4), _noise_items):
                col.metric(label, value)

        _p = {k: _fmt_pct(m_data[k]) for k in ("trigger_den_pct", "trigger_n_pct", "health_den_pct", "health_n_pct")}
        st.markdown(tr(
            f"**{_p['trigger_den_pct']}** der Fassaden liegen über dem Auslösewert "
            f"(LDEN ≥ {_t['den']} dB(A)), **{_p['trigger_n_pct']}** nachts "
            f"(LN ≥ {_t['n']} dB(A)). Im gesundheitsgefährdenden Bereich: "
            f"**{_p['health_den_pct']}** ganztags, **{_p['health_n_pct']}** nachts.",
            f"**{_p['trigger_den_pct']}** of façades are above the trigger value "
            f"(LDEN ≥ {_t['den']} dB(A)), **{_p['trigger_n_pct']}** at night "
            f"(LN ≥ {_t['n']} dB(A)). In the health-risk range: "
            f"**{_p['health_den_pct']}** over 24 hours, **{_p['health_n_pct']}** at night.",
        ))

        st.divider()
        if _is_mobile:
            col_dist, col_top = st.container(), st.container()
        else:
            col_dist, col_top = st.columns(2)

        # Distribution chart
        with col_dist:
            st.subheader(tr("Pegelverteilung: 24 h vs. Nacht", "Level distribution: 24 h vs. night"))
            fig_dist = go.Figure()
            for key, label, colour in [("n", tr("Nacht (LN)", "Night (LN)"), "#1E88E5"), ("den", "24 h (LDEN)", "#C0504D")]:
                fig_dist.add_trace(go.Bar(
                    name=label,
                    x=DB_BANDS,
                    y=[noise["dist"][key][b] for b in DB_BANDS],
                    marker_color=colour,
                ))
            fig_dist.update_layout(
                barmode="group",
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)", title=tr("Anzahl Fassadenpunkte", "Number of façade points")),
                xaxis_title=tr("Pegelklasse (dB(A))", "Level band (dB(A))"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                margin=dict(t=40, b=20),
                height=380,
            )
            st.plotly_chart(fig_dist, width="stretch", config=_plot_config)

        # Top streets chart
        with col_top:
            st.subheader(tr("Lauteste Straßen (Straßenlärm, LDEN)", "Loudest streets (road noise, LDEN)"))
            top = sorted(noise["top"], key=lambda r: r["den"])
            fig_top = go.Figure(go.Bar(
                x=[r["den"] for r in top],
                y=[f"{r['street']} ({r['points']})" for r in top],
                orientation="h",
                marker_color=[
                    "#C0504D" if r["den"] >= _h["den"] else "#FB8C00" if r["den"] >= _t["den"] else "#FFB300"
                    for r in top
                ],
                text=[_fmt_float(r["den"]) for r in top],
                textposition="outside",
            ))
            fig_top.add_vline(
                x=_t["den"], line_dash="dot", line_color="white", opacity=0.4,
                annotation_text=tr("Auslösewert", "Trigger value") + f" ({_t['den']} dB(A))",
                annotation_font_size=10, annotation_position="bottom right",
            )
            fig_top.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)", title="dB(A)"),
                xaxis_range=[55, 78],
                margin=dict(t=40, b=20, r=60),
                height=380,
            )
            st.plotly_chart(fig_top, width="stretch", config=_plot_config)
            st.caption(tr(
                "Median des Straßenlärms an straßenseitigen Fassaden (≤ 20 m von der Straße, "
                "mind. 50 Fassadenpunkte; Anzahl in Klammern). Rot: über der Gesundheitsschwelle, "
                "orange: über dem Auslösewert.",
                "Median road noise at street-facing façades (≤ 20 m from the street, "
                "at least 50 façade points; count in brackets). Red: above the health-risk threshold, "
                "orange: above the trigger value.",
            ))

        # --- Noise at sensitive buildings ---
        _fac = noise.get("facilities") or []
        if _fac:
            st.subheader(tr("Lärm an Kitas, Schulen und Krankenhäusern", "Noise at kitas, schools and hospitals"))
            _fac_series = [
                ("trigger_den_pct", f"24 h: LDEN ≥ {_t['den']} dB(A)", "#C0504D"),
                ("trigger_n_pct",   tr("Nacht", "Night") + f": LN ≥ {_t['n']} dB(A)", "#1E88E5"),
            ]
            fig_fac = go.Figure()
            for key, label, colour in _fac_series:
                fig_fac.add_trace(go.Bar(
                    name=label,
                    x=[trl(f["label"]) for f in _fac],
                    y=[f[key] for f in _fac],
                    marker_color=colour,
                    text=[
                        f"{_fmt_pct(f[key])}<br>({round(f[key] / 100 * f['buildings'])} "
                        + tr("von", "of") + f" {f['buildings']})"
                        for f in _fac
                    ],
                    textposition="outside",
                ))
            _fac_max = max(f[k] for f in _fac for k, _, _ in _fac_series)
            fig_fac.update_layout(
                barmode="group",
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)", ticksuffix=tr(" %", "%"),
                           range=[0, _fac_max * 1.35], title=tr("Anteil der Gebäude", "Share of buildings")),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                margin=dict(t=40, b=20),
                height=400,
            )
            st.plotly_chart(fig_fac, width="stretch", config=_plot_config)
            _fac_health = "; ".join(
                f"{trl(f['label'])} {_fmt_pct(f['health_den_pct'])} / {_fmt_pct(f['health_n_pct'])}" for f in _fac
            )
            st.caption(tr(
                "Anteil der Gebäude, deren am stärksten belastete Fassade über dem Auslösewert des "
                "Lärmaktionsplans liegt (alle Lärmquellen). Im gesundheitsgefährdenden Bereich "
                f"(≥ {_h['den']} / {_h['n']} dB(A), 24 h / Nacht): {_fac_health}. "
                "Gebäude laut Lärmkartierung 2022, ohne Namen; ein Standort kann mehrere Gebäude umfassen.",
                "Share of buildings whose most exposed façade is above the noise action plan's "
                "trigger value (all noise sources). In the health-risk range "
                f"(≥ {_h['den']} / {_h['n']} dB(A), 24 h / night): {_fac_health}. "
                "Buildings as mapped for the 2022 noise maps, without names; one site can comprise several buildings.",
            ))

    # --- Road noise 2004, for comparison ---
    st.divider()
    st.subheader(tr("Zum Vergleich: Straßenverkehrslärm 2004 (Umweltatlas Berlin)",
                    "For comparison: road traffic noise 2004 (Berlin Environmental Atlas)"))
    st.caption(tr(
        "2004 wurde jeder Straßenabschnitt nach seinem Pegel an der Bebauungskante bewertet, also nur "
        "straßenseitig, getrennt nach Tag (6–22 Uhr) und Nacht (22–6 Uhr). Die Fassadenstatistik von 2022 "
        "oben schließt dagegen auch Hof- und Rückseiten ein und nutzt LDEN, sodass die Gesamtzahlen nicht "
        "vergleichbar sind. Am ehesten vergleichbar sind die lautesten Hauptstraßen beider Jahre. "
        "Quelle: Senatsverwaltung für Stadtentwicklung, Umweltatlas Berlin 2004.",
        "In 2004 each street section was rated by its level at the building line, i.e. on the street side "
        "only, separately for day (6 am–10 pm) and night (10 pm–6 am). The 2022 façade statistics above also "
        "include courtyard and rear façades and use LDEN, so the overall figures are not comparable. The "
        "loudest main roads of the two years are the closest like-for-like comparison. "
        "Source: Senate Department for Urban Development, Berlin Environmental Atlas 2004.",
    ))
    try:
        noise04 = get_noise_2004()
    except Exception as e:
        st.error(tr("Lärmdaten 2004 konnten nicht geladen werden", "Could not load 2004 noise data") + f": {e}")
        noise04 = None

    if noise04:
        m04 = noise04["metrics"]
        _n04_items = [
            (tr("Straßenabschnitte", "Street sections"), _fmt_int(m04["n_sections"])),
            (tr("Median Tag", "Median day"),             f"{_fmt_float(m04['median_day'])} dB(A)"),
            (tr("Median Nacht", "Median night"),         f"{_fmt_float(m04['median_night'])} dB(A)"),
            (tr("Tag ≥ 65 dB(A)", "Day ≥ 65 dB(A)"),     _fmt_pct(m04["over65_day_pct"])),
        ]
        if _is_mobile:
            _metrics_2col([{"label": l, "value": v} for l, v in _n04_items])
        else:
            for col, (label, value) in zip(st.columns(4), _n04_items):
                col.metric(label, value)

        if _is_mobile:
            col_d04, col_t04 = st.container(), st.container()
        else:
            col_d04, col_t04 = st.columns(2)

        with col_d04:
            st.subheader(tr("Pegelverteilung 2004: Tag vs. Nacht", "Level distribution 2004: day vs. night"))
            fig_d04 = go.Figure()
            for key, label, colour in [("night", tr("Nacht", "Night"), "#1E88E5"), ("day", tr("Tag", "Day"), "#C0504D")]:
                fig_d04.add_trace(go.Bar(
                    name=label,
                    x=DB_BANDS,
                    y=[noise04["dist"][key][b] for b in DB_BANDS],
                    marker_color=colour,
                ))
            fig_d04.update_layout(
                barmode="group",
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)",
                           title=tr("Anzahl Straßenabschnitte", "Number of street sections")),
                xaxis_title=tr("Pegelklasse (dB(A))", "Level band (dB(A))"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                margin=dict(t=40, b=20),
                height=380,
            )
            st.plotly_chart(fig_d04, width="stretch", config=_plot_config)

        with col_t04:
            st.subheader(tr("Lauteste Straßen 2004 (Tag)", "Loudest streets 2004 (day)"))
            top04 = sorted(noise04["streets"][:10], key=lambda r: r["day"])
            fig_t04 = go.Figure(go.Bar(
                x=[r["day"] for r in top04],
                y=[f"{r['street']} ({r['sections']})" for r in top04],
                orientation="h",
                marker_color=[
                    "#C0504D" if r["day"] >= 70 else "#FB8C00" if r["day"] >= 65 else "#FFB300"
                    for r in top04
                ],
                text=[_fmt_float(r["day"]) for r in top04],
                textposition="outside",
            ))
            fig_t04.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)", title="dB(A)"),
                xaxis_range=[55, 78],
                margin=dict(t=40, b=20, r=60),
                height=380,
            )
            st.plotly_chart(fig_t04, width="stretch", config=_plot_config)
            st.caption(tr(
                "Median der Tagespegel je Straße (mind. 5 bewertete Abschnitte; Anzahl in Klammern). "
                "Gleiche Farbstufen wie 2022 (orange ab 65, rot ab 70 dB(A)), hier auf den Tagespegel angewandt.",
                "Median day level per street (at least 5 rated sections; count in brackets). "
                "Same colour steps as 2022 (orange from 65, red from 70 dB(A)), applied here to the day level.",
            ))

    # --- Trees section ---
    st.divider()
    st.subheader(tr("Stadtbäume (Baumbestand Berlin)", "Street and park trees (Berlin tree register)"))
    st.caption(tr(
        "Straßen- und Anlagenbäume in Moabit laut Baumkataster des Grünflächeninformationssystems (GRIS). "
        "Anlagenbäume sind nur teilweise erfasst. "
        "Quelle: Senatsverwaltung für Mobilität, Verkehr, Klimaschutz und Umwelt, Baumbestand Berlin.",
        "Street and park trees in Moabit from the tree register of Berlin's green-space information system (GRIS). "
        "Park trees are only partly recorded. "
        "Source: Senate Department for Mobility, Transport, Climate Protection and the Environment, Baumbestand Berlin.",
    ))
    try:
        _tdf = pd.DataFrame(get_trees(), columns=TREE_FIELDS)
    except Exception as e:
        st.error(tr("Baumdaten konnten nicht geladen werden", "Could not load tree data") + f": {e}")
        _tdf = pd.DataFrame()

    if not _tdf.empty:
        _tdf["year"] = pd.to_numeric(_tdf["year"], errors="coerce")
        _tdf["age"] = date.today().year - _tdf["year"]
        _tlabels = {k: trl(v["label"]) for k, v in TREE_TYPES.items()}
        _tcolours = {k: v["colour"] for k, v in TREE_TYPES.items()}
        _n_street = int((_tdf["type"] == "strasse").sum())
        _n_park = int((_tdf["type"] == "anlage").sum())

        _tree_items = [
            (tr("Bäume gesamt", "Trees in total"), _fmt_int(len(_tdf))),
            (tr("Straßenbäume", "Street trees"),    _fmt_int(_n_street)),
            (tr("Anlagenbäume", "Park trees"),      _fmt_int(_n_park)),
            (tr("Medianes Alter", "Median age"),    f"{_fmt_int(_tdf['age'].median())} " + tr("Jahre", "years")),
        ]
        if _is_mobile:
            _metrics_2col([{"label": l, "value": v} for l, v in _tree_items])
        else:
            for col, (label, value) in zip(st.columns(4), _tree_items):
                col.metric(label, value)

        if _is_mobile:
            col_species, col_decade = st.container(), st.container()
        else:
            col_species, col_decade = st.columns(2)

        # Most common species, stacked by street/park
        with col_species:
            st.subheader(tr("Häufigste Baumarten", "Most common species"))
            _top_species = _tdf["species"].value_counts().head(10).index.tolist()
            _sp = (_tdf[_tdf["species"].isin(_top_species)]
                   .groupby(["species", "type"]).size().unstack(fill_value=0))
            # Desktop: horizontal bars, largest at the top. Mobile: vertical bars
            # (portrait), largest first, per the dashboard's mobile chart rule.
            _order = _sp.sum(axis=1).sort_values(ascending=not _is_mobile).index.tolist()
            _order_shown = [tr_species(sp) for sp in _order]
            fig_sp = go.Figure()
            for t in TREE_TYPES:
                vals = [int(_sp.loc[sp, t]) if t in _sp.columns else 0 for sp in _order]
                if _is_mobile:
                    fig_sp.add_trace(go.Bar(name=_tlabels[t], x=_order_shown, y=vals, marker_color=_tcolours[t]))
                else:
                    fig_sp.add_trace(go.Bar(name=_tlabels[t], x=vals, y=_order_shown, orientation="h",
                                            marker_color=_tcolours[t]))
            fig_sp.update_layout(
                barmode="stack",
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                margin=dict(t=40, b=100 if _is_mobile else 20),
                height=460 if _is_mobile else 420,
            )
            if _is_mobile:
                fig_sp.update_layout(xaxis=dict(tickangle=-40),
                                     yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)", title=tr("Bäume", "Trees")))
            else:
                fig_sp.update_layout(xaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)", title=tr("Bäume", "Trees")))
            st.plotly_chart(fig_sp, width="stretch", config=_plot_config)

        # Planting by decade, stacked by street/park
        with col_decade:
            st.subheader(tr("Pflanzjahre nach Jahrzehnt", "Planting years by decade"))
            _dated = _tdf.dropna(subset=["year"]).copy()
            _dated["decade"] = (_dated["year"] // 10 * 10).astype(int)
            _dated["decade_label"] = _dated["decade"].map(
                lambda d: tr("vor 1900", "before 1900") if d < 1900 else f"{d}" + tr("er", "s"))
            _dec = _dated.groupby(["decade_label", "type"]).size().unstack(fill_value=0)
            _dec_order = sorted(_dec.index, key=lambda lbl: int(lbl[:4]) if lbl[:4].isdigit() else 0)
            fig_dec = go.Figure()
            for t in TREE_TYPES:
                fig_dec.add_trace(go.Bar(
                    name=_tlabels[t], x=_dec_order,
                    y=[int(_dec.loc[d, t]) if t in _dec.columns else 0 for d in _dec_order],
                    marker_color=_tcolours[t],
                ))
            fig_dec.update_layout(
                barmode="stack",
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)", title=tr("Bäume", "Trees")),
                xaxis=dict(tickangle=-40),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                margin=dict(t=40, b=20),
                height=460 if _is_mobile else 420,
            )
            st.plotly_chart(fig_dec, width="stretch", config=_plot_config)
            _undated = len(_tdf) - len(_dated)
            st.caption(tr(
                f"Ohne Pflanzjahr: {_fmt_int(_undated)} Bäume (überwiegend Anlagenbäume). "
                "Viele Pflanzjahre sind geschätzt – sie häufen sich auf runden Jahren wie 1950 oder 1975.",
                f"No planting year: {_fmt_int(_undated)} trees (mostly park trees). "
                "Many planting years are estimates; they cluster on round years such as 1950 or 1975.",
            ))

        # Oldest recorded trees
        st.markdown("**" + tr("Älteste erfasste Bäume", "Oldest recorded trees") + "**")
        _oldest = _tdf.dropna(subset=["year"]).sort_values(["year", "height"], ascending=[True, False]).head(5)
        _oldest_rows = [
            {
                tr("Baumart", "Species"):   tr_species(r.species),
                tr("Gepflanzt", "Planted"): str(int(r.year)),
                tr("Alter", "Age"):         f"{int(r.age)} " + tr("Jahre", "years"),
                tr("Höhe", "Height"):       f"{int(r.height)} m" if pd.notna(r.height) else "–",
                tr("Standort", "Location"): (f"{r.street} {r.number}".strip() if r.street
                                             else tr("Grünanlage", "Green space")),
            }
            for r in _oldest.itertuples()
        ]
        if _is_mobile:
            st.table(pd.DataFrame(_oldest_rows))
        else:
            st.dataframe(pd.DataFrame(_oldest_rows), width="stretch", hide_index=True, height="content")
        st.caption(tr("Pflanzjahre laut Baumkataster, teils geschätzt.",
                      "Planting years from the tree register, some estimated."))

# --- Kriminalität tab ---
with tab_crime:
    _LOR_COLOURS = {
        "Alexanderplatz":       "#8E24AA",
        "Brunnenstraße Nord":   "#00ACC1",
        "Brunnenstraße Süd":    "#43A047",
        "Moabit (gesamt)":      "#FB8C00",
        "Moabit Ost":           "#C0504D",
        "Moabit West":          "#1E88E5",
        "Osloer Straße":       "#6D4C41",
        "Parkviertel":          "#546E7A",
        "Regierungsviertel":    "#F4511E",
        "Tiergarten Süd":      "#039BE5",
        "Wedding Zentrum":      "#7CB342",
    }
    _CAT_COLOURS = {
        cat: clr for cat, clr in zip(
            sorted(CATEGORIES.keys()),
            ["#1E88E5","#43A047","#8E24AA","#00ACC1","#C0504D","#FB8C00",
             "#6D4C41","#546E7A","#F4511E","#039BE5","#7CB342","#FFB300",
             "#FF6692","#B6E880","#FECB52","#19D3F3","#636EFA"]
        )
    }
    st.caption(tr("Quelle: Polizei Berlin, Kriminalitätsatlas (PKS) · Moabit West + Ost kombiniert",
                  "Source: Berlin Police, Crime Atlas (PKS) · Moabit West and Ost combined"))

    with st.spinner(tr("Lade Kriminalitätsdaten...", "Loading crime data…")):
        try:
            crime_df = get_crime_data()
        except Exception as e:
            st.error(tr("Kriminalitätsdaten konnten nicht geladen werden", "Could not load crime data") + f": {e}")
            crime_df = None

    if crime_df is not None:
        latest_year = crime_df.index.max()
        prev_year   = latest_year - 1

        # --- Headline metrics ---
        total_latest = crime_df.loc[latest_year, "Straftaten insgesamt"]
        total_prev   = crime_df.loc[prev_year,   "Straftaten insgesamt"]
        delta_total  = total_latest - total_prev

        kieztaten_latest = crime_df.loc[latest_year, "Kieztaten"]
        kieztaten_prev   = crime_df.loc[prev_year,   "Kieztaten"]
        delta_kiez       = kieztaten_latest - kieztaten_prev

        fahrrad_latest = crime_df.loc[latest_year, "Fahrraddiebstahl"]
        fahrrad_prev   = crime_df.loc[prev_year,   "Fahrraddiebstahl"]
        delta_fahrrad  = fahrrad_latest - fahrrad_prev

        einbruch_latest = crime_df.loc[latest_year, "Wohnraumeinbruch"]
        einbruch_prev   = crime_df.loc[prev_year,   "Wohnraumeinbruch"]
        delta_einbruch  = einbruch_latest - einbruch_prev

        def _crime_delta(d):
            sign = "+" if d >= 0 else ""
            return f"{sign}{_fmt_int(d)} " + tr("ggü.", "vs.") + f" {prev_year}"

        if _is_mobile:
            _metrics_2col([
                {"label": f"{trl('Straftaten insgesamt')} ({latest_year})", "value": _fmt_int(total_latest),
                 "delta": _crime_delta(delta_total),
                 "delta_colour": "#ff4b4b" if delta_total > 0 else "#21c354"},
                {"label": f"{trl('Kieztaten')} ({latest_year})", "value": _fmt_int(kieztaten_latest),
                 "delta": _crime_delta(delta_kiez),
                 "delta_colour": "#ff4b4b" if delta_kiez > 0 else "#21c354"},
                {"label": f"{trl('Fahrraddiebstahl')} ({latest_year})", "value": _fmt_int(fahrrad_latest),
                 "delta": _crime_delta(delta_fahrrad),
                 "delta_colour": "#ff4b4b" if delta_fahrrad > 0 else "#21c354"},
                {"label": f"{trl('Wohnraumeinbruch')} ({latest_year})", "value": _fmt_int(einbruch_latest),
                 "delta": _crime_delta(delta_einbruch),
                 "delta_colour": "#ff4b4b" if delta_einbruch > 0 else "#21c354"},
            ])
        else:
            col1, col2, col3, col4 = st.columns(4)
            col1.metric(f"{trl('Straftaten insgesamt')} ({latest_year})", _fmt_int(total_latest),
                        delta=_crime_delta(delta_total),
                        delta_color="inverse" if delta_total > 0 else "normal")
            col2.metric(f"{trl('Kieztaten')} ({latest_year})", _fmt_int(kieztaten_latest),
                        delta=_crime_delta(delta_kiez),
                        delta_color="inverse" if delta_kiez > 0 else "normal")
            col3.metric(f"{trl('Fahrraddiebstahl')} ({latest_year})", _fmt_int(fahrrad_latest),
                        delta=_crime_delta(delta_fahrrad),
                        delta_color="inverse" if delta_fahrrad > 0 else "normal")
            col4.metric(f"{trl('Wohnraumeinbruch')} ({latest_year})", _fmt_int(einbruch_latest),
                        delta=_crime_delta(delta_einbruch),
                        delta_color="inverse" if delta_einbruch > 0 else "normal")

        st.divider()

        # --- Bezirk comparison ---
        st.subheader(tr("Straftaten insgesamt im Berliner Vergleich", "All offences: Berlin comparison"))
        st.caption(tr("Moabit ist ein Ortsteil von Mitte — die Balken zeigen Bezirkswerte, nicht Moabit direkt.",
                      "Moabit is part of the Mitte district; the bars show district figures, not Moabit itself."))
        with st.spinner(tr("Lade Bezirksdaten...", "Loading district data…")):
            try:
                bz_fall, bz_hz = get_bezirk_comparison()
            except Exception as e:
                st.error(tr("Bezirksdaten konnten nicht geladen werden", "Could not load district data") + f": {e}")
                bz_fall, bz_hz = None, None

        if bz_fall is not None:
            _bz_sel_col, _bz_year_col, _ = st.columns([2, 1, 2])
            with _bz_sel_col:
                _bz_metric = st.radio(
                    tr("Kennzahl", "Measure"), ["Fallzahlen", "HZ (pro 100 000 Einwohner)"], format_func=trl,
                    horizontal=True, key="bz_metric"
                )
            with _bz_year_col:
                _bz_years = sorted(bz_fall["year"].unique(), reverse=True)
                _bz_year = st.selectbox(tr("Jahr", "Year"), options=_bz_years, index=0, key="bz_year")

            _bz_use_hz = _bz_metric.startswith("HZ")
            if _bz_use_hz:
                _bz_data = bz_hz[bz_hz["year"] == _bz_year].sort_values("Bezirk", ascending=False)
                _bz_x = _bz_data["HZ"].round(0).astype(int)
                _bz_text = _bz_data["HZ"].apply(lambda v: _fmt_int(round(v)))
                _bz_title = trl("HZ (pro 100 000 Einwohner)")
            else:
                _bz_data = bz_fall[bz_fall["year"] == _bz_year].sort_values("Bezirk", ascending=False)
                _bz_x = _bz_data["Fallzahlen"]
                _bz_text = _bz_data["Fallzahlen"].apply(_fmt_int)
                _bz_title = trl("Fallzahlen")
            _bz_colours = [BEZIRK_COLOURS.get(b, "#888") for b in _bz_data["Bezirk"]]
            if _is_mobile:
                fig_bz = go.Figure(go.Bar(
                    x=_bz_data["Bezirk"],
                    y=_bz_x,
                    marker_color=_bz_colours,
                    text=_bz_text,
                    textposition="outside",
                ))
                fig_bz.update_layout(
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)", title=_bz_title),
                    xaxis=dict(tickangle=-40),
                    margin=dict(t=40, b=100, r=20),
                    height=440,
                )
            else:
                fig_bz = go.Figure(go.Bar(
                    x=_bz_x,
                    y=_bz_data["Bezirk"],
                    orientation="h",
                    marker_color=_bz_colours,
                    text=_bz_text,
                    textposition="outside",
                ))
                fig_bz.update_layout(
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    xaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)", title=_bz_title),
                    margin=dict(t=10, b=20, r=80),
                    height=400,
                )
            st.plotly_chart(fig_bz, width="stretch", config=_plot_config)

        st.divider()

        # --- All-Bezirke trend ---
        st.subheader(tr("Alle Bezirke im Vergleich", "All districts compared"))
        _bez_metric = st.radio(
            tr("Kennzahl", "Measure"), ["Fallzahlen", "HZ (pro 100 000 Einwohner)"], format_func=trl,
            horizontal=True, key="bez_trend_metric"
        )
        _use_hz = _bez_metric.startswith("HZ")
        _btr_df = bz_hz if _use_hz else bz_fall
        _btr_val = "HZ" if _use_hz else "Fallzahlen"
        _btr_pivot = _btr_df.pivot(index="year", columns="Bezirk", values=_btr_val).sort_index()
        _btr_pivot = _btr_pivot[sorted(_btr_pivot.columns)]
        _fig_btr = go.Figure()
        for _bez in _btr_pivot.columns:
            _is_mitte = _bez == "Mitte"
            _fig_btr.add_trace(go.Scatter(
                x=_btr_pivot.index.tolist(),
                y=_btr_pivot[_bez].tolist(),
                name=_bez,
                mode="lines+markers",
                line=dict(width=2.5 if _is_mitte else 1.5, color=BEZIRK_COLOURS.get(_bez, "#888")),
                marker=dict(size=5 if _is_mitte else 4),
            ))
        _fig_btr.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)", title=trl(_btr_val)),
            xaxis=dict(tickmode="linear", dtick=1, title=tr("Jahr", "Year")),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            margin=dict(t=60, b=20),
            height=460,
        )
        st.plotly_chart(_fig_btr, width="stretch", config=_plot_config)
        st.caption(tr("Mitte (rot) enthält Moabit. HZ = Häufigkeitszahl (Straftaten pro 100 000 Einwohner).",
                      "Mitte (red) contains Moabit. HZ = crime rate (offences per 100,000 residents)."))

        st.subheader(tr("Warum ist die Kriminalitätsrate in Moabit so hoch?", "Why is Moabit's crime rate so high?"))
        st.markdown(tr("""
Moabits Kriminalitätsrate ist höher als der Berliner Durchschnitt — doch ein genauerer Blick relativiert das Bild erheblich.

**Mitte als touristisches Zentrum.** Moabit ist ein Ortsteil von Mitte — dem historischen Herz Berlins mit Alexanderplatz, Museumsinsel, Brandenburger Tor und Hackeschem Markt. Enormes Besucheraufkommen trifft hier auf eine vergleichsweise kleine gemeldete Wohnbevölkerung, was die HZ des gesamten Bezirks strukturell in die Höhe treibt — und Moabit als Ortsteil davon mit betrifft.

**Hauptbahnhof-Effekt.** Deutschlands verkehrsreichster Bahnhof liegt am östlichen Rand Moabits und zieht täglich Hunderttausende Reisende an. Opportunistische Delikte wie Taschendiebstahl konzentrieren sich rund um Verkehrsknotenpunkte — und erhöhen die Fallzahlen strukturell.

**Häufigkeitszahl und Bevölkerungsbasis.** Die HZ wird gegen die *gemeldete* Wohnbevölkerung berechnet, nicht gegen die tatsächliche Zahl der sich im Kiez aufhaltenden Personen. In Gebieten mit hohem Tagespublikum wie Moabit Ost ist die HZ daher systematisch überhöht.

**Sozialer Brennpunkt Kleiner Tiergarten.** Die offene Drogenszene rund um den Kleinen Tiergarten erzeugt Drogen- und Beschaffungskriminalität, die in den Statistiken sichtbar ist.

**Polizeipräsenz erhöht Erfassungsquote.** Gebiete mit starker Polizeipräsenz — etwa rund um Hbf und Kriminalgericht — weisen schlicht mehr *erfasste* Straftaten auf, nicht unbedingt mehr tatsächliche.
""", """
Moabit's crime rate is higher than the Berlin average, but a closer look puts that figure into perspective.

**Mitte as a tourist centre.** Moabit is part of the Mitte district, Berlin's historic heart, with Alexanderplatz, Museum Island, the Brandenburg Gate and Hackescher Markt. Huge numbers of visitors meet a comparatively small registered population, which structurally pushes up the crime rate (HZ) of the whole district, and of Moabit as part of it.

**The Hauptbahnhof effect.** Germany's busiest railway station sits on Moabit's eastern edge and draws hundreds of thousands of travellers every day. Opportunistic offences such as pickpocketing cluster around transport hubs and structurally raise the number of recorded cases.

**The crime rate and its population base.** The HZ is calculated against the *registered* resident population, not the number of people actually present in the neighbourhood. In areas with many daytime visitors, such as Moabit Ost, the HZ is therefore systematically inflated.

**Kleiner Tiergarten as a social hotspot.** The open drug scene around the Kleiner Tiergarten generates drug-related and acquisitive crime, which shows up in the statistics.

**Police presence raises the recording rate.** Areas with a strong police presence, such as around the Hauptbahnhof and the criminal court, simply have more *recorded* offences, not necessarily more actual ones.
"""))

        st.divider()

        # --- Mitte LOR chart ---
        st.subheader(tr("Bezirk Mitte: Stadtteile im Vergleich", "Mitte district: areas compared"))
        _lor_metric = st.radio(
            tr("Kennzahl", "Measure"), ["Fallzahlen", "HZ (pro 100 000 Einwohner)"], format_func=trl,
            horizontal=True, key="lor_metric"
        )
        _lor_fz_df, _lor_hz_df = get_mitte_lor_data()
        _lor_use_hz = _lor_metric.startswith("HZ")
        _lor_src = _lor_hz_df if _lor_use_hz else _lor_fz_df
        _lor_val = "HZ" if _lor_use_hz else "Fallzahlen"
        _lor_pivot = _lor_src.pivot(index="year", columns="Gebiet", values=_lor_val).sort_index()
        _lor_pivot = _lor_pivot[sorted(_lor_pivot.columns)]
        _MOABIT_GEBIETE = {"Moabit West", "Moabit Ost", "Moabit (gesamt)"}
        _fig_lor = go.Figure()
        for _geb in _lor_pivot.columns:
            _is_moabit = _geb in _MOABIT_GEBIETE
            _fig_lor.add_trace(go.Scatter(
                x=_lor_pivot.index.tolist(),
                y=_lor_pivot[_geb].tolist(),
                name=trl(_geb),
                mode="lines+markers",
                line=dict(width=2.5 if _is_moabit else 1.5, color=_LOR_COLOURS.get(_geb, "#888")),
                marker=dict(size=5 if _is_moabit else 4),
            ))
        _fig_lor.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)", title=trl(_lor_val)),
            xaxis=dict(tickmode="linear", dtick=1, title=tr("Jahr", "Year")),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            margin=dict(t=60, b=20),
            height=460,
        )
        st.plotly_chart(_fig_lor, width="stretch", config=_plot_config)
        _lor_caption = tr("Moabit West (blau), Moabit Ost (rot), Moabit gesamt (orange). Alphabetische Reihenfolge.",
                          "Moabit West (blue), Moabit Ost (red), Moabit total (orange). Alphabetical order.")
        if _lor_use_hz:
            _lor_caption += tr(" Kombinierte HZ für Moabit gesamt nicht verfügbar (bevölkerungsgewichtet).",
                               " No combined HZ for Moabit as a whole (it would need population weighting).")
        st.caption(_lor_caption)

        st.divider()

        # --- Trend chart ---
        st.subheader(tr("Entwicklung", "Trend") + " 2015–" + str(latest_year) + " (Moabit)")
        all_cats = sorted(CATEGORIES.keys(), key=trl)  # alphabetical by displayed name
        st.markdown(
            """<style>
            div[data-testid="stMultiSelect"] span[data-baseweb="tag"] {
                background-color: #546E7A !important;
            }
            </style>""",
            unsafe_allow_html=True
        )
        # A keyed multiselect keeps its tag labels when only format_func changes, so
        # the tags would stay in the old language after a switch. The selection is
        # kept under a language-neutral name; the widget key is per language and is
        # seeded from it, so switching rebuilds the widget without losing the choice.
        if "crime_cats_sel" not in st.session_state:
            st.session_state.crime_cats_sel = list(DEFAULT_CATEGORIES)
        selected = st.multiselect(
            tr("Deliktsbereiche", "Offence categories"),
            options=all_cats,
            format_func=trl,
            default=st.session_state.crime_cats_sel,
            key=f"crime_cats_{LANG}",
        )
        st.session_state.crime_cats_sel = selected
        _swatch_html = '<div style="display:flex;flex-wrap:wrap;row-gap:4px;column-gap:12px;margin-top:4px;">'
        for _c in all_cats:
            _col = _CAT_COLOURS[_c]
            _swatch_html += (
                f'<span style="display:inline-flex;align-items:center;gap:5px;font-size:0.78rem;">'
                f'<span style="display:inline-block;width:10px;height:10px;border-radius:2px;'
                f'background:{_col};flex-shrink:0;"></span>{trl(_c)}</span>'
            )
        _swatch_html += '</div>'
        st.markdown(_swatch_html, unsafe_allow_html=True)

        if selected:
            fig_trend = go.Figure()
            for cat in sorted(selected, key=trl):
                fig_trend.add_trace(go.Scatter(
                    x=crime_df.index.tolist(),
                    y=crime_df[cat].tolist(),
                    name=trl(cat),
                    mode="lines+markers",
                    line=dict(color=_CAT_COLOURS.get(cat, "#888"), width=2),
                    marker=dict(size=5),
                ))
            fig_trend.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)", title=trl("Fallzahlen")),
                xaxis=dict(tickmode="linear", dtick=1, title=tr("Jahr", "Year")),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                margin=dict(t=60, b=20),
                height=420,
            )
            st.plotly_chart(fig_trend, width="stretch", config=_plot_config)
            st.caption(
                tr("⚠️ 2016 zeigt einen auffälligen Ausreißer (+33 % gegenüber 2015), "
                   "der wahrscheinlich auf eine Änderung der Gebietsabgrenzung oder der statistischen "
                   "Erfassungsmethodik zurückzuführen ist. Die Daten für 2015 und 2016 sollten mit "
                   "Vorsicht interpretiert werden.",
                   "⚠️ 2016 shows a striking outlier (+33% on 2015), most likely caused by a change "
                   "in area boundaries or in statistical recording methods. Treat the 2015 and 2016 "
                   "figures with caution.")
            )

        st.divider()

        # --- Latest year breakdown ---
        st.subheader(tr("Alle Deliktsbereiche", "All offence categories"))
        _crime_years = crime_df.index.tolist()[::-1]
        _col_sel, _ = st.columns([1, 3])
        with _col_sel:
            _bar_year = st.selectbox(tr("Jahr", "Year"), options=_crime_years, index=0, key="crime_bar_year")
        _by_area = get_crime_data_by_area()
        _cats_bar = [c for c in CATEGORIES if c != "Straftaten insgesamt"]
        _west = _by_area[_bar_year].get("Moabit West", {})
        _ost  = _by_area[_bar_year].get("Moabit Ost",  {})
        _sorted_cats = sorted(_cats_bar, key=trl) if _is_mobile else sorted(_cats_bar, key=trl, reverse=True)
        _cats_shown = [trl(c) for c in _sorted_cats]
        _vals_west = [_west.get(c, 0) for c in _sorted_cats]
        _vals_ost  = [_ost.get(c, 0)  for c in _sorted_cats]
        _totals    = [w + o for w, o in zip(_vals_west, _vals_ost)]
        fig_bar = go.Figure()
        if _is_mobile:
            fig_bar.add_trace(go.Bar(
                x=_cats_shown, y=_vals_west,
                name="Moabit West", marker_color="#1E88E5", marker_line_width=0,
                legendrank=2,
            ))
            fig_bar.add_trace(go.Bar(
                x=_cats_shown, y=_vals_ost,
                name="Moabit Ost", marker_color="#C0504D", marker_line_width=0,
                legendrank=1,
                text=[_fmt_int(t) for t in _totals],
                textposition="outside",
            ))
            fig_bar.update_layout(
                barmode="stack",
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)"),
                xaxis=dict(tickangle=-40),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                margin=dict(t=40, b=120, r=20),
                height=520,
            )
        else:
            fig_bar.add_trace(go.Bar(
                x=_vals_west, y=_cats_shown, orientation="h",
                name="Moabit West", marker_color="#1E88E5", marker_line_width=0,
                legendrank=2,
            ))
            fig_bar.add_trace(go.Bar(
                x=_vals_ost, y=_cats_shown, orientation="h",
                name="Moabit Ost", marker_color="#C0504D", marker_line_width=0,
                legendrank=1,
                text=[_fmt_int(t) for t in _totals],
                textposition="outside",
            ))
            fig_bar.update_layout(
                barmode="stack",
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                margin=dict(t=40, b=20, r=80),
                height=480,
            )
        st.plotly_chart(fig_bar, width="stretch", config=_plot_config)
        st.caption(tr("Gestapelte Balken: Moabit West (blau) + Moabit Ost (rot). Beschriftung = Gesamtwert.",
                      "Stacked bars: Moabit West (blue) + Moabit Ost (red). Labels show the total."))

with tab_about:
    if _is_mobile:
        col1, col2 = st.container(), st.container()
    else:
        col1, col2 = st.columns(2)
    with col1:
        st.subheader(tr("Über Moabit", "About Moabit"))
        st.markdown(tr("""
Moabit ist ein dichtbevölkerter Ortsteil im Bezirk Mitte, unmittelbar nördlich des Tiergartens gelegen. Der Ortsteil wird vollständig von vier Wasserstraßen umschlossen: Spree, Berlin-Spandauer Schifffahrtskanal, Westhafenkanal und Charlottenburger Verbindungskanal. Diese Insellage verleiht Moabit einen unverwechselbaren Charakter, über 26 Straßen-, Bahn- und Fußgängerbrücken mit der übrigen Stadt verbunden.
""", """
Moabit is a densely populated locality in the Mitte district, directly north of the Tiergarten. It is entirely enclosed by four waterways: the Spree, the Berlin-Spandau Ship Canal, the Westhafen Canal and the Charlottenburg Connecting Canal. This island location gives Moabit its distinctive character; more than 26 road, rail and foot bridges link it to the rest of the city.
"""))

        st.subheader(tr("Bevölkerung & Charakter", "Population & character"))
        st.markdown(tr("""
Moabit ist eines der am dichtesten besiedelten und multikulturellsten Viertel Berlins. Rund **40 %** der Einwohner haben einen Migrationshintergrund: türkische, arabische und osteuropäische Gemeinschaften sind besonders präsent. Verglichen mit aufgewerteten Nachbarvierteln wie Mitte oder Prenzlauer Berg ist Moabit **authentischer und weniger gentrifiziert**; die Mieten sind bisher verhältnismäßig moderat geblieben, steigen aber.

*Daten zur Bevölkerungsstruktur sind im Tab „Bevölkerung“ zu finden.*
""", """
Moabit is one of Berlin's most densely populated and multicultural neighbourhoods. Around **40%** of residents have a migration background, with Turkish, Arab and Eastern European communities particularly present. Compared with gentrified neighbouring areas such as Mitte or Prenzlauer Berg, Moabit is **more authentic and less gentrified**; rents have so far stayed relatively moderate, but they are rising.

*Population figures are in the ‘Population’ tab.*
"""))


        st.subheader(tr("Lage & Verkehr", "Location & transport"))
        st.markdown(tr("""
Der **Berlin Hauptbahnhof** (der wichtigste Eisenbahnknotenpunkt Deutschlands) liegt am östlichen Rand Moabits und bietet hervorragende Anbindung an S-Bahn, U-Bahn, Tram und Fernzüge. Das Regierungsviertel grenzt unmittelbar an, ebenso wie Tiergarten und Charlottenburg.

- **U-Bahn:** U9 (Turmstraße, Birkenstraße)
- **S-Bahn / Fernbahn:** Berlin Hbf, Bellevue
- **Tram:** M10 (Verbindung nach Prenzlauer Berg)
- **Fahrrad:** Gut ausgebautes Radwegenetz entlang der Kanäle

Das **Bundesministerium des Innern** hat seinen Berliner Dienstsitz in Moabit.
""", """
**Berlin Hauptbahnhof** (Germany's most important railway hub) lies on Moabit's eastern edge and offers excellent connections to the S-Bahn, U-Bahn, trams and long-distance trains. The government quarter is directly adjacent, as are Tiergarten and Charlottenburg.

- **U-Bahn:** U9 (Turmstraße, Birkenstraße)
- **S-Bahn / mainline rail:** Berlin Hbf, Bellevue
- **Tram:** M10 (link to Prenzlauer Berg)
- **Cycling:** a well-developed cycle network along the canals

The **Federal Ministry of the Interior** has its Berlin seat in Moabit.
"""))


    with col2:
        st.subheader(tr("Geschichte", "History"))
        st.markdown(tr("""
Im 13. Jahrhundert hieß das Gebiet noch *Große Stadtheide*, später *Kämmereiheide*. Die eigentliche Besiedlung begann **1685**, als Hugenotten (französische Glaubensflüchtlinge) hier angesiedelt wurden. Sie nannten ihre neue Heimat *terre de Moab*, nach dem biblischen Land Moab, der ersten Zufluchtsstätte der Israeliten nach dem Auszug aus Ägypten. 1716 entstand die Kolonie Moabit; 1801 zählte man erst 120 Bewohner.

1818 entstand nördlich davon eine weitere Kolonie, die zur Unterscheidung den Namen **Neu-Moabit** erhielt. Mit der Industrialisierung folgte eine rasche Besiedlung beider Kolonien. **1861** wurde Moabit nach Berlin eingemeindet; bis 1910 war die Bevölkerung auf rund 190 000 angewachsen.

Im 19. Jahrhundert prägten Fabriken von AEG, Schwarzkopf und Löwe das klassische Arbeiterviertel. Von **1920 bis 2000** gehörte Moabit zum Bezirk Tiergarten; seit der Bezirksfusion am 1. Januar 2001 ist es Ortsteil des neuen Bezirks Mitte.
""", """
In the 13th century the area was still called *Große Stadtheide*, later *Kämmereiheide*. Settlement proper began in **1685**, when Huguenots (French Protestant refugees) were settled here. They called their new home *terre de Moab*, after the biblical land of Moab, the Israelites' first place of refuge after the Exodus from Egypt. The colony of Moabit was founded in 1716; in 1801 it still had only 120 inhabitants.

In 1818 a second colony was founded to the north and named **Neu-Moabit** to tell the two apart. Industrialisation brought rapid settlement of both colonies. In **1861** Moabit was incorporated into Berlin; by 1910 its population had grown to around 190,000.

In the 19th century, factories belonging to AEG, Schwarzkopf and Löwe shaped this classic working-class district. From **1920 to 2000** Moabit belonged to the Tiergarten district; since the merger of districts on 1 January 2001 it has been a locality of the new Mitte district.
"""))

        _pop_data = {1801: 120, 1840: 986, 1860: 8200, 1871: 14818, 1880: 29693, 1910: 190000}
        _fig_pop = go.Figure(go.Scatter(
            x=list(_pop_data.keys()),
            y=list(_pop_data.values()),
            mode="lines+markers",
            line=dict(color="#1E88E5", width=2),
            marker=dict(size=7),
            hovertemplate="%{x}: %{y:,.0f}<extra></extra>",
        ))
        _fig_pop.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(tickvals=[1801, 1840, 1860, 1871, 1880, 1910], tickformat="d", showgrid=False, tickangle=45),
            yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)", tickformat=","),
            margin=dict(t=10, b=10, l=10, r=10),
            height=280,
            separators=tr(",.", ".,"),
        )
        st.plotly_chart(_fig_pop, width="stretch", config=_plot_config)
        st.caption(tr("Bevölkerungswachstum Moabits 1801–1910. Quellen: Volkszählungen, Berliner Morgenpost (2012).",
                      "Moabit's population growth 1801–1910. Sources: censuses, Berliner Morgenpost (2012)."))

    st.subheader(tr("Kieze im Überblick", "Moabit's Kieze at a glance"))
    st.markdown(tr("""
Moabit hat keine festen amtlichen Kiezgrenzen; die Grenzen sind fließend. Historisch und städtebaulich werden jedoch sechs bis sieben Hauptkieze unterschieden:
""", """
Moabit has no fixed official Kiez boundaries; they shift depending on who you ask. Historically and in terms of urban development, however, six or seven main Kieze (neighbourhoods) are usually distinguished:
"""))

    # Listed alphabetically. On desktop the i % 3 fill spreads them across three
    # columns so they still read alphabetically left-to-right; on a phone the
    # same list is simply stacked, which keeps that order intact.
    _KIEZE = [
        ("Alt-Moabit & Turmstraße", tr("Die zentralen Lebensadern Moabits. Rund um das Schultheiss Quartier und den Kleinen Tiergarten konzentrieren sich Handel, Gastronomie und öffentliches Leben.", "Moabit's main arteries. Shops, restaurants and public life are concentrated around the Schultheiss Quartier and the Kleiner Tiergarten.")),
        ("Beusselkiez", tr("Traditionelles Arbeiter- und Wohnviertel im Nordwesten, geprägt von gründerzeitlicher Blockbebauung und einer starken Nachbarschaftsidentität.", "Traditional working-class residential area in the north-west, shaped by late-19th-century perimeter blocks and a strong neighbourhood identity.")),
        ("Europacity", tr("Moderne Erweiterung im östlichen Moabit, direkt am Hauptbahnhof. Bürobauten, Neubauwohnungen und Gewerbeflächen prägen dieses noch im Entstehen begriffene Stadtquartier.", "Modern extension in eastern Moabit, right by the Hauptbahnhof. Office buildings, new flats and commercial space define this district, which is still taking shape.")),
        ("Huttenkiez", tr("Mischung aus Wohnen und Industrie entlang der Huttenstraße (auch als ‘Hutteninsel’ bekannt). Rauher Charme, aber zunehmend im Wandel.", "A mix of housing and industry along Huttenstraße (also known as the ‘Hutteninsel’). Rough-edged charm, but changing fast.")),
        ("Lehrter-Straßen-Kiez", tr("Östliches Quartier zwischen Hauptbahnhof und Invalidenstraße, das sich in den vergangenen Jahren stark entwickelt hat.", "Eastern quarter between the Hauptbahnhof and Invalidenstraße that has developed rapidly in recent years.")),
        ("Stephankiez", tr("Einer der bekanntesten und besterhaltenen Gründerzeitkieze Berlins, rund um den Stephanplatz. Stuckfassaden, ruhige Straßen und eine entspannte, fast dörfliche Atmosphäre.", "One of Berlin's best-known and best-preserved late-19th-century (Gründerzeit) neighbourhoods, around Stephanplatz. Stucco façades, quiet streets and a relaxed, almost village-like atmosphere.")),
        ("Westfälisches Viertel", tr("Ruhiges, bürgerlich geprägtes Gründerzeitviertel im Südwesten. Breite Straßen, gepflegte Altbauten und eine entspannte Wohnatmosphäre.", "Quiet, middle-class late-19th-century quarter in the south-west. Wide streets, well-kept period buildings and a relaxed residential atmosphere.")),
    ]

    def _kiez_html(name, desc, style):
        return (f"<div style='{style}'><strong style='font-size:1.1rem'>{name}</strong>"
                f"<br>{desc}</div>")

    if _is_mobile:
        # No fixed height: in a single stacked column it would only add dead space.
        for _name, _desc in _KIEZE:
            st.markdown(_kiez_html(_name, _desc, "padding-bottom:0.9rem"), unsafe_allow_html=True)
    else:
        _ks = "min-height:160px; padding-bottom:0.5rem"
        _kcols = st.columns(3)
        for _i, (_name, _desc) in enumerate(_KIEZE):
            with _kcols[_i % 3]:
                st.markdown(_kiez_html(_name, _desc, _ks), unsafe_allow_html=True)

    st.markdown(tr("""
Darüber hinaus ist Moabit durch das Quartiersmanagement Berlin in zwei offizielle Fördergebiete eingeteilt: **Moabit-Ost** und **Beusselstraße/Moabit-West**. Diese Gebiete erhalten gezielte Förderung für soziale Infrastruktur, Nachbarschaftsprojekte und städtebauliche Entwicklung.
""", """
In addition, Berlin's neighbourhood management programme (Quartiersmanagement) divides Moabit into two official funding areas: **Moabit-Ost** and **Beusselstraße/Moabit-West**. These areas receive targeted funding for social infrastructure, neighbourhood projects and urban development.
"""))

    st.subheader(tr("Orte, Essen & Kultur", "Places, food & culture"))
    st.markdown(tr("""
- **Justizvollzugsanstalt Moabit** und das **Kriminalgericht Moabit**: das größte Kriminalgericht Europas
- **Arminiusmarkthalle** (1891): historische Markthalle mit regionalem und internationalem Angebot; dazu Wochenmarkt Turmstraße (Di & Fr)
- **Kleiner Tiergarten**: zentraler Stadtpark und soziales Zentrum rund um Alt-Moabit und Turmstraße, auch bekannt als sozialer Brennpunkt
- **Fritz-Schloß-Park**: die größte Grünfläche Moabits, entstanden auf einem ehemaligen Exerzierplatz
- **Spreebogenpark**: mit direktem Blick auf den Reichstag; Kanalpromenaden entlang aller vier Wasserstraßen
- **Restaurants:** von türkischen Imbissen bis zur gehobenen Gastronomie
- **Kultur:** Kunsthaus Moabit, freie Theater und Galerien
- **Sport:** Schwimmbad Turmstraße, Sporthallen und Bolzplätze
""", """
- **Moabit prison (JVA Moabit)** and the **Moabit Criminal Court**: the largest criminal court in Europe
- **Arminiusmarkthalle** (1891): historic market hall with regional and international produce; plus the Turmstraße weekly market (Tue & Fri)
- **Kleiner Tiergarten**: central park and social hub around Alt-Moabit and Turmstraße, also known as a social hotspot
- **Fritz-Schloß-Park**: Moabit's largest green space, laid out on a former parade ground
- **Spreebogenpark**: with a direct view of the Reichstag; canal promenades along all four waterways
- **Restaurants:** from Turkish snack bars to fine dining
- **Culture:** Kunsthaus Moabit, independent theatres and galleries
- **Sport:** Turmstraße swimming pool, sports halls and kickabout pitches
"""))

    st.divider()
    st.subheader(tr("Quellen", "Sources"))
    st.markdown(tr("""
- Bezirksamt Mitte: [Ortsteil Moabit](https://www.berlin.de/ba-mitte/ueber-den-bezirk/ortsteile/moabit/)
- Amt für Statistik Berlin-Brandenburg: Volkszählungen und Einwohnerregister
- Wikipedia: [Moabit](https://de.wikipedia.org/wiki/Moabit)
- OpenStreetMap: Geodaten Moabit
- Quartiersmanagement Berlin: [Moabit-Ost](https://www.qm-moabit-ost.de/) und [Beusselstraße/Moabit-West](https://www.stattbau.de/projekte/qm-beusselstrasse/)
- [Moabit Online](https://moabitonline.de/moabit) — lokales Nachrichtenportal
- [Moazin](https://www.moazin.de/) — Magazin für und über Moabit
- [Gebietsinformation Turmstraße](https://www.turmstrasse.de/gebiete/gebietsinformation) — Quartiersmanagement Turmstraße
- Berliner Morgenpost, 2. November 2012: „Kiez im Wandel und Aufbruch“ (Anzeigensonderveröffentlichung)
""", """
- Mitte District Office: [Moabit locality](https://www.berlin.de/ba-mitte/ueber-den-bezirk/ortsteile/moabit/) (German)
- Statistical Office for Berlin-Brandenburg: censuses and population register
- Wikipedia: [Moabit](https://de.wikipedia.org/wiki/Moabit) (German edition)
- OpenStreetMap: geodata for Moabit
- Quartiersmanagement Berlin: [Moabit-Ost](https://www.qm-moabit-ost.de/) and [Beusselstraße/Moabit-West](https://www.stattbau.de/projekte/qm-beusselstrasse/)
- [Moabit Online](https://moabitonline.de/moabit), local news site
- [Moazin](https://www.moazin.de/), a magazine for and about Moabit
- [Gebietsinformation Turmstraße](https://www.turmstrasse.de/gebiete/gebietsinformation), Turmstraße neighbourhood management
- Berliner Morgenpost, 2 November 2012: „Kiez im Wandel und Aufbruch“ (advertising supplement)
"""))
