from functools import lru_cache
from io import BytesIO
from pathlib import Path
from urllib.request import urlopen
import re
import zipfile

import pandas as pd


DWD_BASE = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/historical/"
CACHE_DIR = Path(__file__).with_name("data").joinpath("dwd")
STATION_LIST_FILE = CACHE_DIR / "KL_Tageswerte_Beschreibung_Stationen.txt"
REGIONAL_OBSERVATIONS_CACHE = CACHE_DIR / "regional_observations.pkl"
FILLED_SERIES_CACHE = CACHE_DIR / "filled_regional_series.pkl"

REGIONAL_STATIONS = [
    "01048",  # Dresden-Klotzsche
    "01050",  # Dresden-Hosterwitz
    "01051",  # Dresden-Strehlen
    "05282",  # Wahnsdorf bei Dresden
    "01441",  # Freiberg
    "00314",  # Kubschuetz, Kr. Bautzen
]

STATION_PRIORITY = {
    "01048": 1,
    "01050": 2,
    "01051": 3,
    "05282": 4,
    "01441": 5,
    "00314": 6,
}

DWD_COLUMN_MAP = {
    "STATIONS_ID": "station_id",
    "MESS_DATUM": "date",
    "FX": "wind_gust_ms",
    "FM": "wind_avg_ms",
    "RSK": "rain_mm",
    "SDK": "sunshine_h",
    "SHK_TAG": "snow_depth_cm",
    "PM": "pressure_hpa",
    "TMK": "temp_avg_c",
    "UPM": "humidity_pct",
    "TXK": "temp_max_c",
    "TNK": "temp_min_c",
    "TGK": "temp_ground_min_c",
}

NUMERIC_COLUMNS = [
    "wind_gust_ms",
    "wind_avg_ms",
    "rain_mm",
    "sunshine_h",
    "snow_depth_cm",
    "pressure_hpa",
    "temp_avg_c",
    "humidity_pct",
    "temp_max_c",
    "temp_min_c",
    "temp_ground_min_c",
]


def _download_text(url):
    with urlopen(url, timeout=30) as response:
        return response.read().decode("latin1")


def _download_bytes(url):
    with urlopen(url, timeout=60) as response:
        return response.read()


def ensure_cache_dir():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def station_list(force=False):
    ensure_cache_dir()
    if force or not STATION_LIST_FILE.exists():
        text = _download_text(DWD_BASE + "KL_Tageswerte_Beschreibung_Stationen.txt")
        STATION_LIST_FILE.write_text(text, encoding="utf-8")
    try:
        return STATION_LIST_FILE.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = STATION_LIST_FILE.read_text(encoding="latin1")
        STATION_LIST_FILE.write_text(text, encoding="utf-8")
        return text


def parse_station_list(text):
    rows = []
    for line in text.splitlines():
        if not re.match(r"^\d{5}\s+\d{8}\s+\d{8}\s+", line):
            continue
        parts = line.split(maxsplit=6)
        if len(parts) < 7:
            continue
        station_id, start, end, height, lat, lon, rest = parts
        name = rest
        state = ""
        for marker in [" Baden-Wuerttemberg", " Bayern", " Berlin", " Brandenburg", " Bremen", " Hamburg", " Hessen", " Mecklenburg-Vorpommern", " Niedersachsen", " Nordrhein-Westfalen", " Rheinland-Pfalz", " Saarland", " Sachsen", " Sachsen-Anhalt", " Schleswig-Holstein", " Thueringen"]:
            if marker in rest:
                name, state = rest.split(marker, 1)
                state = marker.strip()
                break
        rows.append(
            {
                "station_id": station_id,
                "start": start,
                "end": end,
                "height_m": int(height),
                "lat": float(lat),
                "lon": float(lon),
                "name": name.strip(),
                "state": state,
            }
        )
    return pd.DataFrame(rows)


def remote_zip_names(force=False):
    ensure_cache_dir()
    index_file = CACHE_DIR / "historical_index.html"
    if force or not index_file.exists():
        index_file.write_text(_download_text(DWD_BASE), encoding="latin1")
    html = index_file.read_text(encoding="latin1")
    return re.findall(r'tageswerte_KL_\d{5}_\d{8}_\d{8}_hist\.zip', html)


def station_zip_name(station_id):
    station_id = str(station_id).zfill(5)
    matches = [name for name in remote_zip_names() if f"_{station_id}_" in name]
    if not matches:
        raise FileNotFoundError(f"Keine DWD-ZIP-Datei für Station {station_id} gefunden.")
    return sorted(matches)[-1]


def station_source_url(station_id):
    return DWD_BASE


def station_product_name(station_id):
    try:
        return station_zip_name(station_id)
    except (FileNotFoundError, OSError):
        return ""


def station_product_url(station_id):
    product_name = station_product_name(station_id)
    return DWD_BASE + product_name if product_name else DWD_BASE


def ensure_station_zip(station_id):
    ensure_cache_dir()
    zip_name = station_zip_name(station_id)
    zip_path = CACHE_DIR / zip_name
    if not zip_path.exists():
        zip_path.write_bytes(_download_bytes(DWD_BASE + zip_name))
    return zip_path


def read_station_zip(station_id):
    station_id = str(station_id).zfill(5)
    zip_path = ensure_station_zip(station_id)
    with zipfile.ZipFile(zip_path) as archive:
        product_name = next(name for name in archive.namelist() if name.startswith("produkt_klima_tag_"))
        with archive.open(product_name) as product:
            df = pd.read_csv(product, sep=";", encoding="latin1")

    df.columns = [column.strip() for column in df.columns]
    df = df.rename(columns=DWD_COLUMN_MAP)
    selected = [column for column in DWD_COLUMN_MAP.values() if column in df.columns]
    df = df[selected].copy()
    df["station_id"] = df["station_id"].astype(str).str.zfill(5)
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    df["day"] = df["date"].dt.day

    for column in NUMERIC_COLUMNS:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
            df[column] = df[column].where(df[column] > -900)

    return df


@lru_cache(maxsize=1)
def regional_station_meta():
    stations = parse_station_list(station_list())
    stations = stations[stations["station_id"].isin(REGIONAL_STATIONS)].copy()
    stations["priority"] = stations["station_id"].map(STATION_PRIORITY)
    return stations.sort_values("priority")


@lru_cache(maxsize=1)
def regional_observations():
    ensure_cache_dir()
    if REGIONAL_OBSERVATIONS_CACHE.exists():
        return pd.read_pickle(REGIONAL_OBSERVATIONS_CACHE)

    frames = []
    meta = regional_station_meta().set_index("station_id")
    for station_id in REGIONAL_STATIONS:
        station = read_station_zip(station_id)
        station["station_name"] = meta.loc[station_id, "name"] if station_id in meta.index else station_id
        station["priority"] = STATION_PRIORITY[station_id]
        frames.append(station)
    observations = pd.concat(frames, ignore_index=True).sort_values(["date", "priority"])
    observations.to_pickle(REGIONAL_OBSERVATIONS_CACHE)
    return observations


def filled_regional_series():
    ensure_cache_dir()
    if FILLED_SERIES_CACHE.exists():
        return pd.read_pickle(FILLED_SERIES_CACHE)

    df = regional_observations()
    value_columns = [column for column in NUMERIC_COLUMNS if column in df.columns]
    ordered = df.sort_values(["date", "priority"]).copy()

    base = ordered.groupby("date", as_index=False).first()[["date", "station_id", "station_name"]]
    filled = base.copy()
    source_frames = []
    for column in value_columns:
        valid = ordered.dropna(subset=[column])
        first_values = valid.groupby("date", as_index=False).first()[["date", column, "station_name"]]
        first_values = first_values.rename(columns={"station_name": f"{column}_source"})
        filled = filled.merge(first_values[["date", column]], on="date", how="left")
        source_frames.append(first_values[["date", f"{column}_source"]])

    for source_frame in source_frames:
        filled = filled.merge(source_frame, on="date", how="left")

    source_columns = [f"{column}_source" for column in value_columns]
    filled["source_detail"] = filled[source_columns].apply(
        lambda row: "; ".join(
            f"{column.removesuffix('_source')}:{source}"
            for column, source in row.items()
            if pd.notna(source)
        ),
        axis=1,
    )
    filled = filled.drop(columns=source_columns)
    filled["year"] = filled["date"].dt.year
    filled["month"] = filled["date"].dt.month
    filled["day"] = filled["date"].dt.day
    filled = filled.sort_values("date")
    filled.to_pickle(FILLED_SERIES_CACHE)
    return filled


def station_coverage():
    df = regional_observations()
    grouped = df.groupby(["station_id", "station_name"]).agg(
        first_date=("date", "min"),
        last_date=("date", "max"),
        days=("date", "count"),
        temp_days=("temp_avg_c", "count"),
        rain_days=("rain_mm", "count"),
    )
    coverage = grouped.reset_index()
    coverage["source_url"] = coverage["station_id"].apply(station_source_url)
    coverage["product_file"] = coverage["station_id"].apply(station_product_name)
    coverage["product_url"] = coverage["station_id"].apply(station_product_url)
    return coverage
