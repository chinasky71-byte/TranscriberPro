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
