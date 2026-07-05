# WetterDresden

Ein lokales Wetterdashboard fuer Dresden mit Live-Werten, DWD-Tagesdaten und
Klimaauswertungen fuer frei waehlbare Zeitraeume.

Das Dashboard laeuft lokal im Browser unter `http://127.0.0.1:8000/`.

## Was das Dashboard zeigt

- Live-Durchschnitt aus Dresdener Open-Meteo-Stationen
- Temperatur, Niederschlag, Luftdruck, Luftfeuchte und Wind als Live-Kacheln
- historischer DWD-Datensatz fuer Dresden und nahe regionale Stationen
- Auswertung nach Jahr, Monat oder Tag
- frei waehlbarer Zeitraum mit Slider und Eingabefeldern
- Temperatur- und Niederschlagsabweichung passend zum gewaehlten Zeitraum
- Starkregenansicht mit 1-, 3- und 7-Tage-Regenmengen
- Extremwerte wie waermstes, kaeltestes, nassestes und trockenstes Jahr
- Data-Reiter mit DWD-Stationen und direkten Quellenlinks

## Datenquellen

### Live-Daten

Die aktuellen Wetterwerte kommen von Open-Meteo und werden als Durchschnitt
mehrerer Dresdener Stationen dargestellt:

- Dresden-Klotzsche
- Dresden-Hosterwitz
- Dresden-Strehlen

Live-Kacheln sind im Dashboard mit einem pulsierenden gruenen Rand markiert.

### Historische Daten

Die langfristige Datenbasis ist `DWD regional gefuellt`. Dabei wird
Dresden-Klotzsche als Hauptstation genutzt und fehlende Werte werden mit nahen
DWD-Stationen ergaenzt.

Verwendete DWD-Stationen:

- Dresden-Klotzsche
- Dresden-Hosterwitz
- Dresden-Strehlen
- Wahnsdorf bei Dresden
- Freiberg
- Kubschuetz, Kr. Bautzen

Die Originaldaten stammen aus dem DWD-CDC-Open-Data-Archiv:

`https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/historical/`

Beim ersten Abruf werden die benoetigten DWD-Dateien lokal in `data/dwd/`
zwischengespeichert. Dieser Cache wird nicht versioniert.

## Starten

Am einfachsten per Doppelklick:

```text
start_dashboard.bat
```

Oder direkt ueber Python:

```powershell
python app.py
```

Falls `python` nicht im Pfad liegt, kann die mit Codex bereitgestellte
Python-Installation genutzt werden:

```powershell
C:\Users\jaden\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe app.py
```

Danach im Browser oeffnen:

```text
http://127.0.0.1:8000/
```

## Voraussetzungen

Das Dashboard ist bewusst leichtgewichtig gebaut:

- Python
- pandas
- eine Internetverbindung fuer den ersten DWD-Download und die Live-Werte

Die Benutzeroberflaeche liegt direkt in `app.py`; es ist kein Frontend-Build
notwendig.

## Projektstruktur

```text
.
├── app.py                         # lokaler Webserver, API und Dashboard-UI
├── dwd_data.py                    # Download, Cache und Aufbereitung der DWD-Daten
├── dataframe.py                   # Hilfsfunktionen fuer lokale CSV-Daten
├── analysis.py                    # einfache Konsolenanalyse
├── Wetterdaten_DD_1934_2026.csv   # lokaler Ausgangsdatensatz
├── start_dashboard.bat            # Startscript fuer Windows
└── data/dwd/                      # lokaler DWD-Cache, nicht versioniert
```

## Lokale API

Das Dashboard stellt intern einfache JSON-Endpunkte bereit:

- `/api/current`
- `/api/summary`
- `/api/history`
- `/api/climate`
- `/api/stations`

## Hinweise

- Klimaabweichungen beziehen sich immer auf den aktuell gewaehlten Zeitraum.
- Starkregen wird getrennt vom Jahresniederschlag betrachtet.
- Der DWD-Cache kann geloescht werden; er wird beim naechsten Start erneut
  aufgebaut.
