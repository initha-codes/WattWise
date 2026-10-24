import csv
import io
import math
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import analytics, database
from .data import LOCATIONS

@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    yield


app = FastAPI(title="WattWise Energy Intelligence API", version="1.0.0", description="Analytics over reproducible fictional campus readings.", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])


class StateUpdate(BaseModel):
    status: str = Field(min_length=2, max_length=32)
    note: str = Field(default="", max_length=2000)


class ImportRow(BaseModel):
    timestamp: datetime
    location_id: str
    kwh: float = Field(ge=0, allow_inf_nan=False)
    interval_minutes: int = Field(default=60, gt=0, le=1440)


class ImportConfirmation(BaseModel):
    readings: list[ImportRow] = Field(max_length=100_000)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "source": "generated sample data", "timezone": "UTC"}


@app.get("/api/locations")
def get_locations() -> list[dict]:
    return [{key: value for key, value in site.items() if key != "base"} for site in LOCATIONS]


@app.get("/api/overview")
def get_overview(days: int = Query(30, ge=1, le=90), location_id: str = "all") -> dict:
    return analytics.overview(database.fetch_readings(), days, location_id)


@app.get("/api/consumption")
def get_consumption(days: int = Query(90, ge=1, le=90), location_id: str = "all", aggregation: Literal["hour", "day", "week", "month"] = "hour") -> dict:
    rows = analytics.select_period(database.fetch_readings(), days, location_id)
    df = analytics.frame(rows)
    if df.empty:
        return {"readings": [], "series": [], "aggregation": aggregation}
    if aggregation in {"hour", "day"}:
        df["period"] = df.timestamp.dt.floor({"hour": "h", "day": "D"}[aggregation])
    elif aggregation == "week":
        df["period"] = df.timestamp.dt.to_period("W-SUN").dt.start_time.dt.tz_localize("UTC")
    else:
        df["period"] = df.timestamp.dt.to_period("M").dt.start_time.dt.tz_localize("UTC")
    series = df.groupby("period").kwh.sum().rename("kwh").reset_index()
    return {"readings": rows, "series": [{"timestamp": row.period.strftime("%Y-%m-%dT%H:%M:%SZ"), "kwh": round(float(row.kwh), 2)} for row in series.itertuples()], "aggregation": aggregation}


@app.get("/api/location-comparison")
def get_comparison(days: int = Query(30, ge=1, le=90)) -> list[dict]:
    return analytics.location_comparison(database.fetch_readings(), days)


@app.get("/api/peak-periods")
def get_peaks(days: int = Query(30, ge=1, le=90), percentile: float = Query(95, ge=50, le=99.9), location_id: str = "all") -> dict:
    return {"definition": f"Valid hourly readings at or above the {percentile:g}th percentile.", "events": analytics.peak_events(database.fetch_readings(), days, percentile, location_id)}


@app.get("/api/anomalies")
def get_anomalies(location_id: str = "all", status: str | None = None, severity: str | None = None) -> list[dict]:
    states = database.get_states("anomaly_states")
    events = analytics.detect_anomalies(database.fetch_readings())
    for event in events:
        state = states.get(event["event_id"], {})
        event["status"] = state.get("status", "New")
        event["analyst_note"] = state.get("note", "")
    return [event for event in events if (location_id == "all" or event["location_id"] == location_id) and (status is None or event["status"] == status) and (severity is None or event["severity"] == severity)]


@app.get("/api/anomalies/{event_id}")
def get_anomaly(event_id: str) -> dict:
    event = next((item for item in get_anomalies() if item["event_id"] == event_id), None)
    if event is None:
        raise HTTPException(status_code=404, detail="Anomaly event not found")
    return event


@app.patch("/api/anomalies/{event_id}")
def patch_anomaly(event_id: str, update: StateUpdate) -> dict:
    exists = any(item["event_id"] == event_id for item in analytics.detect_anomalies(database.fetch_readings()))
    if not exists:
        raise HTTPException(status_code=404, detail="Anomaly event not found")
    if update.status not in {"New", "Investigating", "Resolved", "False positive"}:
        raise HTTPException(status_code=422, detail="Unsupported anomaly status")
    return database.set_state("anomaly_states", "event_id", event_id, update.status, update.note)


@app.get("/api/recommendations")
def get_recommendations(status: str | None = None, location_id: str = "all") -> list[dict]:
    states = database.get_states("recommendation_states")
    items = analytics.recommendations(database.fetch_readings())
    for item in items:
        state = states.get(item["recommendation_id"], {})
        item["status"] = state.get("status", item["status"])
        item["analyst_note"] = state.get("note", "")
    return [item for item in items if (status is None or item["status"] == status) and (location_id == "all" or item["location_id"] in {location_id, "all"})]


@app.get("/api/recommendations/{recommendation_id}")
def get_recommendation(recommendation_id: str) -> dict:
    item = next((entry for entry in get_recommendations() if entry["recommendation_id"] == recommendation_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return item


@app.patch("/api/recommendations/{recommendation_id}")
def patch_recommendation(recommendation_id: str, update: StateUpdate) -> dict:
    exists = any(item["recommendation_id"] == recommendation_id for item in analytics.recommendations(database.fetch_readings()))
    if not exists:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    if update.status not in {"Suggested", "Accepted", "In Progress", "Completed", "Dismissed"}:
        raise HTTPException(status_code=422, detail="Unsupported recommendation status")
    return database.set_state("recommendation_states", "recommendation_id", recommendation_id, update.status, update.note)


@app.get("/api/data-quality")
def get_quality() -> dict:
    return analytics.quality_summary(database.fetch_readings())


@app.post("/api/import/preview")
async def preview_import(file: UploadFile = File(...)) -> dict:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=415, detail="Upload a CSV file.")
    try:
        text = (await file.read()).decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise HTTPException(status_code=400, detail="Could not parse CSV as UTF-8.") from exc
    aliases = {"timestamp": {"timestamp", "datetime", "time"}, "location_id": {"location_id", "locationid", "location"}, "kwh": {"kwh", "consumption_kwh", "energy_kwh"}}
    headers = {str(header).strip().lower(): header for header in (reader.fieldnames or [])}
    columns = {name: next((headers[item] for item in options if item in headers), None) for name, options in aliases.items()}
    if any(value is None for value in columns.values()):
        raise HTTPException(status_code=422, detail="Required columns: timestamp, location_id, kwh.")
    site_names = {site["id"]: site["name"] for site in LOCATIONS}
    name_ids = {site["name"].casefold(): site["id"] for site in LOCATIONS}
    valid, rejected = [], []
    seen = {
        (datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(), item["location_id"])
        for item in database.fetch_readings()
    }
    for line, row in enumerate(reader, start=2):
        try:
            timestamp = datetime.fromisoformat(str(row[columns["timestamp"]]).replace("Z", "+00:00"))
            timestamp = timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp.astimezone(timezone.utc)
            raw_id = str(row[columns["location_id"]]).strip()
            location_id = raw_id if raw_id in site_names else name_ids.get(raw_id.casefold())
            kwh = float(row[columns["kwh"]])
            if not location_id or not math.isfinite(kwh) or kwh < 0:
                raise ValueError("unknown location or negative consumption")
            key = (timestamp.isoformat(), location_id)
            if key in seen:
                rejected.append({"line": line, "reason": "duplicate timestamp and location"})
                continue
            seen.add(key)
            valid.append({"timestamp": timestamp.isoformat().replace("+00:00", "Z"), "location_id": location_id, "location_name": site_names[location_id], "kwh": kwh, "interval_minutes": 60, "quality": "valid"})
        except (TypeError, ValueError, OverflowError) as exc:
            rejected.append({"line": line, "reason": str(exc) or "invalid timestamp or numeric value"})
    return {"valid_count": len(valid), "rejected_count": len(rejected), "duplicates": sum("duplicate" in item["reason"] for item in rejected), "preview": valid[:20], "valid_readings": valid, "rejected": rejected[:100], "schema": "timestamp, location_id, kwh"}


@app.post("/api/import/confirm")
def confirm_import(payload: ImportConfirmation) -> dict:
    allowed = {site["id"] for site in LOCATIONS}
    if any(row.location_id not in allowed for row in payload.readings):
        raise HTTPException(status_code=422, detail="Unknown location_id.")
    rows = [{"timestamp": row.timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "location_id": row.location_id, "kwh": row.kwh, "interval_minutes": row.interval_minutes, "quality": "valid"} for row in payload.readings]
    inserted = database.insert_readings(rows)
    return {"inserted": inserted, "submitted": len(rows), "duplicates_ignored": len(rows) - inserted}


def csv_response(rows: list[dict], filename: str) -> StreamingResponse:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()) if rows else ["timestamp", "location_id", "kwh"])
    writer.writeheader()
    writer.writerows(rows)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/export/consumption")
def export_consumption(days: int = Query(30, ge=1, le=90), location_id: str = "all") -> StreamingResponse:
    return csv_response(analytics.select_period(database.fetch_readings(), days, location_id), "wattwise-consumption.csv")


@app.get("/api/export/anomalies")
def export_anomalies() -> StreamingResponse:
    return csv_response(get_anomalies(), "wattwise-anomalies.csv")


@app.get("/api/export/recommendations")
def export_recommendations() -> StreamingResponse:
    return csv_response(get_recommendations(), "wattwise-recommendations.csv")


@app.post("/api/demo/restore")
def restore_sample() -> dict:
    database.restore_demo()
    return {"status": "restored", "records": len(database.fetch_readings())}