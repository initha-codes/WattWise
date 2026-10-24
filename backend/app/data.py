from datetime import datetime, timedelta, timezone

import numpy as np

LOCATIONS = [
    {"id": "admin", "name": "Administration Building", "category": "Office", "base": 18, "color": "#0d9488"},
    {"id": "engineering", "name": "Engineering Block", "category": "Academic", "base": 31, "color": "#4f7c69"},
    {"id": "computer", "name": "Computer Laboratory", "category": "Laboratory", "base": 26, "color": "#d59235"},
    {"id": "library", "name": "Library", "category": "Academic", "base": 20, "color": "#5287a1"},
    {"id": "hostel", "name": "Student Hostel", "category": "Residential", "base": 34, "color": "#9a7560"},
    {"id": "utilities", "name": "Central Utilities", "category": "Infrastructure", "base": 42, "color": "#688571"},
]
SAMPLE_START = datetime(2026, 7, 27, tzinfo=timezone.utc)
SAMPLE_END = SAMPLE_START + timedelta(days=90)


def generate_readings() -> list[dict]:
    """Generate reproducible hourly campus readings with documented quality cases."""
    rng = np.random.default_rng(42)
    output = []
    for day in range(90):
        weekday = (SAMPLE_START.weekday() + day) % 7
        weekend = weekday >= 5
        for hour in range(24):
            for index, site in enumerate(LOCATIONS):
                daytime = 8 <= hour < 19
                evening = 18 <= hour < 23
                factor = 1.46 if daytime else (0.43 if hour < 6 else 0.76)
                if site["id"] == "hostel":
                    factor = 1.48 if evening else (0.92 if daytime else 0.82)
                elif site["id"] == "utilities":
                    factor = 1.28 if daytime else 0.88
                if weekend and site["id"] != "hostel":
                    factor *= 0.68 if daytime else 0.88
                trend = 1.16 if day > 58 and site["id"] == "engineering" else 1.0
                kwh = site["base"] * factor * trend + rng.normal(0, site["base"] * 0.055)
                spike = (day, hour, index) in {(75, 13, 2), (82, 17, 4), (88, 11, 1)}
                if spike:
                    kwh *= 2.25
                zero = day == 67 and hour in {9, 10} and index == 0
                if zero:
                    kwh = 0
                outage = (day == 55 and hour in {3, 4, 5} and index == 3) or (day == 84 and hour == 2 and index == 5)
                if outage:
                    continue
                timestamp = SAMPLE_START + timedelta(days=day, hours=hour)
                output.append({
                    "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
                    "location_id": site["id"],
                    "location_name": site["name"],
                    "kwh": round(max(0, float(kwh)), 2) if not zero else 0.0,
                    "interval_minutes": 60,
                    "quality": "flagged" if spike or zero else "valid",
                })
    return output