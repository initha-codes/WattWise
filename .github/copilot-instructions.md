# WattWise Project Notes

- Frontend: React, TypeScript, Vite, Tailwind CSS, React Router, Recharts, and Lucide React.
- Backend: FastAPI with Pandas/NumPy analytics and SQLite persistence.
- Start the API with `uvicorn backend.app.main:app --reload --port 8000` and the UI with `npm run dev`.
- The seeded campus dataset is synthetic, deterministic, UTC-based, and uses 60-minute interval kWh.
- Keep missing readings distinct from zero, and do not claim normalized efficiency or realized savings without supporting denominators and verification.
- Run `npm run build` and `python -m pytest` when changing application behavior.