"""AgentEvalOps FastAPI application.

The app is assembled from focused routers. In development the API can also
serve the built React SPA from ``frontend/dist`` so a single container runs the
whole product. Health probes stay public; all mutations are role-gated.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import admin, agents, analytics, benchmarks, experiments, providers, releases, system, trials
from .config import get_settings
from .database import SessionLocal, init_db
from .security import resolve_role
from .seed import seed

log = logging.getLogger("agentevalops")
ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "frontend" / "dist"


def _validate_presented_key(x_api_key: str | None = Header(default=None)):
    """Reject an explicitly invalid key on every route.

    Keyless access is governed by ``AGENTEVALOPS_ALLOW_ANONYMOUS`` on the
    endpoints that actually require a role, keeping liveness probes simple.
    """
    if x_api_key is not None:
        resolve_role(x_api_key)


def _initialize():
    init_db()
    db = SessionLocal()
    try:
        seed(db)
    except RuntimeError as e:  # immutable benchmark drift; surface without a crash loop
        log.error("Seed refused: %s", e)
    except Exception:  # pragma: no cover - defensive startup logging
        log.exception("Initialization failed")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _initialize()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AgentEvalOps",
        version=settings.version,
        description=(
            "Continuous evaluation and release qualification for AI agents. "
            "Offline deterministic baselines and real provider adapters share one harness; "
            "qualification is not a production deployment authorization."
        ),
        lifespan=lifespan,
        dependencies=[Depends(_validate_presented_key)],
        docs_url="/docs",
        redoc_url="/redoc",
    )
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Total-Count"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    for router in (system.router, benchmarks.router, agents.router, providers.router,
                   experiments.router, trials.router, analytics.router, releases.router,
                   admin.router):
        app.include_router(router)

    assets = DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        target = DIST / "index.html"
        if target.is_file():
            return FileResponse(target)
        return JSONResponse({
            "app": settings.app_name, "version": settings.version,
            "message": "API is running. Build the frontend (`cd frontend && npm run build`) or use the Vite dev server.",
            "docs": "/docs", "health": "/health",
        })

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        reserved = ("api/", "health", "ready", "docs", "redoc", "openapi.json")
        if full_path.startswith(reserved):
            raise HTTPException(404, "Not found")
        target = DIST / "index.html"
        if target.is_file():
            return FileResponse(target)
        raise HTTPException(404, "Frontend build not found")

    app.state.initialize = _initialize
    return app


app = create_app()

# Importing the module (e.g. in tests without lifespan) still yields a usable,
# seeded database. This is idempotent and safe to repeat.
_initialize()
