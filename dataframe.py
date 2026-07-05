from pathlib import Path

import pandas as pd


DATA_FILE = Path(__file__).with_name("Wetterdaten_DD_1934_2026.csv")

COLUMN_MAP = {
    "Datum": "date",
    "Jahr": "year",
    "Monat": "month",
    "Tag": "day",
    "taegliche Niederschlagshoehe": "rain_mm",
    "taegliche Sonnenscheindauer": "sunshine_h",
    "Tageswert Schneehoehe": "snow_depth_cm",
    "Tagesmittel des Luftdrucks": "pressure_hpa",
    "Tagesmittel der Temperatur": "temp_avg_c",
    "Tagesmittel der Relativen Feuchte": "humidity_pct",
    "Tagesmaximum der Lufttemperatur in 2m Hoehe": "temp_max_c",
    "Tagesminimum der Lufttemperatur in 2m Hoehe": "temp_min_c",
    "Tagesmittel Windgeschwindigkeit": "wind_avg_ms",
    "Tagesmaximum Windspitze": "wind_gust_ms",
}

NUMERIC_COLUMNS = [
    "rain_mm",
    "sunshine_h",
    "snow_depth_cm",
    "pressure_hpa",
    "temp_avg_c",
    "humidity_pct",
    "temp_max_c",
    "temp_min_c",
    "wind_avg_ms",
    "wind_gust_ms",
]


def _ascii_column_name(name):
    return (
        name.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("Ä", "Ae")
        .replace("Ö", "Oe")
        .replace("Ü", "Ue")
        .replace("ß", "ss")
        .replace("Höhe", "Hoehe")
        .replace("höhe", "hoehe")
    )


def _to_number(series):
    return pd.to_numeric(
        series.astype(str).str.replace(",", ".", regex=False).replace("-", pd.NA),
        errors="coerce",
    )


def read_file(file=DATA_FILE):
    """Read and normalize the daily weather data for Dresden-Klotzsche."""
    df = pd.read_csv(file, sep=";")
    df = df.rename(columns={column: _ascii_column_name(column) for column in df.columns})
    df = df.rename(columns=COLUMN_MAP)

    selected_columns = [column for column in COLUMN_MAP.values() if column in df.columns]
    weather = df[selected_columns].copy()

    weather["date"] = pd.to_datetime(weather["date"], format="%Y%m%d")
    weather["year"] = weather["date"].dt.year
    weather["month"] = weather["date"].dt.month
    weather["day"] = weather["date"].dt.day

    for column in NUMERIC_COLUMNS:
        if column in weather.columns:
            weather[column] = _to_number(weather[column])

    return weather.sort_values("date")


def year_bound(df, begin, end):
    period = df[(df["year"] >= int(begin)) & (df["year"] <= int(end))]
    yearly_temp = period.groupby("year")["temp_avg_c"].mean()
    yearly_rain = period.groupby("year")["rain_mm"].sum()

    return yearly_temp, yearly_rain


def summarize_period(df, begin, end):
    period = df[(df["year"] >= int(begin)) & (df["year"] <= int(end))]
    return {
        "days": int(len(period)),
        "temp_avg_c": float(period["temp_avg_c"].mean()),
        "temp_max_c": float(period["temp_max_c"].max()),
        "temp_min_c": float(period["temp_min_c"].min()),
        "rain_sum_mm": float(period["rain_mm"].sum()),
        "wet_days": int((period["rain_mm"] > 0).sum()),
    }
