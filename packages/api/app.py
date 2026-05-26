from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from packages.api.db import engine
from packages.api.routers import data as data_router
from packages.api.routers import jobs as jobs_router
from packages.api.routers import projects as projects_router
from packages.api.settings import CORS_ORIGINS, ensure_dirs


def create_app() -> FastAPI:
    ensure_dirs()
    engine()  # init DB

    app = FastAPI(title="Hus-DataForge API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(projects_router.router)
    app.include_router(jobs_router.router)
    app.include_router(data_router.router)

    @app.get("/")
    def root():
        return {"service": "hus-dataforge-api", "version": "0.1.0"}

    @app.get("/healthz")
    def healthz():
        from packages.api.queue import get_redis

        redis_ok = True
        try:
            get_redis().ping()
        except Exception:
            redis_ok = False
        return {"ok": True, "redis": redis_ok}

    return app


app = create_app()
