from hashlib import sha1

import numpy as np
import pandas as pd

from .data import LOCATIONS, SAMPLE_END


def frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["timestamp", "location_id", "kwh", "interval_minutes", "quality"])
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df["kwh"] = pd.to_numeric(df["kwh"], errors="coerce")
        df = df.dropna(subset=["timestamp", "kwh"])
    return df


def select_period(rows: list[dict], days: int, location_id: str = "all") -> list[dict]:
    df = frame(rows)
    if df.empty:
        return []
    end = df.timestamp.max().floor("h") + pd.Timedelta(hours=1)
    start = end - pd.Timedelta(days=days)
    selected = df[(df["timestamp"] >= start) & (df["timestamp"] < end)]
    if location_id != "all":
        selected = selected[selected["location_id"] == location_id]
    return selected.assign(timestamp=selected["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")).to_dict("records")


def overview(rows: list[dict], days: int = 30, location_id: str = "all") -> dict:
    df = frame(rows)
    end = df.timestamp.max().floor("h") + pd.Timedelta(hours=1) if not df.empty else pd.Timestamp(SAMPLE_END)
    current_start = end - pd.Timedelta(days=days)
    previous_start = current_start - pd.Timedelta(days=days)
    selected = df[(df["timestamp"] >= current_start) & (df["timestamp"] < end)]
    has_previous_coverage = not df.empty and df.timestamp.min() <= previous_start
    previous = df[(df["timestamp"] >= previous_start) & (df["timestamp"] < current_start)] if has_previous_coverage else df.iloc[0:0]
    if location_id != "all":
        selected = selected[selected.location_id == location_id]
        previous = previous[previous.location_id == location_id]
    total = float(selected.kwh.sum()) if not selected.empty else 0.0
    previous_total = float(previous.kwh.sum()) if not previous.empty else 0.0
    daily = selected.assign(day=selected.timestamp.dt.strftime("%Y-%m-%d")).groupby("day").kwh.sum().to_dict() if not selected.empty else {}
    peak = selected.loc[selected.kwh.idxmax()].to_dict() if not selected.empty else None
    return {
        "total_kwh": round(total, 2), "previous_total_kwh": round(previous_total, 2) if has_previous_coverage else None,
        "change_percent": round((total - previous_total) / previous_total * 100, 2) if has_previous_coverage and previous_total else None,
        "daily_average_kwh": round(total / max(len(daily), 1), 2), "valid_intervals": int(len(selected)),
        "peak_interval": {**peak, "timestamp": peak["timestamp"].isoformat(), "kwh": float(peak["kwh"])} if peak else None,
        "energy_intensity": None, "energy_intensity_reason": "Floor-area and occupancy denominators are not present in the sample data.",
        "period_start": current_start.strftime("%Y-%m-%dT%H:%M:%SZ"), "period_end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def location_comparison(rows: list[dict], days: int = 30) -> list[dict]:
    selected = frame(select_period(rows, days))
    totals = selected.groupby("location_id").kwh.sum().to_dict() if not selected.empty else {}
    return [{"location_id": site["id"], "name": site["name"], "category": site["category"], "total_kwh": round(float(totals.get(site["id"], 0)), 2)} for site in sorted(LOCATIONS, key=lambda item: totals.get(item["id"], 0), reverse=True)]


def peak_events(rows: list[dict], days: int = 30, percentile: float = 95, location_id: str = "all") -> list[dict]:
    selected = frame(select_period(rows, days, location_id))
    if selected.empty:
        return []
    selected = selected[selected.quality == "valid"]
    if selected.empty:
        return []
    threshold = float(np.percentile(selected.kwh, percentile))
    events = selected[selected.kwh >= threshold].sort_values("kwh", ascending=False).head(100)
    return [{"timestamp": row.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"), "location_id": row.location_id, "kwh": round(float(row.kwh), 2), "average_power_kw": round(float(row.kwh) / (row.interval_minutes / 60), 2), "threshold_kwh": round(threshold, 2), "definition": f"Valid readings at or above the {percentile:g}th percentile ({threshold:.2f} kWh)."} for row in events.itertuples()]


def detect_anomalies(rows: list[dict]) -> list[dict]:
    df = frame(rows)
    if df.empty:
        return []
    events: list[dict] = []
    df["hour"] = df.timestamp.dt.hour
    df["weekday"] = df.timestamp.dt.day_of_week >= 5
    for location_id, group in df.groupby("location_id"):
        for _, cohort in group.groupby(["hour", "weekday"], sort=False):
            cohort = cohort.sort_values("timestamp")
            values = cohort.kwh.to_numpy(dtype=float)
            for index, row in enumerate(cohort.itertuples()):
                prior = values[:index]
                if len(prior) < 5:
                    continue
                median = float(np.median(prior))
                if row.kwh == 0 and row.hour in range(8, 19) and median > 0:
                    events.append(_event("unexpected-zero", row, median, "Unexpected zero consumption", "time-of-week zero", "Zero consumption during an hour with active comparable historical readings; check meter communication and operating schedule."))
                    continue
                if row.quality != "valid":
                    continue
                mad = float(np.median(np.abs(prior - median)))
                deviation = row.kwh - median
                robust_scale = max(1.4826 * mad, median * 0.05, 0.25)
                if deviation > 4.5 * robust_scale:
                    events.append(_event("robust-spike", row, median, "Unusual interval spike", "robust median/MAD", "Reading is substantially above the historical median for this location and comparable hour/day type; verify load schedule and meter accuracy."))
        daily = group.assign(day=group.timestamp.dt.floor("D")).groupby("day").kwh.sum().sort_index()
        if len(daily) >= 60:
            earlier = float(daily.iloc[:30].median())
            recent = float(daily.iloc[-30:].median())
            increase = (recent - earlier) / earlier if earlier > 0 else 0
            if increase >= 0.12:
                end = group.timestamp.max()
                events.append({"event_id": _id("sustained-baseline", location_id, end.isoformat()), "location_id": location_id, "timestamp": end.strftime("%Y-%m-%dT%H:%M:%SZ"), "observed_kwh": round(recent, 2), "expected_kwh": round(earlier, 2), "absolute_deviation_kwh": round(recent - earlier, 2), "deviation_percent": round(increase * 100, 2), "method": "sustained baseline increase", "severity": "medium", "evidence": f"Median daily energy in the last 30 observed days is {increase:.0%} above the first 30 days; operating activity and weather are not available to explain the difference.", "recommended_action": "Compare operating schedules, occupancy, and meter coverage across both periods before treating this as an operational issue."})
    by_location = {key: group.sort_values("timestamp") for key, group in df.groupby("location_id")}
    for location_id, group in by_location.items():
        expected = pd.date_range(group.timestamp.min(), group.timestamp.max(), freq="h", tz="UTC")
        observed = set(group.timestamp)
        missing = expected.difference(observed)
        for timestamp in missing:
            same_weekend_type = (group.timestamp.dt.day_of_week >= 5) == (timestamp.day_of_week >= 5)
            peers = group[(group.timestamp.dt.hour == timestamp.hour) & same_weekend_type]
            baseline = float(peers.kwh.median()) if not peers.empty else None
            events.append({"event_id": _id("meter-gap", location_id, timestamp.isoformat()), "location_id": location_id, "timestamp": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"), "observed_kwh": None, "expected_kwh": baseline, "absolute_deviation_kwh": None, "deviation_percent": None, "method": "missing interval", "severity": "medium", "evidence": "Expected hourly timestamp is absent; absence is not interpreted as zero consumption.", "recommended_action": "Check meter connectivity and source-file coverage."})
    return sorted(events, key=lambda item: item["timestamp"], reverse=True)


def _event(kind: str, row, baseline: float, title: str, method: str, reason: str) -> dict:
    difference = float(row.kwh) - baseline
    deviation = difference / baseline * 100 if baseline else None
    severity = "high" if deviation is not None and deviation >= 100 else "medium"
    return {"event_id": _id(kind, row.location_id, row.timestamp.isoformat()), "location_id": row.location_id, "timestamp": row.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"), "observed_kwh": round(float(row.kwh), 2), "expected_kwh": round(baseline, 2), "absolute_deviation_kwh": round(difference, 2), "deviation_percent": round(deviation, 2) if deviation is not None else None, "method": method, "severity": severity, "evidence": reason, "recommended_action": "Verify comparable operating conditions and meter accuracy before classifying this as a fault."}


def _id(*parts: str) -> str:
    return sha1("|".join(parts).encode()).hexdigest()[:16]


def recommendations(rows: list[dict]) -> list[dict]:
    df = frame(rows)
    if df.empty:
        return []
    df["hour"] = df.timestamp.dt.hour
    result = []
    for site in LOCATIONS:
        group = df[df.location_id == site["id"]]
        overnight = group[group.hour.between(0, 5)].kwh
        daytime = group[group.hour.between(8, 17)].kwh
        if len(overnight) and len(daytime):
            ratio = float(overnight.mean() / daytime.mean())
            if ratio > 0.48:
                result.append({"recommendation_id": _id("overnight-review", site["id"]), "location_id": site["id"], "title": "Review overnight base-load schedule", "category": "Schedule review", "priority": "Medium", "evidence": f"Overnight mean is {ratio:.0%} of daytime mean across observed intervals; occupancy and essential-load context are unavailable.", "proposed_action": "Compare overnight operating schedules and essential loads with the facility team.", "estimated_savings_kwh": None, "assumptions": "Investigation recommendation only. No avoidable baseline or reduction scenario is validated.", "status": "Suggested"})
        daily = group.assign(day=group.timestamp.dt.floor("D")).groupby("day").kwh.sum().sort_index()
        if len(daily) >= 60:
            earlier = float(daily.iloc[:30].median())
            recent = float(daily.iloc[-30:].median())
            increase = (recent - earlier) / earlier if earlier > 0 else 0
            if increase >= 0.12:
                result.append({"recommendation_id": _id("baseline-review", site["id"]), "location_id": site["id"], "title": "Investigate sustained consumption increase", "category": "Baseline change", "priority": "High", "evidence": f"Median daily energy rose {increase:.0%} between the first and last 30 observed days. This does not establish the cause or confirm avoidable use.", "proposed_action": "Compare schedules, occupancy, and meter coverage across both periods.", "estimated_savings_kwh": None, "assumptions": "Investigation recommendation only; no savings are estimated without a validated counterfactual baseline.", "status": "Suggested"})
    result.append({"recommendation_id": _id("data-coverage"), "location_id": "all", "title": "Review missing and flagged meter readings", "category": "Data quality", "priority": "Medium", "evidence": "The demonstration dataset includes four missing intervals and flagged synthetic readings.", "proposed_action": "Confirm meter coverage and validate unusual readings before operational action.", "estimated_savings_kwh": None, "assumptions": "No energy or monetary savings claimed.", "status": "Suggested"})
    return result


def quality_summary(rows: list[dict]) -> dict:
    df = frame(rows)
    expected = 90 * 24 * len(LOCATIONS)
    return {"record_count": len(df), "flagged_count": int((df.quality == "flagged").sum()) if not df.empty else 0, "negative_count": int((df.kwh < 0).sum()) if not df.empty else 0, "expected_demo_intervals": expected, "missing_intervals": max(expected - len(df), 0), "interval_minutes": 60, "timezone": "UTC", "source": "Generated sample data", "missing_policy": "Missing readings are excluded, never interpreted as zero."}