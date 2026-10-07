"""
Scheduler embebido en el proceso del engine (M10, D87).

Vive dentro del mismo proceso de FastAPI. Se arranca en el `lifespan`
de `api.main` y se apaga en el shutdown. NO depende de cron del sistema
operativo ni de un servicio externo de scheduling.

Por qué `BackgroundScheduler` y no `AsyncIOScheduler`:
    Los jobs de M10 llaman a funciones SÍNCRONAS (`ejecutar_openaq`,
    `capturar_pronosticos`, `calcular_auditorias`), que usan httpx
    bloqueante y psycopg2. `AsyncIOScheduler` espera corrutinas;
    `BackgroundScheduler` las corre en su propio threadpool, sin
    bloquear el event loop de FastAPI. Un job que se cuelga no congela
    el resto de la API.

Por qué está encapsulado acá y no disperso:
    Un único lugar donde se crea, se arranca y se apaga el scheduler.
    `iniciar_scheduler()` y `detener_scheduler()` son idempotentes:
    llamarlos de más no rompe nada. La guarda contra
    `SCHEDULER_ENABLED=false` vive en `iniciar_scheduler()`, así el
    llamador (el `lifespan`) no tiene que saber de settings.
"""
from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

from database.config import settings
from scheduler import jobs

logger = logging.getLogger(__name__)

# Zona horaria de los cron triggers (D89). Colombia es UTC-5 fijo todo el
# año, sin DST, así que no hay sorpresas de cambio de hora. Se usa el
# nombre IANA para que los logs y las próximas corridas sean legibles.
ZONA_HORARIA = "America/Bogota"

# Instancia única por proceso. Se crea en `iniciar_scheduler`, se apaga
# en `detener_scheduler`. `None` significa "no arrancado".
_scheduler: Optional[BackgroundScheduler] = None


def _construir_scheduler() -> BackgroundScheduler:
    """Crea el `BackgroundScheduler` con los jobs registrados.

    `daemon=True`: los threads de los jobs no impiden que el proceso
    termine. `shutdown(wait=False)` corta los threads vivos; no hay
    motivo para esperar a que terminen (los jobs son idempotentes y se
    reprograman solos).

    Los jobs se registran desde `scheduler.jobs.registrar_jobs(sched)`,
    que es el único lugar donde se declaran los `CronTrigger` (D89).
    Separar la creación del scheduler del registro de jobs permite
    testear los jobs sin levantar el scheduler completo.
    """
    sched = BackgroundScheduler(
        timezone=ZONA_HORARIA,
        daemon=True,
    )
    jobs.registrar_jobs(sched)
    return sched


def iniciar_scheduler() -> None:
    """Arranca el scheduler.

    Idempotente: si `SCHEDULER_ENABLED=false`, no hace nada (útil para
    tests y debugging). Si ya está corriendo, no lo reinicia. Si ya se
    había detenido, lo vuelve a crear desde cero (por si el `lifespan`
    se ejecuta más de una vez en un mismo proceso).
    """
    global _scheduler

    if not settings.SCHEDULER_ENABLED:
        logger.info(
            "Scheduler deshabilitado (SCHEDULER_ENABLED=false). "
            "No se registra ningún job."
        )
        return

    if _scheduler is not None and _scheduler.running:
        logger.info("Scheduler ya estaba corriendo; no se reinicia.")
        return

    _scheduler = _construir_scheduler()
    _scheduler.start()
    _listar_jobs(_scheduler)


def detener_scheduler() -> None:
    """Apaga el scheduler.

    Idempotente: si nunca se arrancó (por `SCHEDULER_ENABLED=false` o
    porque el shutdown corre sin startup previo), no hace nada.
    """
    global _scheduler

    if _scheduler is None:
        return

    if _scheduler.running:
        # `wait=False`: no bloquea el shutdown de FastAPI esperando a que
        # termine una corrida en curso. Los jobs son idempotentes y, si
        # se corta uno a mitad, el siguiente ciclo lo retoma.
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler detenido.")

    _scheduler = None


def _listar_jobs(sched: BackgroundScheduler) -> None:
    """Loguea los jobs registrados con su próximo disparo.

    Es el punto de verificación del Bloque 1: en los logs del engine
    tiene que aparecer cada job con su `next_run_time` y su trigger.
    """
    jobs_activos = sched.get_jobs()
    if not jobs_activos:
        logger.warning("Scheduler arrancado SIN jobs registrados.")
        return

    logger.info("Scheduler arrancado con %d job(s):", len(jobs_activos))
    for j in jobs_activos:
        logger.info(
            "  - id=%s | próximo disparo: %s | trigger: %s",
            j.id, j.next_run_time, j.trigger,
        )