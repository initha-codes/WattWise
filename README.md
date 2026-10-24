# WattWise

WattWise is a local energy-intelligence prototype for a fictional campus network. It includes a React dashboard and a FastAPI/SQLite service. The seeded 90-day dataset is generated with a fixed NumPy seed; it is synthetic and is never presented as live meter data.

## Run locally

Requirements: Node.js 20.19+ or 22.12+, Python 3.10+.

```powershell
npm install
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Start the API and frontend in separate terminals from the project root:

```powershell
uvicorn backend.app.main:app --reload --port 8000
npm run dev
```

Open the Vite URL printed in the frontend terminal (normally `http://localhost:5173`). If the API is unavailable, the interface uses the same-shaped deterministic browser sample as a local fallback. API docs are at `http://localhost:8000/docs`.

## What to demonstrate

1. Overview: change the global date and location filters; chart totals, profiles, and location ranking respond to the selected sample readings.
2. Locations: select comparison sites and inspect their daily energy traces. Values are absolute energy, not normalized efficiency.
3. Peak periods: move the percentile control and inspect the actual qualifying intervals and same-hour reference.
4. Anomalies and recommendations: update status; SQLite persists API-backed status, with browser storage as the no-API fallback.
5. Data explorer: choose a CSV to preview valid rows and excluded records, confirm import, or export filtered readings. Restore returns the seeded dataset.
6. Reports: print the active-filter summary or download its readings.

## Import schema

The import preview accepts UTF-8 CSV with required columns `timestamp`, `location_id`, and `kwh`. Accepted aliases include `datetime`/`time`, `locationid`/`location`, and `consumption_kwh`/`energy_kwh`. Timestamps with offsets are normalized to UTC; naive timestamps are assumed UTC. Location identifiers must match a known sample site. Negative or nonnumeric energy, unknown locations, invalid timestamps, and duplicate timestamp-location pairs are rejected and reported. See [examples/import_template.csv](examples/import_template.csv).

## API

- `GET /api/health`, `/api/locations`, `/api/overview`, `/api/consumption`, `/api/location-comparison`, `/api/peak-periods`
- `GET /api/anomalies`, `/api/anomalies/{event_id}`; `PATCH /api/anomalies/{event_id}`
- `GET /api/recommendations`, `/api/recommendations/{recommendation_id}`; `PATCH /api/recommendations/{recommendation_id}`
- `GET /api/data-quality`; `POST /api/import/preview`, `POST /api/import/confirm`, `POST /api/demo/restore`
- `GET /api/export/consumption`, `/api/export/anomalies`, `/api/export/recommendations`

SQLite defaults to `data/wattwise.db`; set `WATTWISE_DATABASE` to use another file. The database is created and seeded on first API startup. The UI proxies `/api` requests to port 8000.

## Methodology and limits

- Total energy is the sum of valid interval kWh. Missing intervals are excluded, not changed to zero.
- Comparison uses the immediately preceding equivalent day-count window. A zero previous-period denominator yields no percent change.
- Peak events are valid readings at or above a configurable percentile within the selected period and location. Average power is derived only for the documented 60-minute interval.
- The backend robust-spike detector compares each observation with at least five earlier observations for that location, hour, and weekday/weekend class. It uses median absolute deviation with a floor for low dispersion. Separate rules identify operating-hour zeros and absent hourly timestamps.
- Recommendations are investigation steps. Savings remain unquantified because no validated avoidable baseline, reduction scenario, facility area/occupancy, tariff, or before/after verification is available.
- No weather, occupancy, floor area, or live source integration is simulated or implied.

## Tests

```powershell
python -m pytest
npm run build
```# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.
