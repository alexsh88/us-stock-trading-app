# Laptop Setup Guide
## US Stock Trading App — Full Environment Setup

> **How to use this file:**
> 1. Complete **Part 1** manually on your laptop (one-time installs, ~10 min).
> 2. Copy your `.env` file from the PC to the laptop (your API keys live here).
> 3. Open Claude Code on the laptop in this project folder and say **"go"**.
> 4. Claude will execute everything in **Part 2** automatically.

---

## Part 1 — Manual Prerequisites (you do this)

### 1.1 — Install Docker Desktop
Docker runs everything: Postgres, Redis, backend, Celery worker, Celery beat, frontend, Flower.
No Python or Node.js needs to be installed on your laptop directly.

1. Go to: https://www.docker.com/products/docker-desktop/
2. Download **Docker Desktop for Windows** (AMD64)
3. Install it — accept all defaults
4. After install, open Docker Desktop and wait for the whale icon in the taskbar to turn solid (engine running)
5. Open a terminal and verify:
   ```
   docker --version
   docker compose version
   ```
   Both should print version numbers. If `docker compose` fails, try `docker-compose` (older syntax).

> **Important:** Docker Desktop requires WSL 2 on Windows. The installer will prompt you to enable it if needed. Restart your laptop if asked.

### 1.2 — Install Git
1. Go to: https://git-scm.com/download/win
2. Download and install — accept all defaults
3. Verify:
   ```
   git --version
   ```

### 1.3 — Copy your `.env` file
The `.env` file holds all your API keys. It is **NOT** in the git repo (intentionally).

Options to transfer it from your PC to your laptop:
- USB drive
- AirDrop / shared folder
- Email it to yourself (delete after pasting)
- Copy-paste the contents manually

The file lives at the **project root** (same folder as `docker-compose.yml`):
```
C:\Users\gantz\dev\projects\us-stock-trading-app\.env
```

On the laptop, place it at whatever path you clone the repo to, e.g.:
```
C:\Users\<your-laptop-username>\dev\projects\us-stock-trading-app\.env
```

> Do this **before** saying "go" — without the `.env` file the containers will start but have no API keys.

### 1.4 — Choose where to clone
Decide where you want the project on your laptop. Recommended:
```
C:\Users\<your-laptop-username>\dev\projects\
```
Create that folder if it doesn't exist.

---

## Part 2 — Automated Setup (Claude does this when you say "go")

> Claude will execute the steps below in order. Each step is idempotent — safe to re-run if something fails.

### Step 1 — Clone the repository
```bash
cd C:\Users\<your-laptop-username>\dev\projects
git clone https://github.com/alexsh88/us-stock-trading-app.git
cd us-stock-trading-app
```

### Step 2 — Verify `.env` file is present
```bash
# Must exist before continuing
test -f .env && echo "OK" || echo "MISSING — copy .env from your PC first"
```
Claude will stop here if `.env` is missing.

### Step 3 — Build Docker images
This compiles the backend Python image and frontend Node image. Takes 3–5 minutes first time (downloads base images + installs all packages).
```bash
docker compose build --no-cache
```

### Step 4 — Start infrastructure (Postgres + Redis only)
Start the databases first so migrations can run against them.
```bash
docker compose up -d postgres redis
# Wait for health checks to pass
docker compose ps
```

### Step 5 — Run database migrations
Applies all 6 Alembic migrations in order:
- `001` — core tables (analysis_runs, trade_signals, signal_outcomes, positions, portfolios)
- `002` — backtest tables
- `003` — news_embeddings (pgvector 1536-dim)
- `004` — TimescaleDB hypertable + ohlcv_daily_candles CAGG + precomputed_technicals
- `005` — detected_patterns column on trade_signals
- `006` — scale_out columns on positions (scale_out_stage, target2_price, partial_realized_pnl, stop_loss_method)
```bash
docker compose run --rm backend alembic upgrade head
```

### Step 6 — Start all services
```bash
docker compose up -d
```
This starts: backend (port 8000), celery-worker, celery-beat, frontend (port 3002), flower (port 5555).

### Step 7 — Verify all containers are healthy
```bash
docker compose ps
```
All services should show `running` or `healthy`. If any show `exited`, check logs:
```bash
docker compose logs <service-name> --tail=50
```

### Step 8 — OHLCV backfill (populate market data + precomputed technicals)
Downloads 1 year of daily OHLCV data for the full universe (~150 tickers) and computes SMA20/SMA50/VWAP20/EMA150 into `precomputed_technicals`. This is what the technical node reads instead of hitting yfinance every run.

Takes ~3–5 minutes.
```bash
docker compose exec celery-worker celery -A app.tasks.celery_app call \
  app.tasks.market_data_ingest_tasks.run_ohlcv_backfill
```
Watch progress:
```bash
docker compose logs celery-worker -f --tail=20
```

### Step 9 — Trigger embedding backfill
Sends all `news_embeddings` rows to OpenAI `text-embedding-3-small` to fill their `embedding_vec` vectors. The synthesizer uses these for historical context injection. Runs in ~15 seconds per 500 rows.

Note: there won't be any rows yet on a fresh install (embeddings are populated as analysis runs are saved). This step is a no-op on day 1 and will be handled automatically by the nightly 6AM beat task going forward.
```bash
docker compose exec celery-worker celery -A app.tasks.celery_app call \
  app.tasks.embedding_tasks.run_embedding_backfill
```

### Step 10 — Verify the app is working
Open in browser:
- **Frontend dashboard:** http://localhost:3002
- **Backend API docs:** http://localhost:8000/docs
- **Flower (Celery monitor):** http://localhost:5555

Run a manual analysis to confirm the full pipeline works:
```bash
curl -X POST http://localhost:8000/api/v1/analysis/run \
  -H "Content-Type: application/json" \
  -d '{"mode": "swing", "top_n": 3}'
```
Then watch logs:
```bash
docker compose logs celery-worker -f
```
You should see the screener → technical → fundamental → sentiment → catalyst → risk_manager → synthesizer nodes firing in sequence.

---

## Daily Operation

### Starting the app (after laptop reboot)
```bash
cd C:\Users\<your-laptop-username>\dev\projects\us-stock-trading-app
docker compose up -d
```

### Stopping the app
```bash
docker compose down
```
Data is preserved in Docker volumes (`postgres_data`, `redis_data`) — stopping does not delete anything.

### Getting latest code updates from the PC
```bash
git pull origin master
docker compose build   # only needed if backend/Dockerfile or requirements.txt changed
docker compose up -d
# Run migrations if there are new ones:
docker compose run --rm backend alembic upgrade head
```

### Viewing logs
```bash
docker compose logs celery-worker -f    # Celery task logs
docker compose logs backend -f          # FastAPI logs
docker compose logs celery-beat -f      # Beat scheduler logs
```

---

## Service Map

| Service | URL | What it does |
|---------|-----|--------------|
| Frontend | http://localhost:3002 | Next.js dashboard |
| Backend API | http://localhost:8000 | FastAPI REST API |
| API Docs | http://localhost:8000/docs | Swagger UI |
| Flower | http://localhost:5555 | Celery task monitor |
| Postgres | localhost:5433 | Database (TimescaleDB + pgvector) |
| Redis | localhost:6379 | Cache + message broker |

---

## Scheduled Jobs (Celery Beat)

These run automatically once the app is up:

| Time | Job | What it does |
|------|-----|--------------|
| 9:00 AM ET (Mon–Fri) | Morning analysis | Full pipeline: screen → analyze → generate signals |
| Every 5 min (9–4 ET) | Position monitor | Check paper positions for SL/TP/trailing stop hits |
| 4:35 PM ET (Mon–Fri) | OHLCV ingest | Fetch today's candles, refresh precomputed_technicals |
| 5:30 PM ET (Mon–Fri) | Nightly backtest | Evaluate signal outcomes (T+1/T+5 returns) |
| 6:00 AM ET (daily) | Embedding backfill | Vectorize new news headlines via OpenAI |

---

## Troubleshooting

### "Cannot connect to the Docker daemon"
Docker Desktop is not running. Open it from the Start menu and wait for the engine to start.

### Postgres container exits immediately
Usually a volume permission issue on first run. Try:
```bash
docker compose down -v   # WARNING: deletes all data — only on fresh install
docker compose up -d postgres redis
docker compose run --rm backend alembic upgrade head
```

### Backend shows "relation does not exist"
Migrations haven't run yet. Run Step 5 again:
```bash
docker compose run --rm backend alembic upgrade head
```

### "No module named X" in celery-worker
The Docker image needs to be rebuilt after a `requirements.txt` change:
```bash
docker compose build backend
docker compose up -d
```

### Celery worker crashes with Redis error
Redis isn't healthy yet. Check:
```bash
docker compose ps redis
docker compose logs redis --tail=20
```

### precomputed_technicals is empty (technical node slow)
The OHLCV backfill hasn't run yet. Run Step 8 manually.

### Port already in use
Something else on your laptop is using port 8000, 3002, 5555, or 5433.
Either stop the conflicting service or change the port mapping in `docker-compose.yml`
(left side of `"HOST:CONTAINER"` — e.g. `"8001:8000"`).

---

## What is NOT transferred (fresh start)

| Data | Impact | Solution |
|------|--------|---------|
| Analysis run history | Previous signals not visible in dashboard | Runs fresh — new signals appear after first 9AM run |
| Paper trade positions | No open/closed positions | Opens fresh — any previous paper trades lost |
| news_embeddings rows | No embeddings until new runs create headlines | Nightly 6AM job handles it automatically |
| Redis cache | All caches cleared | Pipeline runs a bit slower first time (re-caches within minutes) |
| celerybeat-schedule | Beat schedule resets | Celery beat recreates it automatically |

> The market data (OHLCV) is rebuilt by Step 8 (OHLCV backfill) so the technical node works fully from day one.

---

## Optional: Transfer existing data from PC

If you want to preserve your signal history and paper positions, export the Postgres volume from your PC and import it on the laptop.

**On the PC — export:**
```bash
docker compose exec postgres pg_dump -U trading trading_db > trading_db_export.sql
```

**Copy** `trading_db_export.sql` to the laptop (USB, shared folder, etc.)

**On the laptop — import** (after Step 6, before Step 7):
```bash
docker compose exec -T postgres psql -U trading trading_db < trading_db_export.sql
```
Then skip Steps 8 and 9 (data is already there) and go straight to Step 10.
