"""
Job de APScheduler (Día 3, opcional): revisa leads en stage "nuevo" que
llevan más de N días analizados sin avanzar de etapa, y los loguea como
"requiere seguimiento".

Alcance deliberadamente chico para hoy: solo LOGUEA (no envía email, no
marca una columna nueva en la base de datos, no notifica a nadie). Un
mecanismo de notificación real es un alcance más grande para un día
futuro (Día 6, según el prompt de Día 3).

Este módulo no se inicia solo: hay que llamar start_scheduler() desde
algún lado (por ejemplo, un evento de startup de FastAPI en main.py) para
que efectivamente corra. Si no llegas a conectarlo hoy, no pasa nada: el
archivo existe pero no se ejecuta hasta que alguien lo importe y llame
start_scheduler().
"""

import logging
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from database.models import Lead, utcnow
from database.session import SessionLocal

logger = logging.getLogger(__name__)

# Días sin avanzar de "nuevo" antes de considerarlo estancado. Ajustable.
STALE_NUEVO_DAYS = 3


def check_stale_new_leads() -> None:
    """Loguea (WARNING) cada lead en 'nuevo' analizado hace más de STALE_NUEVO_DAYS días."""
    db = SessionLocal()
    try:
        cutoff = utcnow() - timedelta(days=STALE_NUEVO_DAYS)
        stale_leads = db.scalars(
            select(Lead).where(
                Lead.pipeline_stage == "nuevo",
                Lead.analyzed_at.is_not(None),
                Lead.analyzed_at < cutoff,
            )
        ).all()

        for lead in stale_leads:
            logger.warning(
                "Lead id=%s lleva más de %s días en 'nuevo' sin avanzar de etapa -- requiere seguimiento",
                lead.id, STALE_NUEVO_DAYS,
            )
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    """Arranca el scheduler en background. Llamar una sola vez, al iniciar la app."""
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(check_stale_new_leads, "interval", hours=24, id="check_stale_new_leads")
    scheduler.start()
    return scheduler