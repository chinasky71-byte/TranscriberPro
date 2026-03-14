# -*- coding: utf-8 -*-
"""
Library Scanner - Scheduler
Gestisce scansioni automatiche periodiche e orari silenziosi.
"""
import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from library_scanner.config import Config
from library_scanner.scanner import get_scanner

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler = None


def _is_quiet_hour() -> bool:
    """Verifica se siamo in un orario silenzioso."""
    start = Config.QUIET_HOURS_START
    end = Config.QUIET_HOURS_END
    if start < 0 or end < 0:
        return False  # Orari silenziosi disabilitati

    current_hour = datetime.now().hour
    if start <= end:
        return start <= current_hour < end
    else:
        # Intervallo che attraversa la mezzanotte (es. 23-06)
        return current_hour >= start or current_hour < end


def _scheduled_scan():
    """Esegue una scansione schedulata."""
    if _is_quiet_hour():
        logger.info("Scansione schedulata saltata: orario silenzioso")
        return

    scanner = get_scanner()
    if scanner.is_running:
        logger.info("Scansione schedulata saltata: scansione gia' in corso")
        return

    logger.info("Avvio scansione schedulata automatica")
    scanner.run_full_scan()


def start_scheduler():
    """Avvia lo scheduler per scansioni automatiche."""
    global _scheduler

    if _scheduler is not None:
        logger.warning("Scheduler gia' avviato")
        return

    interval_hours = Config.SCAN_INTERVAL_HOURS
    if interval_hours <= 0:
        logger.info("Scheduler disabilitato (intervallo <= 0)")
        return

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _scheduled_scan,
        trigger=IntervalTrigger(hours=interval_hours),
        id="library_scan",
        name="Scansione libreria automatica",
        replace_existing=True,
        max_instances=1
    )
    _scheduler.start()
    logger.info(f"Scheduler avviato: scansione ogni {interval_hours} ore")


def stop_scheduler():
    """Ferma lo scheduler."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler fermato")


def get_scheduler_status() -> dict:
    """Restituisce lo stato corrente dello scheduler."""
    if _scheduler is None:
        return {"running": False, "interval_hours": Config.SCAN_INTERVAL_HOURS}

    jobs = _scheduler.get_jobs()
    next_run = None
    if jobs:
        next_run = jobs[0].next_run_time.isoformat() if jobs[0].next_run_time else None

    return {
        "running": _scheduler.running,
        "interval_hours": Config.SCAN_INTERVAL_HOURS,
        "next_scan": next_run,
        "quiet_hours": {
            "enabled": Config.QUIET_HOURS_START >= 0,
            "start": Config.QUIET_HOURS_START,
            "end": Config.QUIET_HOURS_END
        }
    }
