import base64
import json
import os
import pathlib
import re
import pandas as pd
import requests
import streamlit as st

os.chdir(pathlib.Path(__file__).parent)
import folium
from folium.plugins import MarkerCluster, LocateControl
from streamlit_folium import st_folium

import plotly.graph_objects as go
from layers.transport import fetch_stops, stop_style
from layers.cycling import fetch_cycle_lanes, lane_style, LEGEND as CYCLE_LEGEND
from layers.rent import fetch_wohnlagen, WOL_STYLE
from layers.greenspace import fetch_greenspaces, FEATURE_STYLE, LEGEND as GREEN_LEGEND
from layers.amenities import fetch_amenities, AMENITY_STYLE, LEGEND as AMENITY_LEGEND
from layers.routes import fetch_routes, fetch_routes_full, LEGEND as ROUTE_LEGEND
from layers.bikeshare import fetch_bikeshare_stations
from layers.noise import fetch_noise_data, THRESHOLDS, DB_BANDS
from layers.crime import fetch_crime_data, fetch_crime_data_by_area, fetch_bezirk_comparison, fetch_mitte_lor_data, CATEGORIES, DEFAULT_CATEGORIES
from layers.airquality import (
    fetch_current, fetch_history,
    STATION_NAME, STATION_LAT, STATION_LON,
    MOABIT_STATIONS, LIMITS, INDEX_LABELS,
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
</style>
""", unsafe_allow_html=True)

try:
    _ua = st.context.headers.get("User-Agent", "")
except AttributeError:
    _ua = ""
_is_mobile = any(kw in _ua for kw in ("Mobile", "Android", "iPhone", "iPad"))
_plot_config = {"staticPlot": True} if _is_mobile else {}


_title_size = "1.3rem" if _is_mobile else "1.8rem"
st.markdown(f"<h1 style='font-size:{_title_size}; margin-bottom:0.25rem'>Moabiter Dashboard</h1>", unsafe_allow_html=True)

with open("data/moabit_boundary.geojson", encoding="utf-8") as f:
    boundary = json.load(f)

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

def _fmt_int(n) -> str:
    return f"{int(n):,}".replace(",", ".")

def _fmt_pct(p) -> str:
    return f"{p:.1f}".replace(".", ",") + " %"

def _fmt_float(v, decimals=1) -> str:
    return f"{v:.{decimals}f}".replace(".", ",")

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

@st.cache_data(ttl=60)
def fetch_arrivals(stop_id=HBF_STOP_ID, results=25):
    body = {
        **_HAFAS_BODY,
        "svcReqL": [{"meth": "StationBoard", "req": {
            "stbLoc": {"lid": f"A=1@L={stop_id}@", "type": "S"},
            "type": "ARR",
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
        t_plan   = stop.get("aTimeS", "")
        t_real   = stop.get("aTimeR", t_plan)
        platform = stop.get("aPltfR", stop.get("aPltfS", {})).get("txt", "—")
        arr_str  = f"{t_plan[:2]}:{t_plan[2:4]}" if len(t_plan) >= 4 else "—"
        if t_plan and t_real and t_real != t_plan and len(t_real) >= 4:
            diff = _hhmm_to_minutes(t_real) - _hhmm_to_minutes(t_plan)
            if diff < -720:
                diff += 1440
            delay_str = f"+{diff} min" if diff > 0 else ("pünktlich" if diff == 0 else f"{diff} min")
        else:
            delay_str = "pünktlich"
        rows.append({
            "Icon":       _TYPE_ICON.get(cat, ""),
            "Linie":      name,
            "Typ":        cat,
            "Herkunft":   j.get("dirTxt") or "?",
            "Gleis":      platform,
            "Ankunft":    arr_str,
            "Verspätung": delay_str,
        })
    return rows


@st.cache_data(ttl=60)
def fetch_departures(stop_id=HBF_STOP_ID, results=25):
    body = {
        **_HAFAS_BODY,
        "svcReqL": [{"meth": "StationBoard", "req": {
            "stbLoc": {"lid": f"A=1@L={stop_id}@", "type": "S"},
            "type": "DEP",
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
        t_plan   = stop.get("dTimeS", "")
        t_real   = stop.get("dTimeR", t_plan)
        platform = stop.get("dPltfR", stop.get("dPltfS", {})).get("txt", "—")
        dep_str  = f"{t_plan[:2]}:{t_plan[2:4]}" if len(t_plan) >= 4 else "—"
        if t_plan and t_real and t_real != t_plan and len(t_real) >= 4:
            diff = _hhmm_to_minutes(t_real) - _hhmm_to_minutes(t_plan)
            if diff < -720:
                diff += 1440  # midnight rollover
            delay_str = f"+{diff} min" if diff > 0 else ("pünktlich" if diff == 0 else f"{diff} min")
        else:
            delay_str = "pünktlich"
        rows.append({
            "Icon":        _TYPE_ICON.get(cat, ""),
            "Linie":       name,
            "Typ":         cat,
            "Richtung":    j.get("dirTxt") or "?",
            "Gleis":       platform,
            "Abfahrt":     dep_str,
            "Verspätung":  delay_str,
        })
    return rows

st.sidebar.title("Ebenen")
show_routes = st.sidebar.checkbox("Verkehrslinien", value=True)
show_routes_full = False
if show_routes:
    legend_html = "".join(
        f'<span style="color:{colour}"><b>&#11834;</b></span> {label}<br>'
        for label, colour in ROUTE_LEGEND.items()
    )
    st.sidebar.markdown(f"<small>{legend_html}</small>", unsafe_allow_html=True)
    show_transport = st.sidebar.checkbox("Haltestellen", value=True)
    show_routes_full = st.sidebar.checkbox("Vollständige Linien (außerhalb Moabits)", value=False)
else:
    show_transport = False
st.sidebar.markdown("<hr style='margin:4px 0'>", unsafe_allow_html=True)
show_cycling = st.sidebar.checkbox("Radwege", value=False)
if show_cycling:
    legend_html = "".join(
        f'<span style="color:{colour}"><b>&#11834;</b></span> {label}<br>'
        for label, colour in CYCLE_LEGEND.items()
    )
    st.sidebar.markdown(f"<small>{legend_html}</small>", unsafe_allow_html=True)
show_bikeshare = st.sidebar.checkbox("Leihräder", value=False)
if show_bikeshare:
    st.sidebar.markdown(
        "<small>"
        '<span style="color:green">&#9679;</span> Räder verfügbar<br>'
        '<span style="color:orange">&#9679;</span> Wenige Räder (1–2)<br>'
        '<span style="color:red">&#9679;</span> Keine Räder'
        "</small>",
        unsafe_allow_html=True,
    )
st.sidebar.markdown("<hr style='margin:4px 0'>", unsafe_allow_html=True)
show_wohnlagen = st.sidebar.checkbox("Wohnlagenkarte", value=False)
if show_wohnlagen:
    legend_html = "".join(
        f'<span style="color:{v["colour"]}">&#9632;</span> {v["label"]}<br>'
        for v in [WOL_STYLE["gut"], WOL_STYLE["mittel"], WOL_STYLE["einfach"]]
    )
    st.sidebar.markdown(f"<small>{legend_html}</small>", unsafe_allow_html=True)
show_amenities = st.sidebar.checkbox("Nahversorgung", value=False)
if show_amenities:
    legend_html = "".join(
        f'<span style="color:{colour}">&#9632;</span> {label}<br>'
        for label, colour in AMENITY_LEGEND.items()
    )
    st.sidebar.markdown(f"<small>{legend_html}</small>", unsafe_allow_html=True)
st.sidebar.markdown("<hr style='margin:4px 0'>", unsafe_allow_html=True)
show_greenspaces = st.sidebar.checkbox("Grünflächen", value=False)
if show_greenspaces:
    legend_html = "".join(
        f'<span style="color:{colour}">&#9632;</span> {label}<br>'
        for label, colour in GREEN_LEGEND.items()
    )
    st.sidebar.markdown(f"<small>{legend_html}</small>", unsafe_allow_html=True)
show_airquality = st.sidebar.checkbox("Luftqualität", value=False)
show_noise = st.sidebar.checkbox("Lärmkarte (2004)", value=False)
noise_layer = "a_strlaerm_tag"
if show_noise:
    noise_source = st.sidebar.radio("Quelle", ["Straße", "Schiene"], horizontal=True, key="noise_source")
    noise_time   = st.sidebar.radio("Zeit",   ["Tag",    "Nacht"],   horizontal=True, key="noise_time")
    noise_layer  = {
        ("Straße",  "Tag"):   "a_strlaerm_tag",
        ("Straße",  "Nacht"): "b_strlaerm_nacht",
        ("Schiene", "Tag"):   "ca_laerm_schiene_tag_links,cb_laerm_schiene_tag_rechts",
        ("Schiene", "Nacht"): "da_schienlaerm_nachts_links,db_schienlaerm_nachts_rechts",
    }[(noise_source, noise_time)]
    _theme = st.get_option("theme.base") or "light"
    _legend_file = "images/noise_legend_dark.png" if _theme == "dark" else "images/noise_legend_light.png"
    st.sidebar.image(_legend_file, use_container_width=False)
    st.sidebar.markdown("<small>Quelle: Umweltatlas Berlin 2004</small>", unsafe_allow_html=True)

# --- Tabs ---
tab_map, tab_departures, tab_arrivals, tab_demographics, tab_umwelt, tab_crime, tab_about = st.tabs(["Karte", "Abfahrten Berlin Hbf", "Ankünfte Berlin Hbf", "Bevölkerung", "Umwelt", "Kriminalität", "Über Moabit"])

# --- Map tab ---
with tab_map:
    if show_transport:
        with st.spinner("Lade ÖPNV-Daten..."):
            stops = get_stops()

    if show_cycling:
        with st.spinner("Lade Radwege..."):
            lanes = get_lanes()

    if show_bikeshare:
        with st.spinner("Lade Leihrad-Daten..."):
            bikeshare_stations = get_bikeshare_stations()

    if show_wohnlagen:
        with st.spinner("Lade Wohnlagenkarte..."):
            wohnlagen = get_wohnlagen()

    if show_greenspaces:
        with st.spinner("Lade Grünflächen..."):
            greenspaces = get_greenspaces()

    if show_amenities:
        with st.spinner("Lade Nahversorgung..."):
            amenities = get_amenities()

    if show_routes:
        if show_routes_full:
            with st.spinner("Lade vollständige Linien..."):
                routes = get_routes_full()
        else:
            with st.spinner("Lade Verkehrslinien..."):
                routes = get_routes()

    if "map_center" not in st.session_state:
        st.session_state.map_center = [52.529, 13.341]
    if "map_zoom" not in st.session_state:
        st.session_state.map_zoom = 13 if _is_mobile else 14
    if show_airquality and not st.session_state.get("_prev_airquality", False):
        st.session_state.map_zoom = max(st.session_state.map_zoom - 1, 10)
    st.session_state._prev_airquality = show_airquality

    m = folium.Map(
        location=st.session_state.map_center,
        zoom_start=st.session_state.map_zoom,
        tiles="CartoDB dark_matter",
    )

    folium.GeoJson(
        boundary,
        style_function=lambda _: {
            "color": "#1D9E75",
            "weight": 2.5,
            "fillColor": "#1D9E75",
            "fillOpacity": 0.08,
        }
    ).add_to(m)

    if show_greenspaces:
        folium.GeoJson(
            {"type": "FeatureCollection", "features": greenspaces},
            style_function=lambda f: FEATURE_STYLE.get(
                f["properties"].get("type", ""),
                {"color": "#1D9E75", "fillColor": "#1D9E75", "fillOpacity": 0.3, "weight": 1}
            ),
            tooltip=folium.GeoJsonTooltip(
                fields=["name", "type"],
                aliases=["Name:", "Typ:"],
            ),
        ).add_to(m)

    if show_amenities:
        for feature in amenities:
            amenity = feature["amenity"]
            style = AMENITY_STYLE.get(amenity, {"colour": "#888888", "label": amenity})
            name = feature["name"] or style["label"]
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
            ).add_to(m)

    if show_routes:
        folium.GeoJson(
            {"type": "FeatureCollection", "features": routes},
            style_function=lambda f: {
                "color":   f["properties"]["colour"],
                "weight":  f["properties"]["weight"],
                "opacity": f["properties"]["opacity"],
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["ref", "name"],
                aliases=["Linie:", "Route:"],
            ),
        ).add_to(m)

    if show_cycling:
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
                    "name": tags.get("name", tags.get("cycleway", "Radweg")),
                }
            })
        folium.GeoJson(
            {"type": "FeatureCollection", "features": cycle_features},
            style_function=lambda f: {
                "color":   f["properties"]["color"],
                "weight":  3,
                "opacity": 0.8,
            },
            tooltip=folium.GeoJsonTooltip(fields=["name"], aliases=["Radweg:"]),
        ).add_to(m)

    if show_bikeshare:
        for station in bikeshare_stations:
            folium.Marker(
                location=[station["lat"], station["lon"]],
                icon=folium.Icon(color=station["colour"], icon="bicycle", prefix="fa"),
                tooltip=folium.Tooltip(
                    f"<span style='font-size:15px'>"
                    f"<b>{station['name']}</b><br>"
                    f"Fahrräder verfügbar: {station['bikes']}<br>"
                    f"Stellplätze frei: {station['docks']}<br>"
                    f"Kapazität: {station['capacity']}"
                    f"</span>"
                ),
            ).add_to(m)

    if show_wohnlagen:
        wol_colours = {k: v["colour"] for k, v in WOL_STYLE.items()}

        folium.GeoJson(
            {"type": "FeatureCollection", "features": wohnlagen},
            style_function=lambda feature: {
                "radius": 4,
                "color": wol_colours.get(feature["properties"].get("wol", ""), "#888888"),
                "fillColor": wol_colours.get(feature["properties"].get("wol", ""), "#888888"),
                "fillOpacity": 0.7,
                "weight": 0,
            },
            marker=folium.CircleMarker(radius=4, weight=0, fill=True, fill_opacity=0.7),
            tooltip=folium.GeoJsonTooltip(
                fields=["strasse", "hnr", "wol"],
                aliases=["Straße:", "Nr.:", "Wohnlage:"],
            ),
        ).add_to(m)

    if show_transport:
        cluster = MarkerCluster(name="Transport stops").add_to(m)
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
        with st.spinner("Lade Luftqualitätsdaten..."):
            aq_current = get_airquality_current()
        readings = "<br>".join(
            f"{label}: {v['value']} {v['unit']}"
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
        ).add_to(m)
        for s in MOABIT_STATIONS:
            folium.Marker(
                location=[s["lat"], s["lon"]],
                icon=folium.Icon(color="lightgray", icon="cloud", prefix="fa"),
                tooltip=folium.Tooltip(
                    "<span style='font-size:15px'>"
                    "<b>" + s['name'] + "</b>"
                    "<br>" + s['years'] + " · Keine Daten verfügbar"
                    "</span>"
                ),
            ).add_to(m)

    if show_noise:
        folium.WmsTileLayer(
            url="https://gdi.berlin.de/services/wms/ua_laerm_2004",
            layers=noise_layer,
            fmt="image/png",
            transparent=True,
            version="1.3.0",
            attr="Umweltatlas Berlin 2004",
            opacity=0.7,
        ).add_to(m)

    LocateControl(auto_start=False).add_to(m)

    map_data = st_folium(
        m,
        use_container_width=True,
        height=350 if _is_mobile else 500,
        returned_objects=["last_object_clicked"],
        key="moabit_map",
    )

    if map_data.get("center"):
        st.session_state.map_center = [map_data["center"]["lat"], map_data["center"]["lng"]]
    if map_data.get("zoom"):
        st.session_state.map_zoom = map_data["zoom"]

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
        st.markdown(f"**{sel['name']}** – nächste Abfahrten")
        with st.spinner("Lade Abfahrtsdaten..."):
            try:
                rows = fetch_departures(stop_id=sel["id"], results=12)
            except Exception as e:
                rows = []
                st.error(f"Abfahrtsdaten konnten nicht geladen werden: {e}")
        if not rows:
            st.caption("Keine Abfahrtsdaten für diese Haltestelle verfügbar.")
        else:
            if _is_mobile:
                df_stop = pd.DataFrame([
                    {"Linie": r["Linie"], "Richtung": r["Richtung"], "Abfahrt": r["Abfahrt"], "Versp.": r["Verspätung"]}
                    for r in rows
                ])
                st.table(df_stop)
            else:
                st.dataframe(
                    rows,
                    use_container_width=True,
                    hide_index=True,
                    height="content",
                    column_order=["Icon", "Linie", "Typ", "Richtung", "Abfahrt", "Verspätung"],
                    column_config={
                        "Icon":       st.column_config.ImageColumn("", width="small"),
                        "Linie":      st.column_config.TextColumn("Linie",      width="small"),
                        "Typ":        st.column_config.TextColumn("Typ",        width="small"),
                        "Richtung":   st.column_config.TextColumn("Richtung"),
                        "Abfahrt":    st.column_config.TextColumn("Abfahrt",    width="small"),
                        "Verspätung": st.column_config.TextColumn("Verspätung", width="small"),
                    },
                )

# --- Demographics tab ---
with tab_demographics:
    trend = get_population_over_time()

    _latest_year = int(trend.iloc[-1]["year"]) if not trend.empty else 2025
    st.caption(f"Quelle: Amt für Statistik Berlin-Brandenburg, Einwohnerregisterstatistik 31.12.{_latest_year}")

    # --- Headline metrics ---
    if not trend.empty:
        latest = trend.iloc[-1]
        if _is_mobile:
            _metrics_2col([
                {"label": "Einwohner",          "value": _fmt_int(latest['total'])},
                {"label": "Frauenanteil",        "value": _fmt_pct(latest['female_pct'])},
                {"label": "Ausländeranteil",     "value": _fmt_pct(latest['foreign_pct'])},
                {"label": "18- bis 44-Jährige", "value": _fmt_pct(latest['young_adult_pct'])},
            ])
        else:
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Einwohner",          _fmt_int(latest['total']))
            col2.metric("Frauenanteil",        _fmt_pct(latest['female_pct']))
            col3.metric("Ausländeranteil",     _fmt_pct(latest['foreign_pct']))
            col4.metric("18- bis 44-Jährige", _fmt_pct(latest['young_adult_pct']))

    st.divider()

    # --- Age distribution and population trend side by side ---
    if not trend.empty:
        age_years = sorted(trend["year"].tolist())
        col_sel, _ = st.columns([1, 3])
        with col_sel:
            selected_age_year = st.selectbox(
                "Jahr", options=age_years, index=len(age_years) - 1,
                key="age_year"
            )
        age_row = trend[trend["year"] == selected_age_year].iloc[0]
        age_data = {
            "unter 6":  int(age_row["u6"]),
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

    col_age, col_pop = st.columns(2)

    with col_age:
        st.subheader(f"Bevölkerung nach Altersgruppe ({title_year})")
        fig_age = go.Figure(go.Bar(
            x=list(age_data.keys()),
            y=list(age_data.values()),
            marker_color="#2E6B8A",
            text=[_fmt_int(v) for v in age_data.values()],
            textposition="outside",
        ))
        fig_age.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)"),
            xaxis_title="Altersgruppe",
            yaxis_title="Bevölkerung",
            margin=dict(t=20, b=20),
        )
        st.plotly_chart(fig_age, use_container_width=True, config=_plot_config)

    _yr0, _yr1 = "–", "–"
    with col_pop:
        if not trend.empty:
            first, last = trend.iloc[0]["total"], trend.iloc[-1]["total"]
            pct = (last - first) / first * 100
            direction = "Anstieg" if pct > 0 else "Rückgang"
            _yr0, _yr1 = int(trend.iloc[0]["year"]), int(trend.iloc[-1]["year"])
            st.subheader(f"Bevölkerungsentwicklung {_yr0}–{_yr1}")
            fig_pop = go.Figure(go.Scatter(
                x=trend["year"], y=trend["total"],
                mode="lines+markers+text",
                line=dict(color="#2E6B8A", width=2.5),
                marker=dict(size=8, color="#2E6B8A"),
                text=[_fmt_int(v) for v in trend["total"]],
                textposition="top center",
                textfont=dict(size=11),
            ))
            fig_pop.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)"),
                xaxis=dict(tickmode="linear", dtick=1),
                xaxis_title="Jahr",
                yaxis_title="Bevölkerung",
                margin=dict(t=20, b=20),
            )
            st.plotly_chart(fig_pop, use_container_width=True, config=_plot_config)
            st.caption(
                f"{direction} um {_fmt_pct(abs(pct))} zwischen 2021 ({_fmt_int(first)} Einwohner) "
                f"und 2025 ({_fmt_int(last)} Einwohner). "
                "Die Zeitreihe beginnt 2021, da Berlins LOR-Planungsraumbezirke am 1. Januar 2021 "
                "neu strukturiert wurden und ältere Daten für Moabits Planungsräume nicht vergleichbar sind."
            )

    if not trend.empty:
        st.divider()

        col_stack, col_comp = st.columns(2)

        # --- Age structure shift (stacked bar) ---
        with col_stack:
            st.subheader("Altersstruktur im Zeitverlauf")
            age_cols = {
                "unter 6":  ("u6",     "#C89030", 8),
                "6–14":     ("6_15",   "#6B8E23", 7),
                "15–17":    ("15_18",  "#2F6B4F", 6),
                "18–26":    ("18_27",  "#2E6B8A", 5),
                "27–44":    ("27_45",  "#3B4D8A", 4),
                "45–54":    ("45_55",  "#6A3D8A", 3),
                "55–64":    ("55_65",  "#8A3D6A", 2),
                "65+":      ("65plus", "#7A3030", 1),
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
                xaxis_title="Jahr",
                yaxis_title="Bevölkerung",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                margin=dict(t=40, b=20),
                height=420,
            )
            st.plotly_chart(fig_stack, use_container_width=True, config=_plot_config)

        # --- Population composition over time ---
        with col_comp:
            st.subheader(f"Bevölkerungszusammensetzung (%, {_yr0}–{_yr1})")
            mig_trend = get_migration_over_time()
            fig_ratios = go.Figure()
            ratio_series = {
                "Mit Migrationshintergrund":    (mig_trend,  "with_mig_bg_pct",  "#7A3030"),
                "Ausländer/innen":              (mig_trend,  "foreign_pct",       "#C06040"),
                "Deutsche mit MH":              (mig_trend,  "german_mig_pct",    "#A07060"),
                "Deutsche ohne MH":             (mig_trend,  "german_no_mig_pct", "#2F6B4F"),
                "18- bis 44-Jährige":           (trend,      "young_adult_pct",   "#2E6B8A"),
                "unter 18":                     (trend,      "u18_pct",           "#C89030"),
                "55 und älter":                 (trend,      "senior_pct",        "#78909C"),
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
                    ticksuffix=" %",
                ),
                xaxis=dict(tickmode="linear", dtick=1),
                xaxis_title="Jahr",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                margin=dict(t=60, b=20),
                height=420,
            )
            st.plotly_chart(fig_ratios, use_container_width=True, config=_plot_config)
            st.caption(
                "Migrationshintergrund umfasst sowohl Ausländer/innen als auch Deutsche, "
                "die selbst oder deren Eltern nach Deutschland zugewandert sind."
            )

    # --- Nationality breakdown over time ---
    nat_trend = get_nationality_over_time()
    if not nat_trend.empty:
        st.divider()
        st.subheader(f"Einwohner/innen mit Migrationshintergrund nach Herkunft ({_yr0}–{_yr1})")
        st.caption(
            "Einzelne Länder-/Regionenzählungen aus T4-Tabelle. "
            "Kategorien sind auf dieser Ebene nicht überlappend. "
            "Einige Länder erscheinen nur in bestimmten Jahren aufgrund von Berichtsänderungen."
        )

        # Year selector
        years = sorted(nat_trend["year"].tolist())
        col_sel, _ = st.columns([1, 3])
        with col_sel:
            selected_year = st.selectbox("Jahr", options=years, index=len(years) - 1, key="nat_year")
        row = nat_trend[nat_trend["year"] == selected_year].iloc[0]
        nat_data = {
            col: int(row[col])
            for col in nat_trend.columns
            if col != "year" and int(row[col]) > 0
        }
        # Sort alphabetically so colour assignment is stable across years
        sorted_nat = dict(sorted(nat_data.items()))

        col_left, col_right = st.columns([1, 1])

        # Donut for selected year
        with col_left:
            st.markdown(f"**Zusammensetzung {selected_year}**")
            fig_donut = go.Figure(go.Pie(
                labels=list(sorted_nat.keys()),
                values=list(sorted_nat.values()),
                marker=dict(colors=[COUNTRY_COLOURS.get(k, "#CCCCCC") for k in sorted_nat]),
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
            st.plotly_chart(fig_donut, use_container_width=True, config=_plot_config)

        # Top nationalities trend lines
        with col_right:
            st.markdown("**Wichtigste Nationalitäten im Zeitverlauf**")
            # Pick top 8 by latest year value
            latest = nat_trend[nat_trend["year"] == max(years)].iloc[0]
            nat_cols = [c for c in nat_trend.columns if c != "year"]
            top_cols = sorted(nat_cols, key=lambda c: latest.get(c, 0), reverse=True)[:8]

            fig_trend = go.Figure()
            for col in top_cols:
                colour = COUNTRY_COLOURS.get(col, "#CCCCCC")
                fig_trend.add_trace(go.Scatter(
                    x=nat_trend["year"],
                    y=nat_trend[col],
                    mode="lines+markers",
                    name=col,
                    line=dict(color=colour, width=2),
                    marker=dict(size=6, color=colour),
                ))
            fig_trend.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)"),
                xaxis=dict(tickmode="linear", dtick=1),
                xaxis_title="Jahr",
                yaxis_title="Bevölkerung",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                margin=dict(t=40, b=20),
                height=480,
            )
            st.plotly_chart(fig_trend, use_container_width=True, config=_plot_config)

        st.caption(
            "**Hinweis zu Berichtsänderungen:** Die Ausgabe 2025 hat die T4-Ländergliederung umstrukturiert. "
            "Mehrere aggregierte Gruppen aus 2021–2024 (islamische/OIC-Länder, arabische Länder, "
            "ehemaliges Jugoslawien, ehemalige Sowjetunion) wurden durch einzelne Länderspalten ersetzt, "
            "darunter neue Einträge für Afghanistan, Irak, China und Indien. "
            "Zahlen für Syrien, Iran und einige andere Länder sind daher über die Grenze 2024–2025 "
            "nicht direkt vergleichbar."
        )

    # --- IBB asking rent trend ---
    st.divider()
    st.subheader("Angebotsmieten nach Bezirk 2008–2025 (€/m², netto kalt)")

    # Mitte midpoint years for overlapping reporting periods:
    # 2008/09 → 2009, 2009/10 → 2010, 2011/12 → 2012, 2012/13 → 2013, 2013/14 → 2014
    IBB_DATA = {
        "year": [2009, 2010, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025],
        "Mitte":                      [5.37, 6.18, 8.03, 9.39, 9.36, 10.06, 10.51, 12.77, 12.51, 13.45, 13.70, 14.00, 15.46, 18.26, 19.91, 20.00],
        "Friedrichshain-Kreuzberg":   [6.42, 7.00, 8.61, 9.64, 9.98, 10.99, 11.50, 12.50, 12.94, 13.01, 13.11, 13.52, 14.85, 18.33, 19.42, 19.40],
        "Pankow":                     [6.13, 6.73, 8.00, 8.56, 8.99,  9.45,  9.99, 10.86, 10.97, 10.96, 10.50, 11.73, 12.50, 14.93, 17.00, 17.00],
        "Charlottenburg-Wilmersdorf": [6.56, 7.53, 8.93, 9.86, 9.49, 10.00, 10.53, 11.86, 12.00, 12.63, 12.38, 13.29, 15.00, 17.20, 19.39, 19.17],
        "Spandau":                    [5.26, 5.28, 5.93, 6.48, 6.58,  6.99,  7.35,  7.95,  8.59,  8.86,  8.53,  8.22,  8.67, 10.13, 12.00, 12.50],
        "Steglitz-Zehlendorf":        [6.29, 6.88, 7.99, 8.50, 8.50,  8.87,  9.38, 10.00, 10.44, 10.70, 10.31, 11.03, 12.31, 13.33, 14.59, 15.00],
        "Tempelhof-Schöneberg":       [5.84, 6.23, 7.49, 8.00, 8.01,  8.50,  9.00,  9.97, 10.30, 10.52,  9.97, 10.22, 11.31, 12.94, 14.67, 15.79],
        "Neukölln":                   [5.19, 5.57, 6.70, 7.33, 7.73,  8.57,  9.00, 10.00, 10.00, 10.10,  9.38,  9.85, 10.55, 13.00, 14.50, 13.61],
        "Treptow-Köpenick":           [5.55, 5.80, 6.55, 7.08, 7.12,  7.81,  8.24,  9.16,  9.62,  9.93, 10.19, 11.00, 11.60, 13.56, 14.45, 15.60],
        "Marzahn-Hellersdorf":        [4.86, 4.85, 5.08, 5.55, 5.80,  5.76,  6.51,  7.16,  7.77,  7.90,  8.02,  8.26,  9.29, 10.61, 11.38, 11.56],
        "Lichtenberg":                [5.51, 5.65, 6.53, 7.01, 7.50,  8.10,  8.80,  9.72,  9.53,  9.27,  9.08,  8.50, 10.45, 12.00, 15.15, 13.33],
        "Reinickendorf":              [5.26, 5.49, 6.31, 6.86, 6.92,  7.50,  8.00,  8.73,  9.17,  9.42,  8.84,  8.99,  9.66, 10.61, 12.15, 12.80],
        "Berlin (median)":            [5.82, 6.17, 7.40, 8.05, 8.25,  8.80,  9.07, 10.15, 10.32, 10.45, 10.14, 10.55, 11.54, 13.99, 15.74, 15.78],
    }

    ibb_years = IBB_DATA["year"]
    bezirke = [k for k in IBB_DATA if k != "year"]

    # Highlight Mitte and Berlin median, mute the rest
    BEZIRK_COLOURS = {
        "Mitte":                      "#7A3030",
        "Berlin (median)":            "#9E9E9E",
        "Friedrichshain-Kreuzberg":   "#2E6B8A",
        "Pankow":                     "#2F6B4F",
        "Charlottenburg-Wilmersdorf": "#B8860B",
        "Spandau":                    "#6A3D8A",
        "Steglitz-Zehlendorf":        "#6B8E23",
        "Tempelhof-Schöneberg":       "#A07060",
        "Neukölln":                   "#3B4D8A",
        "Treptow-Köpenick":           "#308070",
        "Marzahn-Hellersdorf":        "#604090",
        "Lichtenberg":                "#8A3D6A",
        "Reinickendorf":              "#708050",
    }

    fig_rent = go.Figure()
    for bezirk in bezirke:
        is_key = bezirk == "Mitte"
        is_berlin = bezirk == "Berlin (median)"
        fig_rent.add_trace(go.Scatter(
            x=ibb_years,
            y=IBB_DATA[bezirk],
            mode="lines+markers",
            name=bezirk,
            line=dict(
                color=BEZIRK_COLOURS.get(bezirk, "#888888"),
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
    st.plotly_chart(fig_rent, use_container_width=True, config=_plot_config)
    st.caption(
        "Moabit gehört zum Bezirk Mitte (dunkelrote Linie) – keine moabitspezifischen Mietdaten verfügbar. "
        "Berliner Median als gestrichelte graue Linie. "
        "Frühe Datenpunkte verwenden überlappende Berichtszeiträume (z. B. 2008/09 → 2009); "
        "keine Daten für 2011 und 2014. "
        "Quelle: IBB Wohnungsmarktbericht 2008–2025, Tabellenbände, netto kalt."
    )

# --- Departures tab ---
with tab_departures:
    col_title, col_btn = st.columns([8, 1])
    col_title.subheader("Abfahrten Berlin Hauptbahnhof")
    if col_btn.button("Aktualisieren", use_container_width=True, key="btn_departures"):
        st.rerun()
    with st.spinner("Lade Abfahrtsdaten..."):
        try:
            rows = fetch_departures()
        except Exception as e:
            st.error(f"Abfahrtsdaten konnten nicht geladen werden: {e}")
            rows = []
    if rows:
        _dep_cols = ["Icon", "Linie", "Richtung", "Gleis", "Abfahrt", "Verspätung"] if _is_mobile else ["Icon", "Linie", "Typ", "Richtung", "Gleis", "Abfahrt", "Verspätung"]
        st.dataframe(
            rows,
            use_container_width=True,
            hide_index=True,
            height="content",
            column_order=_dep_cols,
            column_config={
                "Icon":       st.column_config.ImageColumn("", width="small"),
                "Linie":      st.column_config.TextColumn("Linie",                                        width="small"),
                "Typ":        st.column_config.TextColumn("Typ",                                          width="small"),
                "Richtung":   st.column_config.TextColumn("Richtung"),
                "Gleis":      st.column_config.TextColumn("Gleis",                                        width="small"),
                "Abfahrt":    st.column_config.TextColumn("Abfahrt",                                      width="small"),
                "Verspätung": st.column_config.TextColumn("Verspätung" if not _is_mobile else "Versp.",   width="small"),
            },
        )
    else:
        st.info("Keine Abfahrten gefunden.")

with tab_arrivals:
    col_title, col_btn = st.columns([8, 1])
    col_title.subheader("Ankünfte Berlin Hauptbahnhof")
    if col_btn.button("Aktualisieren", use_container_width=True, key="btn_arrivals"):
        st.rerun()
    with st.spinner("Lade Ankunftsdaten..."):
        try:
            rows = fetch_arrivals()
        except Exception as e:
            st.error(f"Ankunftsdaten konnten nicht geladen werden: {e}")
            rows = []
    if rows:
        _arr_cols = ["Icon", "Linie", "Herkunft", "Gleis", "Ankunft", "Verspätung"] if _is_mobile else ["Icon", "Linie", "Typ", "Herkunft", "Gleis", "Ankunft", "Verspätung"]
        st.dataframe(
            rows,
            use_container_width=True,
            hide_index=True,
            height="content",
            column_order=_arr_cols,
            column_config={
                "Icon":       st.column_config.ImageColumn("", width="small"),
                "Linie":      st.column_config.TextColumn("Linie",                                        width="small"),
                "Typ":        st.column_config.TextColumn("Typ",                                          width="small"),
                "Herkunft":   st.column_config.TextColumn("Herkunft"),
                "Gleis":      st.column_config.TextColumn("Gleis",                                        width="small"),
                "Ankunft":    st.column_config.TextColumn("Ankunft",                                      width="small"),
                "Verspätung": st.column_config.TextColumn("Verspätung" if not _is_mobile else "Versp.",   width="small"),
            },
        )
    else:
        st.info("Keine Ankünfte gefunden.")

# --- Umwelt tab ---
with tab_umwelt:
    st.caption(f"Messstation: {STATION_NAME} (DEBE010) · Quelle: Umweltbundesamt")

    with st.spinner("Lade Luftqualitätsdaten..."):
        try:
            aq_current = get_airquality_current()
            aq_history = get_airquality_history()
        except Exception as e:
            st.error(f"Luftqualitätsdaten konnten nicht geladen werden: {e}")
            aq_current = {}
            aq_history = pd.DataFrame()

    if aq_current:
        st.subheader("Aktuelle Luftqualität")
        if _is_mobile:
            _aq_items = []
            for label, data in aq_current.items():
                idx = data["index"]
                idx_label, idx_colour = INDEX_LABELS.get(idx, ("–", "#9E9E9E"))
                limit = LIMITS.get(label)
                delta = (f"{data['value'] - limit:+.0f}".replace(".", ",") + " µg/m³ ggü. Grenzwert") if limit else None
                _delta_colour = "#ff4b4b" if (limit and data["value"] > limit) else "#21c354"
                _aq_items.append({
                    "label": label + " (" + data["unit"] + ")",
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
                limit = LIMITS.get(label)
                delta = (f"{data['value'] - limit:+.0f}".replace(".", ",") + " µg/m³ ggü. Grenzwert") if limit else None
                delta_colour = "inverse" if (limit and data["value"] > limit) else "normal"
                col.metric(
                    label=f"{label} ({data['unit']})",
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
        st.subheader("Luftqualität im Jahresverlauf (Tagesmittelwerte)")
        fig_aq = go.Figure()
        colour_map = {"NO₂": "#C0504D", "PM₁₀": "#FB8C00", "PM₂,₅": "#8E24AA", "O₃": "#1E88E5"}
        for col in [c for c in aq_history.columns if c != "date"]:
            fig_aq.add_trace(go.Scatter(
                x=aq_history["date"],
                y=aq_history[col],
                mode="lines",
                name=col,
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
                    annotation_text=f"{label} Grenzwert",
                    annotation_position="right",
                    annotation_font_size=10,
                )
        fig_aq.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)", title="µg/m³"),
            xaxis_title="Datum",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            margin=dict(t=40, b=20),
            height=420,
        )
        st.plotly_chart(fig_aq, use_container_width=True, config=_plot_config)
        st.caption(
            "Gestrichelte Linien zeigen EU-Grenzwerte: NO₂ 40 µg/m³ (Jahresmittel), "
            "PM₁₀ 50 µg/m³ (Tagesmittel), PM₂,₅ 25 µg/m³ (Jahresmittel), O₃ 120 µg/m³ (8-Stunden-Maximum). "
            "O₃ steigt im Sommer — die 8-Stunden-Maxima liegen über den Tagesmitteln. Hinweis: Für den gesamten Dezember 2025 liegt nur ein Datenpunkt vor (am 31. Dezember) – die Messstation war mit ziemlicher Sicherheit aufgrund von Wartungs- oder Reparaturarbeiten außer Betrieb."
        )

    # --- Noise section ---
    st.divider()
    st.subheader("Straßenverkehrslärm (Umweltatlas Berlin 2004)")
    st.caption(
        "Beurteilungspegel entlang der Straßenabschnitte im Moabiter Gebiet (ca. Begrenzungsrechteck). "
        "Quelle: Senatsverwaltung für Stadtentwicklung, Umweltatlas 2004."
    )

    with st.spinner("Lade Lärmdaten..."):
        try:
            noise = get_noise_data()
        except Exception as e:
            st.error(f"Lärmdaten konnten nicht geladen werden: {e}")
            noise = None

    if noise:
        m_data = noise["metrics"]

        # Headline metrics
        if _is_mobile:
            _metrics_2col([
                {"label": "Straßenabschnitte",  "value": m_data["n_segments"]},
                {"label": "Median Tag",          "value": f"{_fmt_float(m_data['median_day'])} dB"},
                {"label": "Median Nacht",        "value": f"{_fmt_float(m_data['median_night'])} dB"},
                {"label": "Tag-Nacht-Differenz", "value": f"{_fmt_float(m_data['median_day'] - m_data['median_night'])} dB"},
            ])
        else:
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Straßenabschnitte",    m_data["n_segments"])
            col2.metric("Median Tag",           f"{_fmt_float(m_data['median_day'])} dB")
            col3.metric("Median Nacht",         f"{_fmt_float(m_data['median_night'])} dB")
            col4.metric("Tag-Nacht-Differenz",  f"{_fmt_float(m_data['median_day'] - m_data['median_night'])} dB")

        st.markdown(
            f"**{_fmt_float(m_data['above_day_pct'])} %** der Abschnitte überschreiten den EU-Richtwert tagsüber ({THRESHOLDS['Tag']} dB) · "
            f"**{_fmt_float(m_data['above_night_pct'])} %** nachts ({THRESHOLDS['Nacht']} dB)"
        )

        st.divider()
        col_dist, col_top = st.columns(2)

        # Distribution chart
        with col_dist:
            st.subheader("Pegelverteilung: Tag vs. Nacht")
            colours = {"Tag": "#C0504D", "Nacht": "#1E88E5"}
            fig_dist = go.Figure()
            for col_name in ["Tag", "Nacht"]:
                fig_dist.add_trace(go.Bar(
                    name=col_name,
                    x=DB_BANDS,
                    y=noise["dist"][col_name],
                    marker_color=colours[col_name],
                ))
            fig_dist.add_vline(
                x=1.5, line_dash="dot", line_color="white", opacity=0.4,
                annotation_text=f"EU-Richtwert Tag ({THRESHOLDS['Tag']} dB)",
                annotation_font_size=10, annotation_position="top right",
            )
            fig_dist.update_layout(
                barmode="group",
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)", title="Anzahl Abschnitte"),
                xaxis_title="Pegelklasse (dB)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                margin=dict(t=40, b=20),
                height=380,
            )
            st.plotly_chart(fig_dist, use_container_width=True, config=_plot_config)

        # Top streets chart
        with col_top:
            st.subheader("Lauteste Straßen (Tagesmittel)")
            top_df = noise["top"].sort_values("dB (Tag)")
            fig_top = go.Figure(go.Bar(
                x=top_df["dB (Tag)"],
                y=top_df["Straße"],
                orientation="h",
                marker_color=[
                    "#C0504D" if v >= 70 else "#FB8C00" if v >= 65 else "#FDD835"
                    for v in top_df["dB (Tag)"]
                ],
                text=[_fmt_float(v) for v in top_df["dB (Tag)"]],
                textposition="outside",
            ))
            fig_top.add_vline(
                x=THRESHOLDS["Tag"], line_dash="dot", line_color="white", opacity=0.4,
                annotation_text=f"EU-Richtwert ({THRESHOLDS['Tag']} dB)",
                annotation_font_size=10, annotation_position="top right",
            )
            fig_top.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)", title="dB"),
                xaxis_range=[50, 78],
                margin=dict(t=40, b=20, r=60),
                height=380,
            )
            st.plotly_chart(fig_top, use_container_width=True, config=_plot_config)

# --- Kriminalität tab ---
with tab_crime:
    _BZ_COLOURS = {
        "Charlottenburg-Wilmersdorf": "#1E88E5",
        "Friedrichshain-Kreuzberg":   "#43A047",
        "Lichtenberg":                "#8E24AA",
        "Marzahn-Hellersdorf":        "#00ACC1",
        "Mitte":                      "#C0504D",
        "Neukölln":                     "#FB8C00",
        "Pankow":                     "#6D4C41",
        "Reinickendorf":              "#546E7A",
        "Spandau":                    "#F4511E",
        "Steglitz-Zehlendorf":        "#039BE5",
        "Tempelhof-Schöneberg":       "#7CB342",
        "Treptow-Köpenick":           "#FFB300",
    }
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
    st.caption("Quelle: Polizei Berlin, Kriminalitätsatlas (PKS) · Moabit West + Ost kombiniert")

    with st.spinner("Lade Kriminalitätsdaten..."):
        try:
            crime_df = get_crime_data()
        except Exception as e:
            st.error(f"Kriminalitätsdaten konnten nicht geladen werden: {e}")
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
            return f"{sign}{_fmt_int(d)} ggü. {prev_year}"

        if _is_mobile:
            _metrics_2col([
                {"label": f"Straftaten insgesamt ({latest_year})", "value": _fmt_int(total_latest),
                 "delta": _crime_delta(delta_total),
                 "delta_colour": "#ff4b4b" if delta_total > 0 else "#21c354"},
                {"label": f"Kieztaten ({latest_year})", "value": _fmt_int(kieztaten_latest),
                 "delta": _crime_delta(delta_kiez),
                 "delta_colour": "#ff4b4b" if delta_kiez > 0 else "#21c354"},
                {"label": f"Fahrraddiebstahl ({latest_year})", "value": _fmt_int(fahrrad_latest),
                 "delta": _crime_delta(delta_fahrrad),
                 "delta_colour": "#ff4b4b" if delta_fahrrad > 0 else "#21c354"},
                {"label": f"Wohnraumeinbruch ({latest_year})", "value": _fmt_int(einbruch_latest),
                 "delta": _crime_delta(delta_einbruch),
                 "delta_colour": "#ff4b4b" if delta_einbruch > 0 else "#21c354"},
            ])
        else:
            col1, col2, col3, col4 = st.columns(4)
            col1.metric(f"Straftaten insgesamt ({latest_year})", _fmt_int(total_latest),
                        delta=_crime_delta(delta_total),
                        delta_color="inverse" if delta_total > 0 else "normal")
            col2.metric(f"Kieztaten ({latest_year})", _fmt_int(kieztaten_latest),
                        delta=_crime_delta(delta_kiez),
                        delta_color="inverse" if delta_kiez > 0 else "normal")
            col3.metric(f"Fahrraddiebstahl ({latest_year})", _fmt_int(fahrrad_latest),
                        delta=_crime_delta(delta_fahrrad),
                        delta_color="inverse" if delta_fahrrad > 0 else "normal")
            col4.metric(f"Wohnraumeinbruch ({latest_year})", _fmt_int(einbruch_latest),
                        delta=_crime_delta(delta_einbruch),
                        delta_color="inverse" if delta_einbruch > 0 else "normal")

        st.divider()

        # --- Bezirk comparison ---
        st.subheader("Straftaten insgesamt im Berliner Vergleich")
        st.caption("Moabit ist ein Ortsteil von Mitte — die Balken zeigen Bezirkswerte, nicht Moabit direkt.")
        with st.spinner("Lade Bezirksdaten..."):
            try:
                bz_fall, bz_hz = get_bezirk_comparison()
            except Exception as e:
                st.error(f"Bezirksdaten konnten nicht geladen werden: {e}")
                bz_fall, bz_hz = None, None

        if bz_fall is not None:
            _bz_sel_col, _bz_year_col, _ = st.columns([2, 1, 2])
            with _bz_sel_col:
                _bz_metric = st.radio(
                    "Kennzahl", ["Fallzahlen", "HZ (pro 100 000 Einwohner)"],
                    horizontal=True, key="bz_metric"
                )
            with _bz_year_col:
                _bz_years = sorted(bz_fall["year"].unique(), reverse=True)
                _bz_year = st.selectbox("Jahr", options=_bz_years, index=0, key="bz_year")

            _bz_use_hz = _bz_metric.startswith("HZ")
            if _bz_use_hz:
                _bz_data = bz_hz[bz_hz["year"] == _bz_year].sort_values("Bezirk", ascending=False)
                _bz_x = _bz_data["HZ"].round(0).astype(int)
                _bz_text = _bz_data["HZ"].apply(lambda v: _fmt_int(round(v)))
                _bz_title = "HZ (pro 100 000 Einwohner)"
            else:
                _bz_data = bz_fall[bz_fall["year"] == _bz_year].sort_values("Bezirk", ascending=False)
                _bz_x = _bz_data["Fallzahlen"]
                _bz_text = _bz_data["Fallzahlen"].apply(_fmt_int)
                _bz_title = "Fallzahlen"
            _bz_colours = [_BZ_COLOURS.get(b, "#888") for b in _bz_data["Bezirk"]]
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
            st.plotly_chart(fig_bz, use_container_width=True, config=_plot_config)

        st.divider()

        # --- All-Bezirke trend ---
        st.subheader("Alle Bezirke im Vergleich")
        _bez_metric = st.radio(
            "Kennzahl", ["Fallzahlen", "HZ (pro 100 000 Einwohner)"],
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
                line=dict(width=2.5 if _is_mitte else 1.5, color=_BZ_COLOURS.get(_bez, "#888")),
                marker=dict(size=5 if _is_mitte else 4),
            ))
        _fig_btr.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)", title=_btr_val),
            xaxis=dict(tickmode="linear", dtick=1, title="Jahr"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            margin=dict(t=60, b=20),
            height=460,
        )
        st.plotly_chart(_fig_btr, use_container_width=True, config=_plot_config)
        st.caption("Mitte (rot) enthält Moabit. HZ = Häufigkeitszahl (Straftaten pro 100 000 Einwohner).")

        st.subheader("Warum ist die Kriminalitätsrate in Moabit so hoch?")
        st.markdown("""
Moabits Kriminalitätsrate ist höher als der Berliner Durchschnitt — doch ein genauerer Blick relativiert das Bild erheblich.

**Mitte als touristisches Zentrum.** Moabit ist ein Ortsteil von Mitte — dem historischen Herz Berlins mit Alexanderplatz, Museumsinsel, Brandenburger Tor und Hackeschem Markt. Enormes Besucheraufkommen trifft hier auf eine vergleichsweise kleine gemeldete Wohnbevölkerung, was die HZ des gesamten Bezirks strukturell in die Höhe treibt — und Moabit als Ortsteil davon mit betrifft.

**Hauptbahnhof-Effekt.** Deutschlands verkehrsreichster Bahnhof liegt am östlichen Rand Moabits und zieht täglich Hunderttausende Reisende an. Opportunistische Delikte wie Taschendiebstahl konzentrieren sich rund um Verkehrsknotenpunkte — und erhöhen die Fallzahlen strukturell.

**Häufigkeitszahl und Bevölkerungsbasis.** Die HZ wird gegen die *gemeldete* Wohnbevölkerung berechnet, nicht gegen die tatsächliche Zahl der sich im Kiez aufhaltenden Personen. In Gebieten mit hohem Tagespublikum wie Moabit Ost ist die HZ daher systematisch überhöht.

**Sozialer Brennpunkt Kleiner Tiergarten.** Die offene Drogenszene rund um den Kleinen Tiergarten erzeugt Drogen- und Beschaffungskriminalität, die in den Statistiken sichtbar ist.

**Polizeipräsenz erhöht Erfassungsquote.** Gebiete mit starker Polizeipräsenz — etwa rund um Hbf und Kriminalgericht — weisen schlicht mehr *erfasste* Straftaten auf, nicht unbedingt mehr tatsächliche.
""")

        st.divider()

        # --- Mitte LOR chart ---
        st.subheader("Bezirk Mitte: Stadtteile im Vergleich")
        _lor_metric = st.radio(
            "Kennzahl", ["Fallzahlen", "HZ (pro 100 000 Einwohner)"],
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
                name=_geb,
                mode="lines+markers",
                line=dict(width=2.5 if _is_moabit else 1.5, color=_LOR_COLOURS.get(_geb, "#888")),
                marker=dict(size=5 if _is_moabit else 4),
            ))
        _fig_lor.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)", title=_lor_val),
            xaxis=dict(tickmode="linear", dtick=1, title="Jahr"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            margin=dict(t=60, b=20),
            height=460,
        )
        st.plotly_chart(_fig_lor, use_container_width=True, config=_plot_config)
        _lor_caption = "Moabit West (blau), Moabit Ost (rot), Moabit gesamt (orange). Alphabetische Reihenfolge."
        if _lor_use_hz:
            _lor_caption += " Kombinierte HZ für Moabit gesamt nicht verfügbar (bevölkerungsgewichtet)."
        st.caption(_lor_caption)

        st.divider()

        # --- Trend chart ---
        st.subheader("Entwicklung 2015–" + str(latest_year) + " (Moabit)")
        all_cats = sorted(CATEGORIES.keys())
        st.markdown(
            """<style>
            div[data-testid="stMultiSelect"] span[data-baseweb="tag"] {
                background-color: #546E7A !important;
            }
            </style>""",
            unsafe_allow_html=True
        )
        selected = st.multiselect(
            "Deliktsbereiche",
            options=all_cats,
            default=DEFAULT_CATEGORIES,
            key="crime_cats",
        )
        _swatch_html = '<div style="display:flex;flex-wrap:wrap;row-gap:4px;column-gap:12px;margin-top:4px;">'
        for _c in all_cats:
            _col = _CAT_COLOURS[_c]
            _swatch_html += (
                f'<span style="display:inline-flex;align-items:center;gap:5px;font-size:0.78rem;">'
                f'<span style="display:inline-block;width:10px;height:10px;border-radius:2px;'
                f'background:{_col};flex-shrink:0;"></span>{_c}</span>'
            )
        _swatch_html += '</div>'
        st.markdown(_swatch_html, unsafe_allow_html=True)

        if selected:
            fig_trend = go.Figure()
            for cat in sorted(selected):
                fig_trend.add_trace(go.Scatter(
                    x=crime_df.index.tolist(),
                    y=crime_df[cat].tolist(),
                    name=cat,
                    mode="lines+markers",
                    line=dict(color=_CAT_COLOURS.get(cat, "#888"), width=2),
                    marker=dict(size=5),
                ))
            fig_trend.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.1)", title="Fallzahlen"),
                xaxis=dict(tickmode="linear", dtick=1, title="Jahr"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                margin=dict(t=60, b=20),
                height=420,
            )
            st.plotly_chart(fig_trend, use_container_width=True, config=_plot_config)
            st.caption(
                "⚠️ 2016 zeigt einen auffälligen Ausreißer (+33 % gegenüber 2015), "
                "der wahrscheinlich auf eine Änderung der Gebietsabgrenzung oder der statistischen "
                "Erfassungsmethodik zurückzuführen ist. Die Daten für 2015 und 2016 sollten mit "
                "Vorsicht interpretiert werden."
            )

        st.divider()

        # --- Latest year breakdown ---
        st.subheader("Alle Deliktsbereiche")
        _crime_years = crime_df.index.tolist()[::-1]
        _col_sel, _ = st.columns([1, 3])
        with _col_sel:
            _bar_year = st.selectbox("Jahr", options=_crime_years, index=0, key="crime_bar_year")
        _by_area = get_crime_data_by_area()
        _cats_bar = [c for c in CATEGORIES if c != "Straftaten insgesamt"]
        _west = _by_area[_bar_year].get("Moabit West", {})
        _ost  = _by_area[_bar_year].get("Moabit Ost",  {})
        _sorted_cats = sorted(_cats_bar, reverse=True)
        _vals_west = [_west.get(c, 0) for c in _sorted_cats]
        _vals_ost  = [_ost.get(c, 0)  for c in _sorted_cats]
        _totals    = [w + o for w, o in zip(_vals_west, _vals_ost)]
        fig_bar = go.Figure()
        fig_bar.add_trace(go.Bar(
            x=_vals_west, y=_sorted_cats, orientation="h",
            name="Moabit West", marker_color="#1E88E5", marker_line_width=0,
        ))
        fig_bar.add_trace(go.Bar(
            x=_vals_ost, y=_sorted_cats, orientation="h",
            name="Moabit Ost", marker_color="#C0504D", marker_line_width=0,
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
        st.plotly_chart(fig_bar, use_container_width=True, config=_plot_config)
        st.caption("Gestapelte Balken: Moabit West (blau) + Moabit Ost (rot). Beschriftung = Gesamtwert.")

with tab_about:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Über Moabit")
        st.markdown("""
Moabit ist ein dichtbevölkerter Ortsteil im Bezirk Mitte, unmittelbar nördlich des Tiergartens gelegen. Der Ortsteil wird vollständig von vier Wasserstraßen umschlossen: Spree, Berlin-Spandauer Schifffahrtskanal, Westhafenkanal und Charlottenburger Verbindungskanal. Diese Insellage verleiht Moabit einen unverwechselbaren Charakter, über 26 Straßen-, Bahn- und Fußgängerbrücken mit der übrigen Stadt verbunden.
""")

        st.subheader("Bevölkerung & Charakter")
        st.markdown("""
Moabit ist eines der am dichtesten besiedelten und multikulturellsten Viertel Berlins. Rund **40 %** der Einwohner haben einen Migrationshintergrund: türkische, arabische und osteuropäische Gemeinschaften sind besonders präsent. Verglichen mit aufgewerteten Nachbarvierteln wie Mitte oder Prenzlauer Berg ist Moabit **authentischer und weniger gentrifiziert**; die Mieten sind bisher verhältnismäßig moderat geblieben, steigen aber.

*Daten zur Bevölkerungsstruktur sind im Tab „Bevölkerung" zu finden.*
""")


        st.subheader("Lage & Verkehr")
        st.markdown("""
Der **Berlin Hauptbahnhof** (der wichtigste Eisenbahnknotenpunkt Deutschlands) liegt am östlichen Rand Moabits und bietet hervorragende Anbindung an S-Bahn, U-Bahn, Tram und Fernzüge. Das Regierungsviertel grenzt unmittelbar an, ebenso wie Tiergarten und Charlottenburg.

- **U-Bahn:** U9 (Turmstraße, Birkenstraße)
- **S-Bahn / Fernbahn:** Berlin Hbf, Bellevue
- **Tram:** M10 (Verbindung nach Prenzlauer Berg)
- **Fahrrad:** Gut ausgebautes Radwegenetz entlang der Kanäle

Das **Bundesministerium des Innern** hat seinen Berliner Dienstsitz in Moabit.
""")


    with col2:
        st.subheader("Geschichte")
        st.markdown("""
Im 13. Jahrhundert hieß das Gebiet noch *Große Stadtheide*, später *Kämmereiheide*. Die eigentliche Besiedlung begann **1685**, als Hugenotten (französische Glaubensflüchtlinge) hier angesiedelt wurden. Sie nannten ihre neue Heimat *terre de Moab*, nach dem biblischen Land Moab, der ersten Zufluchtsstätte der Israeliten nach dem Auszug aus Ägypten. 1716 entstand die Kolonie Moabit; 1801 zählte man erst 120 Bewohner.

1818 entstand nördlich davon eine weitere Kolonie, die zur Unterscheidung den Namen **Neu-Moabit** erhielt. Mit der Industrialisierung folgte eine rasche Besiedlung beider Kolonien. **1861** wurden bei der Eingemeindung nach Berlin 6 534 Einwohner gezählt; bis 1910 war die Bevölkerung auf rund 190 000 angewachsen.

Im 19. Jahrhundert prägten Fabriken von AEG, Schwarzkopf und Löwe das klassische Arbeiterviertel. Von **1920 bis 2000** gehörte Moabit zum Bezirk Tiergarten; seit der Bezirksfusion am 1.  Januar 2001 ist es Ortsteil des neuen Bezirks Mitte.
""")

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
        )
        st.plotly_chart(_fig_pop, use_container_width=True, config=_plot_config)
        st.caption("Bevölkerungswachstum Moabits 1801–1910. Quellen: Volkszählungen, Berliner Morgenpost (2012).")

    st.subheader("Kieze im Überblick")
    st.markdown("""
Moabit hat keine festen amtlichen Kiezgrenzen; die Grenzen sind fließend. Historisch und städtebaulich werden jedoch sechs bis sieben Hauptkieze unterschieden:
""")

    _kc1, _kc2, _kc3 = st.columns(3)
    _ks = 'min-height:160px; padding-bottom:0.5rem'
    with _kc1:
        st.markdown(f"<div style='{_ks}'><strong style='font-size:1.1rem'>Alt-Moabit & Turmstraße</strong><br>Die zentralen Lebensadern Moabits. Rund um das Schultheiss Quartier und den Kleinen Tiergarten konzentrieren sich Handel, Gastronomie und öffentliches Leben.</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='{_ks}'><strong style='font-size:1.1rem'>Huttenkiez</strong><br>Mischung aus Wohnen und Industrie entlang der Huttenstraße (auch als ‘Hutteninsel’ bekannt). Rauher Charme, aber zunehmend im Wandel.</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='{_ks}'><strong style='font-size:1.1rem'>Westfälisches Viertel</strong><br>Ruhiges, bürgerlich geprägtes Gründerzeitviertel im Südwesten. Breite Straßen, gepflegte Altbauten und eine entspannte Wohnatmosphäre.</div>", unsafe_allow_html=True)
    with _kc2:
        st.markdown(f"<div style='{_ks}'><strong style='font-size:1.1rem'>Beusselkiez</strong><br>Traditionelles Arbeiter- und Wohnviertel im Nordwesten, geprägt von gründerzeitlicher Blockbebauung und einer starken Nachbarschaftsidentität.</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='{_ks}'><strong style='font-size:1.1rem'>Lehrter-Straßen-Kiez</strong><br>Östliches Quartier zwischen Hauptbahnhof und Invalidenstraße, das sich in den vergangenen Jahren stark entwickelt hat.</div>", unsafe_allow_html=True)
    with _kc3:
        st.markdown(f"<div style='{_ks}'><strong style='font-size:1.1rem'>Europacity</strong><br>Moderne Erweiterung im östlichen Moabit, direkt am Hauptbahnhof. Bürobauten, Neubauwohnungen und Gewerbeflächen prägen dieses noch im Entstehen begriffene Stadtquartier.</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='{_ks}'><strong style='font-size:1.1rem'>Stephankiez</strong><br>Einer der bekanntesten und besterhaltenen Gründerzeitkieze Berlins, rund um den Stephanplatz. Stuckfassaden, ruhige Straßen und eine entspannte, fast dörfliche Atmosphäre.</div>", unsafe_allow_html=True)

    st.markdown("""
Darüber hinaus ist Moabit durch das Quartiersmanagement Berlin in zwei offizielle Fördergebiete eingeteilt: **Moabit-Ost** und **Beusselstraße/Moabit-West**. Diese Gebiete erhalten gezielte Förderung für soziale Infrastruktur, Nachbarschaftsprojekte und städtebauliche Entwicklung.
""")

    st.subheader("Orte, Essen & Kultur")
    st.markdown("""
- **Justizvollzugsanstalt Moabit** und das **Kriminalgericht Moabit**: das größte Kriminalgericht Europas
- **Arminiusmarkthalle** (1891): historische Markthalle mit regionalem und internationalem Angebot; dazu Wochenmarkt Turmstraße (Di & Fr)
- **Kleiner Tiergarten**: zentraler Stadtpark und soziales Zentrum rund um Alt-Moabit und Turmstraße, auch bekannt als sozialer Brennpunkt
- **Fritz-Schloß-Park**: die größte Grünfläche Moabits, entstanden auf einem ehemaligen Exerzierplatz
- **Spreebogenpark**: mit direktem Blick auf den Reichstag; Kanalpromenaden entlang aller vier Wasserstraßen
- **Restaurants:** von türkischen Imbissen bis zur gehobenen Gastronomie
- **Kultur:** Kunsthaus Moabit, freie Theater und Galerien
- **Sport:** Schwimmbad Turmstraße, Sporthallen und Bolzplätze
""")

    st.divider()
    st.subheader("Quellen")
    st.markdown("""
- Bezirksamt Mitte: [Ortsteil Moabit](https://www.berlin.de/ba-mitte/ueber-den-bezirk/ortsteile/moabit/)
- Amt für Statistik Berlin-Brandenburg: Volkszählungen und Einwohnerregister
- Wikipedia: [Moabit](https://de.wikipedia.org/wiki/Moabit)
- OpenStreetMap: Geodaten Moabit
- Quartiersmanagement Berlin: [Moabit-Ost](https://www.qm-moabit-ost.de/) und [Beusselstraße/Moabit-West](https://www.stattbau.de/projekte/qm-beusselstrasse/)
- [Moabit Online](https://moabitonline.de/moabit) — lokales Nachrichtenportal
- [Moazin](https://www.moazin.de/) — Magazin für und über Moabit
- [Gebietsinformation Turmstraße](https://www.turmstrasse.de/gebiete/gebietsinformation) — Quartiersmanagement Turmstraße
- Berliner Morgenpost, 2. November 2012: „Kiez im Wandel und Aufbruch“ (Anzeigensonderveröffentlichung)
""")
