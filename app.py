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
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

import plotly.graph_objects as go
from layers.transport import fetch_stops, stop_style
from layers.cycling import fetch_cycle_lanes, lane_style, LEGEND as CYCLE_LEGEND
from layers.rent import fetch_wohnlagen, WOL_STYLE
from layers.greenspace import fetch_greenspaces, FEATURE_STYLE, LEGEND as GREEN_LEGEND
from layers.amenities import fetch_amenities, AMENITY_STYLE, LEGEND as AMENITY_LEGEND
from layers.routes import fetch_routes, fetch_routes_full, LEGEND as ROUTE_LEGEND
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


st.title("Moabiter Dashboard")

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
    show_routes_full = st.sidebar.checkbox("Vollständige Linien (außerhalb Moabits)", value=False)
    legend_html = "".join(
        f'<span style="color:{colour}">&#9644;</span> {label}<br>'
        for label, colour in ROUTE_LEGEND.items()
    )
    st.sidebar.markdown(f"<small>{legend_html}</small>", unsafe_allow_html=True)
show_transport = st.sidebar.checkbox("Haltestellen", value=True)
show_cycling = st.sidebar.checkbox("Radwege", value=False)
if show_cycling:
    legend_html = "".join(
        f'<span style="color:{colour}">&#9644;</span> {label}<br>'
        for label, colour in CYCLE_LEGEND.items()
    )
    st.sidebar.markdown(f"<small>{legend_html}</small>", unsafe_allow_html=True)
show_wohnlagen = st.sidebar.checkbox("Wohnlagenkarte", value=False)
if show_wohnlagen:
    legend_html = "".join(
        f'<span style="color:{v["colour"]}">&#9632;</span> {v["label"]}<br>'
        for v in [WOL_STYLE["gut"], WOL_STYLE["mittel"], WOL_STYLE["einfach"]]
    )
    st.sidebar.markdown(f"<small>{legend_html}</small>", unsafe_allow_html=True)
show_greenspaces = st.sidebar.checkbox("Grünflächen", value=False)
if show_greenspaces:
    legend_html = "".join(
        f'<span style="color:{colour}">&#9632;</span> {label}<br>'
        for label, colour in GREEN_LEGEND.items()
    )
    st.sidebar.markdown(f"<small>{legend_html}</small>", unsafe_allow_html=True)
show_amenities = st.sidebar.checkbox("Einrichtungen", value=False)
if show_amenities:
    legend_html = "".join(
        f'<span style="color:{colour}">&#9632;</span> {label}<br>'
        for label, colour in AMENITY_LEGEND.items()
    )
    st.sidebar.markdown(f"<small>{legend_html}</small>", unsafe_allow_html=True)

# --- Tabs ---
tab_map, tab_departures, tab_arrivals, tab_demographics = st.tabs(["Karte", "Abfahrten Berlin Hbf", "Ankünfte Berlin Hbf", "Bevölkerung"])

# --- Map tab ---
with tab_map:
    if show_transport:
        with st.spinner("Lade ÖPNV-Daten..."):
            stops = get_stops()

    if show_cycling:
        with st.spinner("Lade Radwege..."):
            lanes = get_lanes()

    if show_wohnlagen:
        with st.spinner("Lade Wohnlagenkarte..."):
            wohnlagen = get_wohnlagen()

    if show_greenspaces:
        with st.spinner("Lade Grünflächen..."):
            greenspaces = get_greenspaces()

    if show_amenities:
        with st.spinner("Lade Einrichtungen..."):
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
                popup=folium.Popup(name, max_width=200),
                tooltip=name,
                icon=folium.Icon(color=style["color"], icon=style["icon"], prefix="fa"),
            ).add_to(cluster)

    if "selected_stop" not in st.session_state:
        st.session_state.selected_stop = None

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

    # Update selected stop only when a transport stop marker is clicked
    if show_transport and map_data.get("last_object_clicked"):
        click = map_data["last_object_clicked"]
        clat, clng = click.get("lat"), click.get("lng")
        if clat and clng:
            matched = min(stops, key=lambda s: (s["lat"] - clat) ** 2 + (s["lon"] - clng) ** 2)
            dist = ((matched["lat"] - clat) ** 2 + (matched["lon"] - clng) ** 2) ** 0.5
            if dist < 0.002:
                st.session_state.selected_stop = matched

    # Departure table — persists via session_state across reruns
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
    col1, col2, col3, col4 = st.columns(4)
    if not trend.empty:
        latest = trend.iloc[-1]
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

    years = IBB_DATA["year"]
    bezirke = [k for k in IBB_DATA if k != "year"]

    # Colour map — highlight Mitte and Berlin, grey others
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
            x=years,
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
