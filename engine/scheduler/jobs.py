"""
Jobs del scheduler (M10).

D88: los jobs llaman DIRECTO a las funciones de servicio
(`services/ingestion.py`, `services/pronosticos.py`,
`services/auditoria.py`, ...), no hacen HTTP a `/internal/*` ni a
`/api/admin/*` de sí mismos. Mismo proceso, mismo intérprete: la vuelta
de red y el `INTERNAL_API_TOKEN` son innecesarios.

Bloque 1: solo un job de prueba que loguea. Los jobs reales se agregan
en los bloques 2 (ingesta), 3 (pronósticos), 4 (auditoría) y 5 (purgas).
El job de prueba se retira cuando entre el primero de ellos.

Cada job real va a seguir este patrón:
    def job_xxx() -> None:
        db = SessionLocal()
        try:
            resumen = funcion_de_servicio(db)
            logger.info("[scheduler] xxx: %s", resumen.a_dict())
        except Exception:
            # No dejar que una excepción tumbe el thread del scheduler:
            # se loguea y se espera al próximo ciclo.
            logger.exception("[scheduler] xxx falló")
        finally:
            db.close()
"""
from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Job de prueba (Bloque 1)
# ---------------------------------------------------------------------------
def job_de_prueba() -> None:
    """Job no-op que loguea la hora.

    Se retira en el Bloque 2 cuando entre el primer job real. Sirve para
    verificar en los logs del engine que el scheduler corre y dispara a
    horario. No toca la base ni la red.
    """
    logger.info(
        "[scheduler] job_de_prueba ejecutado a las %s",
        datetime.now().isoformat(timespec="seconds"),
    )


# ---------------------------------------------------------------------------
# Registro de jobs
# ---------------------------------------------------------------------------
def registrar_jobs(sched: BackgroundScheduler) -> None:
    """Registra todos los jobs del scheduler.

    Bloque 1: solo el job de prueba (intervalo de 5 min). En los bloques
    siguientes se reemplaza por los `CronTrigger` de D89 (hora local
    America/Bogota):
        - ingesta:      cada hora al minuto :05
        - pronósticos:  04:10
        - auditoría:    04:40
        - purgas:       05:10
    Cada job va con `max_instances=1` y `misfire_grace_time` razonable,
    para que no se acumulen corridas si el proceso estuvo caído un rato.
    """
    sched.add_job(
        job_de_prueba,
        trigger="interval",
        minutes=5,
        id="prueba_m10",
        replace_existing=True,
        max_instances=1,
        # Si el proceso estuvo caído y "se perdió" el horario programado,
        # todavía se corre si pasaron menos de 60s desde el horario
        # original. Con más de eso, se descarta y se espera al próximo.
        misfire_grace_time=60,
    )