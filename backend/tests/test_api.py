from fastapi.testclient import TestClient

from backend.app import database
from backend.app.main import app


def test_api_health_consumption_and_csv_preview(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "wattwise-test.db")
    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        overview = client.get("/api/overview?days=7").json()
        assert overview["total_kwh"] > 0
        readings = client.get("/api/consumption?days=7&aggregation=day").json()
        assert readings["aggregation"] == "day"
        assert readings["series"]
        response = client.post("/api/import/preview", files={"file": ("sample.csv", "timestamp,location_id,kwh\n2026-11-01T09:00:00Z,admin,24.5\n2026-11-01T10:00:00Z,unknown,12\n", "text/csv")})
        assert response.status_code == 200
        assert response.json()["valid_count"] == 1
        assert response.json()["rejected_count"] == 1
        events = client.get("/api/anomalies").json()
        assert events
        event_id = events[0]["event_id"]
        updated = client.patch(f"/api/anomalies/{event_id}", json={"status": "Investigating", "note": "Verified API persistence"})
        assert updated.status_code == 200
        assert client.get(f"/api/anomalies/{event_id}").json()["status"] == "Investigating"
        recommendations = client.get("/api/recommendations").json()
        assert recommendations
        recommendation_id = recommendations[0]["recommendation_id"]
        assert client.patch(f"/api/recommendations/{recommendation_id}", json={"status": "Accepted"}).status_code == 200
        assert client.get("/api/recommendations").json()[0]["status"] == "Accepted"
        payload = {"readings": [{"timestamp": "2026-11-01T09:00:00Z", "location_id": "admin", "kwh": 24.5, "interval_minutes": 60}]}
        assert client.post("/api/import/confirm", json=payload).json()["inserted"] == 1
        assert client.post("/api/import/confirm", json=payload).json()["inserted"] == 0
        assert client.get("/api/consumption?days=1").json()["readings"][0]["kwh"] == 24.5