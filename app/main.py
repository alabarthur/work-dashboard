"""FastAPI application: serves the API and the static dashboard."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app import config
from app.api import router as api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Wire the real headless-Claude collector so the in-dashboard Refresh button
    # (and the 15-min schedule) actually pulls live data. Done at runtime, not
    # import time, so tests using TestClient without a lifespan stay hermetic.
    from collector.run import wire

    wire()
    yield


app = FastAPI(title="work-table", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def no_cache(request: Request, call_next):
    # Force browsers to revalidate JS/CSS/HTML on every load so a plain reload
    # always picks up the latest assets (no stale-tab surprises).
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache"
    return response


app.include_router(api_router)

# Serve the frontend at the root. html=True makes "/" return index.html.
app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True), name="frontend")
