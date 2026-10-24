from datetime import timedelta

from backend.app.analytics import detect_anomalies, location_comparison, overview, peak_events, recommendations, select_period
from backend.app.data import LOCATIONS, SAMPLE_END, SAMPLE_START, generate_readings


def small_rows(days=56):
    start = SAMPLE_END - timedelta(days=days)
    rows = []
    for day in range(days):
        for hour in range(24):
            for site in LOCATIONS[:2]:
                rows.append({"timestamp": (start + timedelta(days=day, hours=hour)).isoformat().replace("+00:00", "Z"), "location_id": site["id"], "kwh": 10.0 + site["base"] / 100, "interval_minutes": 60, "quality": "valid"})
    return rows


def test_demo_generation_is_reproducible_and_has_quality_cases():
    first, second = generate_readings(), generate_readings()
    assert first == second
    assert len(first) == 90 * 24 * 6 - 4
    assert any(row["quality"] == "flagged" for row in first)


def test_overview_sums_interval_energy_and_zero_baseline_has_no_percent():
    rows = small_rows(8)
    result = overview(rows, days=8)
    assert result["total_kwh"] == round(sum(row["kwh"] for row in rows), 2)
    assert overview([], days=8)["change_percent"] is None
    assert overview(generate_readings(), days=90)["change_percent"] is None
    assert overview(generate_readings(), days=30)["change_percent"] is not None


def test_location_comparison_is_ranked_by_absolute_energy():
    ranked = location_comparison(small_rows(8), days=8)
    assert ranked[0]["location_id"] == "engineering"
    assert ranked[0]["total_kwh"] > ranked[1]["total_kwh"]


def test_later_imported_readings_advance_analysis_window():
    rows = small_rows(8)
    rows.append({"timestamp": "2026-11-01T09:00:00Z", "location_id": "admin", "kwh": 24.5, "interval_minutes": 60, "quality": "valid"})
    selected = select_period(rows, days=1)
    assert len(selected) == 1
    assert selected[0]["kwh"] == 24.5


def test_peak_threshold_is_explicit_and_returns_supporting_interval():
    rows = small_rows()
    rows[-1]["kwh"] = 100
    events = peak_events(rows, days=56, percentile=95)
    assert events and events[0]["kwh"] == 100
    assert "95th percentile" in events[0]["definition"]


def test_detector_separates_missing_intervals_from_spikes():
    rows = small_rows()
    rows = [row for row in rows if not (row["location_id"] == "admin" and row["timestamp"].startswith("2026-10-01T04:"))]
    rows.append({"timestamp": "2026-10-23T13:00:00Z", "location_id": "admin", "kwh": 100, "interval_minutes": 60, "quality": "valid"})
    events = detect_anomalies(rows)
    assert any(item["method"] == "missing interval" for item in events)
    assert any(item["method"] == "robust median/MAD" for item in events)


def test_recommendations_do_not_invent_savings_without_valid_baseline():
    items = recommendations(small_rows())
    assert items
    assert all(item["estimated_savings_kwh"] is None for item in items)