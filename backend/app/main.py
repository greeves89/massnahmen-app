from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .database import SessionLocal, init_db
from .models import User
from .routes import analyse, auth, dashboard, massnahmen, settings as settings_routes
from .security import hash_password


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await _ensure_initial_admin()
    yield


async def _ensure_initial_admin() -> None:
    """Create the initial admin user on first start (if no users exist)."""
    async with SessionLocal() as session:
        result = await session.execute(select(User).limit(1))
        if result.scalar_one_or_none():
            return
        admin = User(
            email=settings.initial_admin_email.strip().lower(),
            name=settings.initial_admin_name,
            password_hash=hash_password(settings.initial_admin_password),
        )
        session.add(admin)
        await session.commit()
        print(f"[init] Initial admin created: {admin.email}")


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie=settings.session_cookie_name,
    max_age=settings.session_max_age_seconds,
    https_only=settings.cookie_secure,
    same_site="lax",
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(massnahmen.router)
app.include_router(settings_routes.router)
app.include_router(analyse.router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
