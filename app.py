from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from functools import lru_cache
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen
import json
import math
import numbers

from dataframe import read_file
from dwd_data import filled_regional_series, station_coverage


HOST = "127.0.0.1"
PORT = 8000
STATION_NAME = "Dresden-Klotzsche"
LATITUDE = 51.1277
LONGITUDE = 13.7543
LIVE_STATIONS = [
    {"name": "Dresden-Klotzsche", "latitude": 51.1277, "longitude": 13.7543},
    {"name": "Dresden-Hosterwitz", "latitude": 51.0149, "longitude": 13.8522},
    {"name": "Dresden-Strehlen", "latitude": 51.0221, "longitude": 13.7593},
]


def _finite(value):
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        return float(value)
    return value


def _record(row):
    return {key: _finite(value) for key, value in row.items()}


@lru_cache(maxsize=2)
def weather_data(source="local"):
    if source == "dwd_filled":
        return filled_regional_series()
    return read_file()


def _avg(values):
    clean = [value for value in values if value is not None]
    return _finite(sum(clean) / len(clean)) if clean else None


def _circular_avg_degrees(values):
    clean = [math.radians(value) for value in values if value is not None]
    if not clean:
        return None
    sin_sum = sum(math.sin(value) for value in clean)
    cos_sum = sum(math.cos(value) for value in clean)
    if sin_sum == 0 and cos_sum == 0:
        return None
    return _finite((math.degrees(math.atan2(sin_sum, cos_sum)) + 360) % 360)


def current_weather():
    latitudes = ",".join(str(station["latitude"]) for station in LIVE_STATIONS)
    longitudes = ",".join(str(station["longitude"]) for station in LIVE_STATIONS)
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={latitudes}&longitude={longitudes}"
        "&current=temperature_2m,relative_humidity_2m,precipitation,"
        "weather_code,pressure_msl,wind_speed_10m,wind_direction_10m"
        "&timezone=Europe%2FBerlin"
    )

    try:
        with urlopen(url, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        payloads = payload if isinstance(payload, list) else [payload]
        station_rows = [
            (LIVE_STATIONS[index]["name"], item.get("current", {}))
            for index, item in enumerate(payloads)
            if isinstance(item, dict) and item.get("current")
        ]
        if not station_rows:
            raise ValueError("Keine Live-Werte erhalten.")
        current_rows = [row for _, row in station_rows]
        time = next((row.get("time") for row in current_rows if row.get("time")), None)
        return {
            "source": "Open-Meteo Live-Durchschnitt",
            "station": "Dresden Live-Durchschnitt",
            "time": time,
            "station_count": len(current_rows),
            "stations": [name for name, _ in station_rows],
            "temperature_c": _avg([_finite(row.get("temperature_2m")) for row in current_rows]),
            "humidity_pct": _avg([_finite(row.get("relative_humidity_2m")) for row in current_rows]),
            "precipitation_mm": _avg([_finite(row.get("precipitation")) for row in current_rows]),
            "pressure_hpa": _avg([_finite(row.get("pressure_msl")) for row in current_rows]),
            "wind_kmh": _avg([_finite(row.get("wind_speed_10m")) for row in current_rows]),
            "wind_direction_deg": _circular_avg_degrees([_finite(row.get("wind_direction_10m")) for row in current_rows]),
            "weather_code": _finite(current_rows[0].get("weather_code")) if current_rows else None,
            "is_live": True,
        }
    except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        latest = weather_data("local").dropna(subset=["temp_avg_c"]).iloc[-1]
        return {
            "source": "CSV, letzter verfügbarer Tageswert",
            "station": STATION_NAME,
            "time": latest["date"].strftime("%Y-%m-%d"),
            "station_count": 1,
            "stations": [STATION_NAME],
            "temperature_c": _finite(float(latest["temp_avg_c"])),
            "humidity_pct": _finite(float(latest["humidity_pct"])),
            "precipitation_mm": _finite(float(latest["rain_mm"])),
            "pressure_hpa": _finite(float(latest["pressure_hpa"])),
            "wind_kmh": None,
            "wind_direction_deg": None,
            "weather_code": None,
            "is_live": False,
        }


def summary(start_year, end_year, source):
    df = weather_data(source)
    period = df[(df["year"] >= start_year) & (df["year"] <= end_year)]
    latest = df.iloc[-1]
    temp_days = int(period["temp_avg_c"].count())
    rain_days = int(period["rain_mm"].count())
    return {
        "station": "DWD regional gefüllt" if source == "dwd_filled" else STATION_NAME,
        "source": source,
        "first_year": int(df["year"].min()),
        "last_year": int(df["year"].max()),
        "latest_date": latest["date"].strftime("%Y-%m-%d"),
        "days": int(len(period)),
        "temp_days": temp_days,
        "rain_days": rain_days,
        "temp_coverage_pct": _finite((temp_days / len(period)) * 100 if len(period) else None),
        "rain_coverage_pct": _finite((rain_days / len(period)) * 100 if len(period) else None),
        "temp_avg_c": _finite(float(period["temp_avg_c"].mean())),
        "temp_max_c": _finite(float(period["temp_max_c"].max())),
        "temp_min_c": _finite(float(period["temp_min_c"].min())),
        "rain_sum_mm": _finite(float(period["rain_mm"].sum())),
        "wet_days": int((period["rain_mm"] > 0).sum()),
        "sunshine_sum_h": _finite(float(period["sunshine_h"].sum())),
        "pressure_avg_hpa": _finite(float(period["pressure_hpa"].mean())),
        "humidity_avg_pct": _finite(float(period["humidity_pct"].mean())),
    }


def annual_heavy_rain(df):
    rain = df[["date", "year", "rain_mm"]].copy().sort_values("date")
    rain["rain_3day_mm"] = rain.groupby("year")["rain_mm"].transform(lambda series: series.rolling(3, min_periods=1).sum())
    rain["rain_7day_mm"] = rain.groupby("year")["rain_mm"].transform(lambda series: series.rolling(7, min_periods=1).sum())
    return rain.groupby("year").agg(
        rain_max_day_mm=("rain_mm", "max"),
        rain_max_3day_mm=("rain_3day_mm", "max"),
        rain_max_7day_mm=("rain_7day_mm", "max"),
    )


def history(start_year, end_year, grain, source):
    df = weather_data(source)
    period = df[(df["year"] >= start_year) & (df["year"] <= end_year)].copy()
    if "station_name" not in period.columns:
        period["station_name"] = STATION_NAME

    if grain == "day":
        period["label"] = period["date"].dt.strftime("%Y-%m-%d")
        grouped = period.set_index("label")
    elif grain == "month":
        period["label"] = period["date"].dt.strftime("%Y-%m")
        grouped = period.groupby("label")
    else:
        period["label"] = period["year"].astype(str)
        grouped = period.groupby("label")

    if grain == "day":
        rows = period[
            [
                "label",
                "temp_avg_c",
                "temp_max_c",
                "temp_min_c",
                "rain_mm",
                "sunshine_h",
                "pressure_hpa",
                "humidity_pct",
                "station_name",
            ]
        ].rename(columns={"rain_mm": "rain_sum_mm", "sunshine_h": "sunshine_sum_h"})
    else:
        rows = grouped.agg(
            temp_avg_c=("temp_avg_c", "mean"),
            temp_max_c=("temp_max_c", "max"),
            temp_min_c=("temp_min_c", "min"),
            rain_sum_mm=("rain_mm", "sum"),
            rain_max_day_mm=("rain_mm", "max"),
            sunshine_sum_h=("sunshine_h", "sum"),
            pressure_hpa=("pressure_hpa", "mean"),
            humidity_pct=("humidity_pct", "mean"),
            temp_days=("temp_avg_c", "count"),
            rain_days=("rain_mm", "count"),
        ).reset_index()
        if grain == "year":
            rows["year"] = rows["label"].astype(int)
            rows = rows.merge(annual_heavy_rain(period).reset_index(), on="year", how="left", suffixes=("", "_heavy"))
            rows["rain_max_day_mm"] = rows["rain_max_day_mm_heavy"].fillna(rows["rain_max_day_mm"])
            rows = rows.drop(columns=["year", "rain_max_day_mm_heavy"])

    return [_record(row) for row in rows.to_dict("records")]


def climate(start_year, end_year, source):
    df = weather_data(source).copy()
    period = df[(df["year"] >= start_year) & (df["year"] <= end_year)].copy()

    annual = df.groupby("year").agg(
        temp_avg_c=("temp_avg_c", "mean"),
        temp_max_c=("temp_max_c", "max"),
        temp_min_c=("temp_min_c", "min"),
        rain_sum_mm=("rain_mm", "sum"),
        rain_days=("rain_mm", lambda series: (series > 0).sum()),
        temp_days=("temp_avg_c", "count"),
    )
    annual = annual.join(annual_heavy_rain(df))
    annual["temp_trend_10y_c"] = annual["temp_avg_c"].rolling(10, min_periods=5).mean()

    selected = annual[(annual.index >= start_year) & (annual.index <= end_year)].copy()
    ref_temp = float(period["temp_avg_c"].mean())
    ref_rain = float(selected["rain_sum_mm"].mean())
    selected["label"] = selected.index.astype(str)
    selected["temp_anomaly_c"] = selected["temp_avg_c"] - ref_temp
    selected["rain_anomaly_mm"] = selected["rain_sum_mm"] - ref_rain
    selected["rain_pct_of_normal"] = (selected["rain_sum_mm"] / ref_rain) * 100

    hottest_day = period.loc[period["temp_max_c"].idxmax()]
    coldest_day = period.loc[period["temp_min_c"].idxmin()]
    wettest_day = period.loc[period["rain_mm"].idxmax()]
    wettest_year = selected.loc[selected["rain_sum_mm"].idxmax()]
    driest_year = selected.loc[selected["rain_sum_mm"].idxmin()]
    hottest_year = selected.loc[selected["temp_avg_c"].idxmax()]
    coldest_year = selected.loc[selected["temp_avg_c"].idxmin()]
    heavy_year = selected.loc[selected["rain_max_day_mm"].idxmax()]

    top_events = (
        period[["date", "rain_mm", "station_name"] if "station_name" in period.columns else ["date", "rain_mm"]]
        .nlargest(10, "rain_mm")
        .copy()
    )
    if "station_name" not in top_events.columns:
        top_events["station_name"] = STATION_NAME
    top_events["date"] = top_events["date"].dt.strftime("%Y-%m-%d")

    return {
        "reference": {
            "start": start_year,
            "end": end_year,
            "temp_avg_c": _finite(ref_temp),
            "rain_year_mm": _finite(ref_rain),
        },
        "annual": [_record(row) for row in selected.reset_index(drop=True).to_dict("records")],
        "extremes": {
            "hottest_year": {"year": int(hottest_year.name), "value": _finite(hottest_year["temp_avg_c"])},
            "coldest_year": {"year": int(coldest_year.name), "value": _finite(coldest_year["temp_avg_c"])},
            "wettest_year": {"year": int(wettest_year.name), "value": _finite(wettest_year["rain_sum_mm"])},
            "driest_year": {"year": int(driest_year.name), "value": _finite(driest_year["rain_sum_mm"])},
            "heavy_rain_year": {"year": int(heavy_year.name), "value": _finite(heavy_year["rain_max_day_mm"])},
            "hottest_day": {
                "date": hottest_day["date"].strftime("%Y-%m-%d"),
                "value": _finite(hottest_day["temp_max_c"]),
            },
            "coldest_day": {
                "date": coldest_day["date"].strftime("%Y-%m-%d"),
                "value": _finite(coldest_day["temp_min_c"]),
            },
            "wettest_day": {
                "date": wettest_day["date"].strftime("%Y-%m-%d"),
                "value": _finite(wettest_day["rain_mm"]),
            },
        },
        "top_rain_events": [_record(row) for row in top_events.to_dict("records")],
    }


def stations():
    coverage = station_coverage()
    coverage["first_date"] = coverage["first_date"].dt.strftime("%Y-%m-%d")
    coverage["last_date"] = coverage["last_date"].dt.strftime("%Y-%m-%d")
    return [_record(row) for row in coverage.to_dict("records")]


INDEX_HTML = r"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Wetterdashboard Dresden</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #667085;
      --line: #d7dde5;
      --blue: #2563eb;
      --red: #e11d48;
      --green: #0f766e;
      --amber: #b45309;
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }
    header {
      padding: 22px 28px 16px;
      border-bottom: 1px solid var(--line);
      background: #fff;
    }
    h1 { margin: 0; font-size: 28px; line-height: 1.15; letter-spacing: 0; }
    .subtitle { margin-top: 6px; color: var(--muted); }
    main { padding: 20px 28px 32px; max-width: 1440px; margin: 0 auto; }
    .layout { display: block; }
    .controls, .panel, .metric, .chart-panel, table {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .controls {
      display: grid;
      grid-template-columns: minmax(280px, 1.5fr) minmax(160px, 1fr);
      gap: 14px;
      align-items: end;
      padding: 14px;
    }
    .control-note {
      grid-column: 1 / -1;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 14px;
      align-items: center;
    }
    label { display: block; margin: 14px 0 6px; font-size: 13px; font-weight: 650; color: #344054; }
    input, select, button {
      width: 100%;
      min-height: 40px;
      border-radius: 6px;
      border: 1px solid #c9d1dc;
      padding: 8px 10px;
      font: inherit;
      background: #fff;
    }
    button {
      margin-top: 16px;
      cursor: pointer;
      color: #fff;
      background: var(--blue);
      border-color: var(--blue);
      font-weight: 700;
    }
    .status {
      margin-top: 12px;
      min-height: 20px;
      color: var(--muted);
      font-size: 13px;
    }
    .range-readout {
      display: flex;
      justify-content: flex-end;
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
    }
    .year-inputs {
      display: grid;
      grid-template-columns: 1fr auto 1fr;
      gap: 8px;
      align-items: center;
      margin-top: 8px;
    }
    .year-inputs input {
      min-height: 36px;
    }
    .year-separator { color: var(--muted); font-weight: 750; }
    .range-slider {
      position: relative;
      height: 38px;
      margin-top: 4px;
    }
    .range-track,
    .range-fill {
      position: absolute;
      left: 0;
      right: 0;
      top: 16px;
      height: 8px;
      border-radius: 999px;
    }
    .range-track { background: #d7dde5; }
    .range-fill {
      left: var(--start-pos, 0%);
      right: calc(100% - var(--end-pos, 100%));
      background: linear-gradient(90deg, #2563eb, #0f766e);
    }
    input[type="range"] {
      position: absolute;
      inset: 0;
      width: 100%;
      padding: 0;
      margin: 0;
      min-height: 38px;
      pointer-events: none;
      appearance: none;
      background: transparent;
      border: 0;
    }
    input[type="range"]::-webkit-slider-thumb {
      width: 18px;
      height: 18px;
      border: 2px solid #ffffff;
      border-radius: 999px;
      background: var(--blue);
      box-shadow: 0 1px 4px rgba(16, 24, 40, 0.28);
      cursor: pointer;
      pointer-events: auto;
      appearance: none;
    }
    input[type="range"]::-moz-range-thumb {
      width: 18px;
      height: 18px;
      border: 2px solid #ffffff;
      border-radius: 999px;
      background: var(--blue);
      box-shadow: 0 1px 4px rgba(16, 24, 40, 0.28);
      cursor: pointer;
      pointer-events: auto;
    }
    input[type="range"]::-webkit-slider-runnable-track { background: transparent; border: 0; }
    input[type="range"]::-moz-range-track { background: transparent; border: 0; }
    .hint {
      margin-top: 10px;
      padding: 10px;
      border-radius: 6px;
      color: #344054;
      background: #f2f6fc;
      font-size: 13px;
      line-height: 1.35;
    }
    .metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
    .insights { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }
    .metric { padding: 14px; min-height: 92px; }
    .metric span { display: block; color: var(--muted); font-size: 13px; }
    .metric strong { display: block; margin-top: 8px; font-size: 26px; line-height: 1.05; }
    .metric small { display: block; margin-top: 5px; color: var(--muted); }
    .metric.live {
      position: relative;
      border-color: #16a34a;
      outline: 2px solid rgba(22, 163, 74, 0.78);
      outline-offset: -2px;
      box-shadow: 0 0 0 0 rgba(22, 163, 74, 0.34);
      animation: livePulse 1.8s ease-in-out infinite;
    }
    @keyframes livePulse {
      0%, 100% {
        border-color: #16a34a;
        outline-color: rgba(22, 163, 74, 0.78);
        box-shadow: 0 0 0 0 rgba(22, 163, 74, 0.34);
      }
      50% {
        border-color: #22c55e;
        outline-color: rgba(34, 197, 94, 1);
        box-shadow: 0 0 0 7px rgba(22, 163, 74, 0.16);
      }
    }
    @media (prefers-reduced-motion: reduce) {
      .metric.live {
        animation: none;
        box-shadow: 0 0 0 4px rgba(22, 163, 74, 0.14);
      }
    }
    .metric-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }
    .live-badge {
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      padding: 3px 8px;
      border-radius: 999px;
      color: #ffffff;
      background: #16a34a;
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0;
    }
    .content { display: grid; gap: 14px; }
    .current {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 12px;
      align-items: stretch;
      padding: 2px;
    }
    .current .metric {
      min-height: 118px;
    }
    .current .metric span {
      font-size: 14px;
      font-weight: 650;
    }
    .current .metric strong {
      margin-top: 10px;
      font-size: clamp(28px, 3vw, 36px);
      line-height: 0.98;
      letter-spacing: 0;
    }
    .current .metric small {
      margin-top: 8px;
      font-size: 14px;
      line-height: 1.25;
    }
    .live-value {
      display: flex;
      align-items: baseline;
      gap: 5px;
      flex-wrap: wrap;
    }
    .live-unit {
      color: #344054;
      font-size: 0.62em;
      font-weight: 850;
      white-space: nowrap;
    }
    .tabs {
      display: flex;
      gap: 8px;
      border-bottom: 1px solid var(--line);
    }
    .tab-button {
      width: auto;
      min-height: 38px;
      margin: 0 0 -1px;
      padding: 8px 14px;
      border-radius: 6px 6px 0 0;
      border-color: transparent;
      border-bottom-color: var(--line);
      background: transparent;
      color: var(--muted);
      font-weight: 750;
    }
    .tab-button.active {
      border-color: var(--line);
      border-bottom-color: var(--panel);
      background: var(--panel);
      color: var(--ink);
    }
    .tab-panel {
      display: none;
    }
    .tab-panel.active {
      display: grid;
      gap: 14px;
    }
    .chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    .chart-panel { padding: 14px; min-height: 330px; }
    .chart-panel { position: relative; }
    .chart-panel h2, .panel h2 { margin: 0 0 10px; font-size: 17px; }
    .panel-note { margin: -4px 0 10px; color: var(--muted); font-size: 13px; }
    canvas { width: 100%; height: 270px; display: block; }
    .chart-tooltip {
      position: fixed;
      z-index: 20;
      max-width: 260px;
      padding: 8px 10px;
      border: 1px solid #c9d1dc;
      border-radius: 6px;
      background: #ffffff;
      box-shadow: 0 8px 24px rgba(16, 24, 40, 0.16);
      color: #17202a;
      font-size: 12px;
      line-height: 1.35;
      pointer-events: none;
      opacity: 0;
      transform: translate(10px, 10px);
      transition: opacity 120ms ease;
    }
    .chart-tooltip strong { display: block; margin-bottom: 4px; font-size: 13px; }
    .panel { padding: 14px; overflow: auto; }
    table { width: 100%; border-collapse: collapse; overflow: hidden; }
    th, td { padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: right; white-space: nowrap; }
    th:first-child, td:first-child { text-align: left; }
    th { color: #344054; font-size: 13px; background: #f9fafb; }
    td { font-size: 14px; }
    td a {
      color: var(--blue);
      font-weight: 700;
      text-decoration: none;
    }
    td a:hover { text-decoration: underline; }

    @media (max-width: 980px) {
      main, header { padding-left: 16px; padding-right: 16px; }
      .layout, .chart-grid { grid-template-columns: 1fr; }
      .controls { grid-template-columns: 1fr; }
      .control-note { grid-template-columns: 1fr; }
      .current {
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
      }
      .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .insights { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 560px) {
      .current {
        gap: 8px;
      }
      .current .metric { padding: 13px; min-height: 110px; }
      .current .metric span { font-size: 13px; }
      .current .metric strong { font-size: 25px; }
      .current .metric small { font-size: 13px; }
      .metrics, .insights { grid-template-columns: 1fr; }
      h1 { font-size: 23px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Wetterdashboard Dresden</h1>
    <div class="subtitle">Live-Durchschnitt Dresdener Wetterstationen und regional gefüllte DWD-Stationsdaten</div>
  </header>
  <main>
    <div class="layout">
      <section class="content">
        <div class="current" id="current"></div>
        <div class="tabs" role="tablist" aria-label="Dashboardbereiche">
          <button class="tab-button active" type="button" data-tab="analysis" role="tab" aria-selected="true">Analyse</button>
          <button class="tab-button" type="button" data-tab="data" role="tab" aria-selected="false">Data</button>
        </div>
        <section class="tab-panel active" id="analysisTab" data-tab-panel="analysis" role="tabpanel">
          <section class="controls">
            <div>
              <label for="startYear">Zeitraum</label>
              <div class="range-slider" id="yearSlider">
                <div class="range-track"></div>
                <div class="range-fill"></div>
                <input id="startYear" type="range" min="1934" max="2025" value="1991" aria-label="Startjahr">
                <input id="endYear" type="range" min="1934" max="2025" value="2025" aria-label="Endjahr">
              </div>
              <div class="year-inputs">
                <input id="startYearText" type="number" min="1934" max="2025" value="1991" aria-label="Startjahr als Zahl">
                <span class="year-separator">bis</span>
                <input id="endYearText" type="number" min="1934" max="2025" value="2025" aria-label="Endjahr als Zahl">
              </div>
              <div class="range-readout">
                <span id="yearCountText">35 Jahre</span>
              </div>
            </div>
            <div>
              <label for="grain">Auswertung</label>
              <select id="grain">
                <option value="year">Jährlich</option>
                <option value="month">Monatlich</option>
                <option value="day">Täglich</option>
              </select>
            </div>
            <div class="control-note">
              <div class="hint">Referenz für Klimaabweichungen: der aktuell gewählte Zeitraum. Starkregen wird getrennt vom Jahresniederschlag betrachtet.</div>
              <div id="status" class="status">Bereit.</div>
            </div>
          </section>
          <div class="chart-grid">
            <section class="chart-panel">
              <h2>Temperaturabweichung</h2>
              <div class="panel-note" id="tempNormalNote"></div>
              <canvas id="tempAnomalyChart"></canvas>
            </section>
            <section class="chart-panel">
              <h2>Niederschlagsabweichung</h2>
              <div class="panel-note" id="rainNormalNote"></div>
              <canvas id="rainAnomalyChart"></canvas>
            </section>
          </div>
          <section class="chart-panel">
            <h2>Starkregen und Hochwasser-Signal</h2>
            <div class="panel-note">Jahressumme und maximale 1-/3-/7-Tage-Regenmengen werden getrennt gezeigt.</div>
            <canvas id="heavyRainChart"></canvas>
          </section>
          <div class="chart-grid">
            <section class="chart-panel">
              <h2>Temperatur</h2>
              <canvas id="tempChart"></canvas>
            </section>
            <section class="chart-panel">
              <h2>Niederschlag</h2>
              <canvas id="rainChart"></canvas>
            </section>
          </div>
          <section class="chart-panel">
            <h2>Sonne, Luftdruck und Feuchte</h2>
            <canvas id="climateChart"></canvas>
          </section>
        </section>
        <section class="tab-panel" id="dataTab" data-tab-panel="data" role="tabpanel">
          <div class="metrics" id="summary"></div>
          <div class="insights" id="extremes"></div>
          <section class="panel">
            <h2>DWD-Stationen in der Datenbasis</h2>
            <div class="panel-note">Stationsname öffnet das DWD-Open-Data-Verzeichnis, DWD-Datei die konkrete Originaldatei.</div>
            <table>
              <thead>
                <tr>
                  <th>Station</th>
                  <th>Zeitraum</th>
                  <th>Temp.-Tage</th>
                  <th>Regen-Tage</th>
                  <th>Quelle</th>
                </tr>
              </thead>
              <tbody id="stations"></tbody>
            </table>
          </section>
        </section>
      </section>
    </div>
  </main>
  <div id="chartTooltip" class="chart-tooltip"></div>
  <script>
    const fmt = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1 });
    const statusEl = document.getElementById("status");
    const tooltipEl = document.getElementById("chartTooltip");
    const chartState = new Map();
    let reloadTimer = null;

    function value(v, unit = "") {
      return v === null || v === undefined || Number.isNaN(v) ? "n/a" : `${fmt.format(v)}${unit}`;
    }

    function setStatus(text) {
      statusEl.textContent = text;
    }

    async function getJson(url) {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    }

    function metric(label, main, sub = "", badge = "", className = "") {
      return `<div class="metric ${className}"><div class="metric-head"><span>${label}</span>${badge}</div><strong>${main}</strong><small>${sub}</small></div>`;
    }

    function liveValue(v, unit = "") {
      if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
      return `<span>${fmt.format(v)}</span><span class="live-unit">${unit}</span>`;
    }

    function liveMetric(label, main, unit, sub = "", badge = "", className = "") {
      return `<div class="metric ${className}"><div class="metric-head"><span>${label}</span>${badge}</div><strong class="live-value">${liveValue(main, unit)}</strong><small>${sub}</small></div>`;
    }

    function renderCurrent(data) {
      const liveClass = data.is_live ? "live" : "";
      document.getElementById("current").innerHTML = [
        liveMetric("Temperatur", data.temperature_c, "°C", "aktueller Durchschnitt", data.is_live ? `<span class="live-badge">LIVE</span>` : "", liveClass),
        liveMetric("Niederschlag", data.precipitation_mm, "mm", "jetzt", "", liveClass),
        liveMetric("Luftdruck", data.pressure_hpa, "hPa", "MSL", "", liveClass),
        liveMetric("Feuchte", data.humidity_pct, "%", "relativ", "", liveClass),
        liveMetric("Wind", data.wind_kmh, "km/h", data.wind_direction_deg === null ? "" : `${fmt.format(data.wind_direction_deg)}°`, "", liveClass),
      ].join("");
    }

    function renderSummary(data) {
      document.getElementById("summary").innerHTML = [
        metric("Datenbasis", data.station, `${data.first_year}-${data.last_year}, Daten bis ${data.latest_date}`),
        metric("Temperaturmittel", value(data.temp_avg_c, " °C"), `${fmt.format(data.temp_coverage_pct)} % Abdeckung`),
        metric("Niederschlag gesamt", value(data.rain_sum_mm, " mm"), `${fmt.format(data.wet_days)} Tage mit Regen`),
        metric("Datenpunkte", fmt.format(data.days), `Regen ${fmt.format(data.rain_coverage_pct)} % abgedeckt`),
      ].join("");
    }

    function renderExtremes(data) {
      const e = data.extremes;
      document.getElementById("extremes").innerHTML = [
        metric("Wärmstes Jahr", e.hottest_year.year, value(e.hottest_year.value, " °C")),
        metric("Kältestes Jahr", e.coldest_year.year, value(e.coldest_year.value, " °C")),
        metric("Nassestes Jahr", e.wettest_year.year, value(e.wettest_year.value, " mm")),
        metric("Trockenstes Jahr", e.driest_year.year, value(e.driest_year.value, " mm")),
        metric("Stärkster Regentag", e.wettest_day.date, value(e.wettest_day.value, " mm")),
      ].join("");
      document.getElementById("tempNormalNote").textContent =
        `Abweichung vom Mittel ${data.reference.start}-${data.reference.end}: ${value(data.reference.temp_avg_c, " °C")}`;
      document.getElementById("rainNormalNote").textContent =
        `Abweichung vom Jahresmittel ${data.reference.start}-${data.reference.end}: ${value(data.reference.rain_year_mm, " mm")}`;
    }

    function renderStations(stations, source) {
      const body = document.getElementById("stations");
      if (source !== "dwd_filled") {
        body.innerHTML = `<tr><td colspan="5">Lokale CSV: nur Dresden-Klotzsche.</td></tr>`;
        return;
      }
      body.innerHTML = stations.map(row => `
        <tr>
          <td><a href="${row.source_url}" target="_blank" rel="noopener noreferrer">${row.station_name}</a></td>
          <td>${row.first_date} bis ${row.last_date}</td>
          <td>${fmt.format(row.temp_days)}</td>
          <td>${fmt.format(row.rain_days)}</td>
          <td><a href="${row.product_url}" target="_blank" rel="noopener noreferrer" title="${row.product_file}">DWD-Datei</a></td>
        </tr>
      `).join("");
    }

    function activateTab(tabName) {
      document.querySelectorAll(".tab-button").forEach(button => {
        const active = button.dataset.tab === tabName;
        button.classList.toggle("active", active);
        button.setAttribute("aria-selected", active ? "true" : "false");
      });
      document.querySelectorAll("[data-tab-panel]").forEach(panel => {
        panel.classList.toggle("active", panel.dataset.tabPanel === tabName);
      });
      if (tabName === "analysis") {
        window.requestAnimationFrame(() => loadDashboard().catch(error => setStatus(`Fehler: ${error.message}`)));
      }
    }

    function setupCanvas(canvas) {
      const ctx = canvas.getContext("2d");
      const ratio = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.max(320, Math.floor(rect.width * ratio));
      canvas.height = Math.floor(270 * ratio);
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      return { ctx, width: canvas.width / ratio, height: canvas.height / ratio };
    }

    function formatTooltipValue(point) {
      if (point === null || point === undefined || !Number.isFinite(point)) return "n/a";
      return fmt.format(point);
    }

    function registerChart(canvas, labels, series, xPositions) {
      chartState.set(canvas.id, { labels, series, xPositions });
      if (canvas.dataset.tooltipReady) return;
      canvas.dataset.tooltipReady = "true";
      canvas.addEventListener("mousemove", event => showChartTooltip(canvas, event));
      canvas.addEventListener("mouseleave", hideChartTooltip);
    }

    function showChartTooltip(canvas, event) {
      const state = chartState.get(canvas.id);
      if (!state || !state.xPositions.length) return;
      const rect = canvas.getBoundingClientRect();
      const mouseX = event.clientX - rect.left;
      let nearest = 0;
      let distance = Infinity;
      state.xPositions.forEach((x, index) => {
        const candidate = Math.abs(x - mouseX);
        if (candidate < distance) {
          distance = candidate;
          nearest = index;
        }
      });
      const rows = state.series.map(item => {
        const point = item.values[nearest];
        return `<div><span style="color:${item.color}">●</span> ${item.name}: ${formatTooltipValue(point)}</div>`;
      }).join("");
      tooltipEl.innerHTML = `<strong>${state.labels[nearest]}</strong>${rows}`;
      tooltipEl.style.left = `${event.clientX}px`;
      tooltipEl.style.top = `${event.clientY}px`;
      tooltipEl.style.opacity = "1";
    }

    function hideChartTooltip() {
      tooltipEl.style.opacity = "0";
    }

    function drawChart(canvas, labels, series, options = {}) {
      const { ctx, width, height } = setupCanvas(canvas);
      ctx.clearRect(0, 0, width, height);

      const pad = { left: 48, right: 18, top: 18, bottom: 36 };
      const allValues = series.flatMap(item => item.values).filter(v => v !== null && Number.isFinite(v));
      if (!allValues.length) return;
      let min = options.zero ? Math.min(0, ...allValues) : Math.min(...allValues);
      let max = Math.max(...allValues);
      if (min === max) { min -= 1; max += 1; }
      const plotW = width - pad.left - pad.right;
      const plotH = height - pad.top - pad.bottom;
      const x = i => pad.left + (labels.length <= 1 ? 0 : (i / (labels.length - 1)) * plotW);
      const y = v => pad.top + (1 - (v - min) / (max - min)) * plotH;
      const xPositions = labels.map((_, index) => x(index));

      ctx.strokeStyle = "#d7dde5";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(pad.left, pad.top);
      ctx.lineTo(pad.left, pad.top + plotH);
      ctx.lineTo(pad.left + plotW, pad.top + plotH);
      ctx.stroke();

      ctx.fillStyle = "#667085";
      ctx.font = "12px system-ui, sans-serif";
      ctx.textAlign = "right";
      for (let i = 0; i <= 4; i++) {
        const tick = min + ((max - min) * i) / 4;
        const ty = y(tick);
        ctx.strokeStyle = "#edf0f4";
        ctx.beginPath();
        ctx.moveTo(pad.left, ty);
        ctx.lineTo(pad.left + plotW, ty);
        ctx.stroke();
        ctx.fillText(fmt.format(tick), pad.left - 8, ty + 4);
      }

      ctx.textAlign = "center";
      const labelStep = Math.max(1, Math.ceil(labels.length / 7));
      labels.forEach((label, index) => {
        if (index % labelStep === 0 || index === labels.length - 1 || label === "2002") {
          ctx.fillStyle = label === "2002" ? "#17202a" : "#667085";
          ctx.fillText(label, x(index), height - 12);
        }
      });

      series.forEach(item => {
        ctx.strokeStyle = item.color;
        ctx.lineWidth = item.width || 2;
        ctx.beginPath();
        let started = false;
        item.values.forEach((point, index) => {
          if (point === null || !Number.isFinite(point)) return;
          const px = x(index);
          const py = y(point);
          if (!started) {
            ctx.moveTo(px, py);
            started = true;
          } else {
            ctx.lineTo(px, py);
          }
        });
        ctx.stroke();
      });

      let legendX = pad.left;
      series.forEach(item => {
        ctx.fillStyle = item.color;
        ctx.fillRect(legendX, 4, 10, 10);
        ctx.fillStyle = "#344054";
        ctx.textAlign = "left";
        ctx.fillText(item.name, legendX + 14, 13);
        legendX += ctx.measureText(item.name).width + 34;
      });
      registerChart(canvas, labels, series, xPositions);
    }

    function drawBars(canvas, labels, values, colors) {
      const { ctx, width, height } = setupCanvas(canvas);
      ctx.clearRect(0, 0, width, height);
      const pad = { left: 48, right: 18, top: 18, bottom: 36 };
      const clean = values.filter(v => v !== null && Number.isFinite(v));
      if (!clean.length) return;
      let min = Math.min(0, ...clean);
      let max = Math.max(0, ...clean);
      if (min === max) { min -= 1; max += 1; }
      const plotW = width - pad.left - pad.right;
      const plotH = height - pad.top - pad.bottom;
      const y = v => pad.top + (1 - (v - min) / (max - min)) * plotH;
      const zeroY = y(0);
      const barW = Math.max(2, plotW / Math.max(labels.length, 1) * 0.72);
      const xPositions = labels.map((_, index) => pad.left + (index + 0.5) * (plotW / labels.length));

      ctx.strokeStyle = "#d7dde5";
      ctx.beginPath();
      ctx.moveTo(pad.left, zeroY);
      ctx.lineTo(pad.left + plotW, zeroY);
      ctx.stroke();

      values.forEach((point, index) => {
        if (point === null || !Number.isFinite(point)) return;
        const x = pad.left + (index + 0.5) * (plotW / labels.length) - barW / 2;
        const top = Math.min(y(point), zeroY);
        const h = Math.abs(y(point) - zeroY);
        ctx.fillStyle = colors(point, labels[index]);
        ctx.fillRect(x, top, barW, Math.max(1, h));
      });

      ctx.fillStyle = "#667085";
      ctx.font = "12px system-ui, sans-serif";
      ctx.textAlign = "right";
      for (let i = 0; i <= 4; i++) {
        const tick = min + ((max - min) * i) / 4;
        ctx.fillText(fmt.format(tick), pad.left - 8, y(tick) + 4);
      }
      ctx.textAlign = "center";
      const labelStep = Math.max(1, Math.ceil(labels.length / 7));
      labels.forEach((label, index) => {
        if (index % labelStep === 0 || index === labels.length - 1 || label === "2002") {
          ctx.fillStyle = label === "2002" ? "#17202a" : "#667085";
          ctx.fillText(label, pad.left + (index + 0.5) * (plotW / labels.length), height - 12);
        }
      });
      registerChart(canvas, labels, [{ name: "Wert", values, color: "#2563eb" }], xPositions);
    }

    async function loadDashboard() {
      const source = "dwd_filled";
      const start = Number(document.getElementById("startYear").value);
      const end = Number(document.getElementById("endYear").value);
      const grain = document.getElementById("grain").value;
      if (start > end) {
        setStatus("Startjahr muss vor dem Endjahr liegen.");
        return;
      }
      setStatus("Daten werden geladen...");

      const [current, summary, rows, stations, climate] = await Promise.all([
        getJson("/api/current"),
        getJson(`/api/summary?start=${start}&end=${end}&source=${source}`),
        getJson(`/api/history?start=${start}&end=${end}&grain=${grain}&source=${source}`),
        getJson("/api/stations"),
        getJson(`/api/climate?start=${start}&end=${end}&source=${source}`),
      ]);

      renderCurrent(current);
      renderSummary(summary);
      renderExtremes(climate);
      renderStations(stations, source);

      const labels = rows.map(row => row.label);
      const annualRows = climate.annual;
      drawBars(
        document.getElementById("tempAnomalyChart"),
        annualRows.map(row => row.label),
        annualRows.map(row => row.temp_anomaly_c),
        point => point >= 0 ? "#e11d48" : "#2563eb",
      );
      drawBars(
        document.getElementById("rainAnomalyChart"),
        annualRows.map(row => row.label),
        annualRows.map(row => row.rain_anomaly_mm),
        point => point >= 0 ? "#2563eb" : "#b45309",
      );
      drawChart(document.getElementById("heavyRainChart"), annualRows.map(row => row.label), [
        { name: "Jahressumme", values: annualRows.map(row => row.rain_sum_mm), color: "#2563eb" },
        { name: "1 Tag", values: annualRows.map(row => row.rain_max_day_mm), color: "#e11d48" },
        { name: "3 Tage", values: annualRows.map(row => row.rain_max_3day_mm), color: "#b45309" },
        { name: "7 Tage", values: annualRows.map(row => row.rain_max_7day_mm), color: "#0f766e" },
      ], { zero: true });
      const tempSeries = [
        { name: "Mittel", values: rows.map(row => row.temp_avg_c), color: "#2563eb" },
        { name: "Maximum", values: rows.map(row => row.temp_max_c), color: "#e11d48" },
        { name: "Minimum", values: rows.map(row => row.temp_min_c), color: "#0f766e" },
      ];
      if (grain === "year") {
        tempSeries.splice(1, 0, { name: "10-Jahres-Trend", values: annualRows.map(row => row.temp_trend_10y_c), color: "#17202a", width: 3 });
      }
      drawChart(document.getElementById("tempChart"), labels, tempSeries);
      drawChart(document.getElementById("rainChart"), labels, [
        { name: "Niederschlag", values: rows.map(row => row.rain_sum_mm), color: "#2563eb" },
        { name: "Tagesmaximum", values: rows.map(row => row.rain_max_day_mm), color: "#e11d48" },
      ], { zero: true });
      drawChart(document.getElementById("climateChart"), labels, [
        { name: "Sonne", values: rows.map(row => row.sunshine_sum_h), color: "#b45309" },
        { name: "Feuchte", values: rows.map(row => row.humidity_pct), color: "#0f766e" },
      ], { zero: true });

      setStatus(`${fmt.format(rows.length)} Datenpunkte geladen.`);
    }

    function syncYearRange(changed) {
      const startInput = document.getElementById("startYear");
      const endInput = document.getElementById("endYear");
      const startText = document.getElementById("startYearText");
      const endText = document.getElementById("endYearText");
      let start = Number(startInput.value);
      let end = Number(endInput.value);
      if (start > end && changed === "start") end = start;
      if (end < start && changed === "end") start = end;
      startInput.value = start;
      endInput.value = end;
      startText.value = start;
      endText.value = end;
      const min = Number(startInput.min);
      const max = Number(startInput.max);
      const startPct = ((start - min) / (max - min)) * 100;
      const endPct = ((end - min) / (max - min)) * 100;
      document.getElementById("yearSlider").style.setProperty("--start-pos", `${startPct}%`);
      document.getElementById("yearSlider").style.setProperty("--end-pos", `${endPct}%`);
      document.getElementById("yearCountText").textContent = `${end - start + 1} Jahre`;
    }

    function syncYearText(changed) {
      const startInput = document.getElementById("startYear");
      const endInput = document.getElementById("endYear");
      const startText = document.getElementById("startYearText");
      const endText = document.getElementById("endYearText");
      const min = Number(startInput.min);
      const max = Number(startInput.max);
      let start = Number(startText.value);
      let end = Number(endText.value);
      if (!Number.isFinite(start)) start = Number(startInput.value);
      if (!Number.isFinite(end)) end = Number(endInput.value);
      start = Math.max(min, Math.min(max, Math.round(start)));
      end = Math.max(min, Math.min(max, Math.round(end)));
      if (start > end && changed === "start") end = start;
      if (end < start && changed === "end") start = end;
      startInput.value = start;
      endInput.value = end;
      syncYearRange(changed);
    }

    function scheduleLoad() {
      window.clearTimeout(reloadTimer);
      reloadTimer = window.setTimeout(() => {
        loadDashboard().catch(error => setStatus(`Fehler: ${error.message}`));
      }, 140);
    }

    document.getElementById("grain").addEventListener("change", () => {
      loadDashboard().catch(error => setStatus(`Fehler: ${error.message}`));
    });
    document.getElementById("startYear").addEventListener("input", () => {
      syncYearRange("start");
      scheduleLoad();
    });
    document.getElementById("endYear").addEventListener("input", () => {
      syncYearRange("end");
      scheduleLoad();
    });
    document.getElementById("startYearText").addEventListener("change", () => {
      syncYearText("start");
      scheduleLoad();
    });
    document.getElementById("endYearText").addEventListener("change", () => {
      syncYearText("end");
      scheduleLoad();
    });
    document.querySelectorAll(".tab-button").forEach(button => {
      button.addEventListener("click", () => activateTab(button.dataset.tab));
    });
    window.addEventListener("resize", () => scheduleLoad());
    syncYearRange();
    loadDashboard().catch(error => setStatus(`Fehler: ${error.message}`));
  </script>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path in {"/", "/api/index", "/api/index.py"}:
            self._send_html(INDEX_HTML)
            return
        if parsed.path == "/api/current":
            self._send_json(current_weather())
            return
        if parsed.path == "/api/stations":
            self._send_json(stations())
            return

        source = query.get("source", ["dwd_filled"])[0]
        if source not in {"local", "dwd_filled"}:
            source = "dwd_filled"
        data = weather_data(source)
        start = int(query.get("start", [int(data["year"].min())])[0])
        end = int(query.get("end", [int(data["year"].max())])[0])
        start = max(int(data["year"].min()), min(start, int(data["year"].max())))
        end = max(int(data["year"].min()), min(end, int(data["year"].max())))

        if parsed.path == "/api/summary":
            self._send_json(summary(start, end, source))
        elif parsed.path == "/api/history":
            grain = query.get("grain", ["year"])[0]
            if grain not in {"year", "month", "day"}:
                grain = "year"
            self._send_json(history(start, end, grain, source))
        elif parsed.path == "/api/climate":
            self._send_json(climate(start, end, source))
        else:
            self._send_json({"error": "Not found"}, status=404)

    def log_message(self, format, *args):
        return


def main():
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    print(f"Wetterdashboard läuft unter http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
