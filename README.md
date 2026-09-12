# Smart Blood Donation Management System (SBDMS) - Backend

Production-ready, modular FastAPI backend for SBDMS with PostgreSQL (Supabase) and serverless ASGI deployment configuration for Vercel.

## Tech Stack
- **Framework:** Python 3.11+, FastAPI, Pydantic v2
- **ORM & Database:** SQLAlchemy 2.0 with PostgreSQL on Supabase Transaction Pooler (Port 6543)
- **Authentication:** JWT (15-minute access token, 7-day refresh token), Passwords hashed with bcrypt (cost 12)
- **Deployment:** Vercel ASGI (`main.py` + `vercel.json`)

---

## Directory Structure

```
backend/
├── app/
│   ├── api/
│   │   ├── deps.py             # Auth & RBAC (DONOR, RECIPIENT, HOSPITAL_ADMIN, SYSTEM_ADMIN)
│   │   └── v1/
│   │       ├── auth.py         # /api/v1/auth (/register, /login, /refresh, /me)
│   │       ├── donors.py       # /api/v1/donors (/profile, /availability, /eligibility, /medical-info, /history)
│   │       ├── requests.py     # /api/v1/requests (/, /emergency, /{id}, /{id}/matches)
│   │       ├── matches.py      # /api/v1/matches ({id}/respond, {id}/contact - Contact Reveal Safeguard)
│   │       ├── inventory.py    # /api/v1/inventory (/, /transaction, /scan-expiries)
│   │       ├── appointments.py # /api/v1/appointments (/, /my-appointments, /{id}/status)
│   │       ├── events.py       # /api/v1/events (/, /{id}/register, /{id}/checkin)
│   │       ├── notices.py      # /api/v1/campaign-notices (Public listings & Admin creation)
│   │       ├── logs.py         # /api/v1/system-logs (System Admin audit trail)
│   │       └── communications.py# /api/v1/communications (In-app match chat)
│   ├── core/
│   │   ├── config.py           # Pydantic Settings
│   │   ├── database.py         # Supabase connection pooler engine & session factory
│   │   ├── enums.py            # All 14 system enums
│   │   └── security.py         # Bcrypt (cost 12) & JWT helper utilities
│   ├── models/                 # SQLAlchemy 2.0 models (16 tables)
│   ├── schemas/                # Pydantic v2 validation models
│   └── services/
│       ├── compatibility.py    # Blood Compatibility Matrix
│       ├── eligibility.py      # Automated Donor Eligibility Validator (age 18-65, weight >=50, Hb >=12.5, cooldown 90d/14d)
│       ├── matching.py         # Haversine distance, progressive radius expansion (10km->25km->50km), Composite scoring
│       ├── inventory.py        # Stock threshold ratios & 72-hour expiry sweep
│       └── audit.py            # Audit logger helper
├── main.py                     # Root ASGI app with CORS configuration
├── requirements.txt            # Python dependencies
├── vercel.json                 # Vercel ASGI configuration
├── .env.example                # Environment variables template
└── tests/
    └── test_api.py             # Pytest automated test suite
```

---

## Local Setup & Execution

1. **Install Dependencies:**
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

2. **Environment Variables:**
   Create `.env` inside `backend/`:
   ```env
   DATABASE_URL=postgresql+psycopg2://postgres.fgvdkpuvdedenwmdjhym:keukonokajkorena@aws-0-ap-south-1.pooler.supabase.com:6543/postgres
   JWT_SECRET=your-secure-random-secret-key-here
   JWT_ALGORITHM=HS256
   ACCESS_TOKEN_EXPIRE_MINUTES=15
   REFRESH_TOKEN_EXPIRE_DAYS=7
   ENVIRONMENT=development
   ```

3. **Start Development Server:**
   ```bash
   uvicorn main:app --reload --port 8000
   ```
   - Interactive Swagger API Documentation: [http://localhost:8000/docs](http://localhost:8000/docs)
   - ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)

4. **Run Automated Test Suite:**
   ```bash
   python -m pytest backend/tests/test_api.py -v
   ```
