# -*- coding: utf-8 -*-
"""
Library Scanner - Modelli Database
Definisce tutte le tabelle del sistema.
"""
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Float, Text,
    ForeignKey, Index, BigInteger
)
from sqlalchemy.orm import relationship

from library_scanner.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class ScanDirectory(Base):
    """Directory configurate per la scansione."""
    __tablename__ = "scan_directories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    label = Column(String(100), nullable=False)                  # Nome descrittivo (es. "Movies")
    linux_path = Column(String(500), nullable=False, unique=True) # Path nel container Docker
    windows_path = Column(String(500), nullable=False)            # Path Windows per il client
    enabled = Column(Boolean, default=True, nullable=False)
    recursive = Column(Boolean, default=True, nullable=False)
    media_type = Column(String(20), default="movie")             # "movie" o "tvshow"
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    # Relazione con i video trovati in questa directory
    video_files = relationship("VideoFile", back_populates="scan_directory", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<ScanDirectory(id={self.id}, label='{self.label}', path='{self.linux_path}')>"


class VideoFile(Base):
    """File video individuati dal scanner."""
    __tablename__ = "video_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    directory_id = Column(Integer, ForeignKey("scan_directories.id", ondelete="CASCADE"), nullable=False)

    # Informazioni file
    filename = Column(String(500), nullable=False)
    linux_path = Column(String(1000), nullable=False, unique=True)  # Path completo nel container
    windows_path = Column(String(1000), nullable=False)              # Path completo per Windows
    relative_path = Column(String(1000), nullable=False)             # Path relativo alla scan_directory
    file_size = Column(BigInteger, default=0)                        # Dimensione in bytes
    file_modified = Column(DateTime, nullable=True)                  # Data modifica file

    # Stato sottotitoli
    has_italian_srt = Column(Boolean, default=False, nullable=False)      # Sottotitolo esterno .srt italiano
    has_italian_embedded = Column(Boolean, default=False, nullable=False)  # Sottotitolo embedded italiano
    has_any_italian_sub = Column(Boolean, default=False, nullable=False)   # Qualsiasi sottotitolo italiano
    subtitle_check_error = Column(Text, nullable=True)                     # Errore durante verifica ffprobe

    # Metadati
    media_type = Column(String(20), default="movie")  # "movie" o "tvshow"

    # Timestamp
    first_seen = Column(DateTime, default=_utcnow, nullable=False)   # Prima scansione
    last_scanned = Column(DateTime, default=_utcnow, nullable=False) # Ultima scansione
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    # Relazione
    scan_directory = relationship("ScanDirectory", back_populates="video_files")

    # Indici per query veloci
    __table_args__ = (
        Index("idx_video_no_subs", "has_any_italian_sub"),
        Index("idx_video_directory", "directory_id"),
        Index("idx_video_first_seen", "first_seen"),
        Index("idx_video_media_type", "media_type"),
    )

    @property
    def days_without_subs(self):
        """Calcola da quanti giorni il file e' senza sottotitoli."""
        if self.has_any_italian_sub:
            return 0
        delta = datetime.now(timezone.utc) - self.first_seen.replace(tzinfo=timezone.utc)
        return delta.days

    def __repr__(self):
        return f"<VideoFile(id={self.id}, name='{self.filename}', ita_sub={self.has_any_italian_sub})>"


class ScanLog(Base):
    """Log delle scansioni effettuate."""
    __tablename__ = "scan_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime, default=_utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="running")  # running, completed, failed, cancelled
    directories_scanned = Column(Integer, default=0)
    files_found = Column(Integer, default=0)
    files_new = Column(Integer, default=0)
    files_updated = Column(Integer, default=0)
    files_removed = Column(Integer, default=0)
    files_with_subs = Column(Integer, default=0)
    files_without_subs = Column(Integer, default=0)
    errors = Column(Integer, default=0)
    error_details = Column(Text, nullable=True)
    duration_seconds = Column(Float, nullable=True)

    def __repr__(self):
        return f"<ScanLog(id={self.id}, status='{self.status}', files={self.files_found})>"


class SystemConfig(Base):
    """Configurazione persistente del sistema (chiave-valore)."""
    __tablename__ = "system_config"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    def __repr__(self):
        return f"<SystemConfig(key='{self.key}', value='{self.value}')>"
