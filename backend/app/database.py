from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    from . import models  # noqa: F401
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Lightweight migration: add legacy single-attachment columns if missing
        result = await conn.execute(text("PRAGMA table_info(massnahmen)"))
        existing_cols = {row[1] for row in result.fetchall()}
        legacy_cols = {
            "anhang_dateiname": "TEXT",
            "anhang_pfad": "TEXT",
            "anhang_mimetype": "TEXT",
            "anhang_groesse": "INTEGER",
            "kategorie": "TEXT",
            "confidence": "INTEGER",
        }
        for col, col_type in legacy_cols.items():
            if col not in existing_cols:
                await conn.execute(text(f"ALTER TABLE massnahmen ADD COLUMN {col} {col_type}"))

        # Migrate legacy single-attachment data into the new multi-anhaenge table
        rows = await conn.execute(text("""
            SELECT m.id, m.anhang_dateiname, m.anhang_pfad, m.anhang_mimetype, m.anhang_groesse
            FROM massnahmen m
            LEFT JOIN anhaenge a ON a.massnahme_id = m.id AND a.pfad = m.anhang_pfad
            WHERE m.anhang_pfad IS NOT NULL AND a.id IS NULL
        """))
        for row in rows.fetchall():
            mid, name, pfad, mime, size = row
            await conn.execute(text("""
                INSERT INTO anhaenge (massnahme_id, dateiname, pfad, mimetype, groesse)
                VALUES (:mid, :name, :pfad, :mime, :size)
            """), {"mid": mid, "name": name, "pfad": pfad, "mime": mime, "size": size})
