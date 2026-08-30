from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from health_dashboard.api.routes import router
from health_dashboard.db import init_db
from health_dashboard.services.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(title="Personal Health Dashboard", version="0.1.0", lifespan=lifespan)
app.include_router(router)
