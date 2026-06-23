# -*- coding: utf-8 -*-
"""
Library Scanner - Database
Setup SQLAlchemy con SQLite. Gestisce connessione, sessioni e inizializzazione.
"""
import logging
from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase

from library_scanner.config import Config

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base per tutti i modelli ORM."""
    pass


# Engine e SessionLocal vengono inizializzati in init_db()
_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        init_db()
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        init_db()
    return _SessionLocal


def init_db():
    """Inizializza il database: crea engine, tabelle e sessione factory."""
    global _engine, _SessionLocal

    Config.ensure_directories()
    db_url = f"sqlite:///{Config.DB_PATH}"
    logger.info(f"Inizializzazione database: {db_url}")

    _engine = create_engine(
        db_url,
        echo=False,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False}
    )

    # Abilita WAL mode e foreign keys per SQLite
    @event.listens_for(_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    # Importa models per registrare le tabelle
    from library_scanner import models  # noqa: F401
    Base.metadata.create_all(bind=_engine)

    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    logger.info("Database inizializzato con successo")


def run_migrations():
    """
    Migrazione additive-only: aggiunge le colonne mancanti a video_files
    e crea le nuove tabelle. Sicuro su DB esistente — non rimuove mai dati.
    """
    from sqlalchemy import text

    engine = get_engine()

    new_video_cols = [
        ("has_italian_text_sub",   "BOOLEAN NOT NULL DEFAULT 0"),
        ("has_italian_bitmap_sub", "BOOLEAN NOT NULL DEFAULT 0"),
        ("has_convertible_subs",   "BOOLEAN NOT NULL DEFAULT 0"),
        ("has_italian_convertible_subs", "BOOLEAN NOT NULL DEFAULT 0"),
        ("sub_formats_json",       "TEXT"),
        ("conversion_status",      "VARCHAR(20)"),
        ("conversion_error",       "TEXT"),
        ("conversion_done_at",     "DATETIME"),
        ("ocr_status",             "VARCHAR(20)"),
        ("ocr_error",              "TEXT"),
        ("ocr_done_at",            "DATETIME"),
    ]

    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(video_files)"))
        existing = {row[1] for row in result}

        added = []
        for col_name, col_def in new_video_cols:
            if col_name not in existing:
                conn.execute(text(
                    f"ALTER TABLE video_files ADD COLUMN {col_name} {col_def}"
                ))
                added.append(col_name)
                logger.info(f"Migrazione: aggiunta colonna video_files.{col_name}")

        conn.commit()

        # Backfill has_italian_convertible_subs dai sub_formats_json esistenti, così
        # il conteggio "convertibili" non crolla a zero in attesa della prossima scansione.
        if "has_italian_convertible_subs" in added:
            _backfill_italian_convertible(conn)

    # Crea nuove tabelle (no-op se già esistono)
    from library_scanner import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    logger.info("Migrazione database completata")


def _backfill_italian_convertible(conn):
    """
    Popola has_italian_convertible_subs sui file esistenti analizzando
    sub_formats_json (ASS/SSA con lingua italiana). Idempotente.
    """
    import json
    from sqlalchemy import text

    conv_codecs = Config.CONVERTIBLE_SUB_CODECS
    ita_codes = Config.ITALIAN_LANG_CODES

    rows = conn.execute(
        text("SELECT id, sub_formats_json FROM video_files "
             "WHERE sub_formats_json IS NOT NULL")
    ).fetchall()

    updated = 0
    for vid, raw in rows:
        try:
            streams = json.loads(raw) if raw else []
        except (ValueError, TypeError):
            continue
        if not isinstance(streams, list):
            continue
        has_ita_conv = any(
            isinstance(s, dict)
            and (s.get("codec") or "").lower() in conv_codecs
            and str(s.get("language", s.get("lang", "")) or "").lower().strip() in ita_codes
            for s in streams
        )
        if has_ita_conv:
            conn.execute(
                text("UPDATE video_files SET has_italian_convertible_subs = 1 "
                     "WHERE id = :id"),
                {"id": vid},
            )
            updated += 1

    conn.commit()
    logger.info(f"Backfill has_italian_convertible_subs: {updated} file aggiornati")


@contextmanager
def get_db() -> Session:
    """Context manager per ottenere una sessione database."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
