"""
Jobs del scheduler (M10).

D88: los jobs llaman DIRECTO a las funciones de servicio
(`services/ingestion.py`, `services/pronosticos.py`,
`services/auditoria.py`, ...), no hacen HTTP a `/internal/*` ni a
`/api/admin/*` de sí mismos. Mismo proceso, mismo intérprete: la vuelta
de red y el `INTERNAL_API_TOKEN` son innecesarios.

Patrón de cada job real:
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

Bloques implementados:
    - Bloque 2: job_ingesta (cada hora al minuto :05).
    - Bloque 3 (este): job_pronosticos (04:10, D89).
    - Bloques 4 y 5: auditoría diaria y purgas.
"""
from __future__ import annotations

import logging
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from database.session import SessionLocal
from services.ingestion import (
    ResumenIngestion,
    ejecutar_aqicn,
    ejecutar_iboca,
    ejecutar_openaq,
    ejecutar_siata,
)
from services.pronosticos import capturar_pronosticos

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Zona horaria de los cron triggers (D89).
# ---------------------------------------------------------------------------
# Se declara acá (no en scheduler.py) porque es una propiedad de los
# jobs, no del scheduler en sí. El scheduler también la usa como default,
# pero el CronTrigger la pisa con la suya para que quede explícita.
ZONA_HORARIA = "America/Bogota"


# ---------------------------------------------------------------------------
# Bloque 2 — Job de ingesta repartida
# ---------------------------------------------------------------------------
def _fuentes_ingesta() -> tuple[tuple[str, Callable[[Session], ResumenIngestion]], ...]:
    """Tupla (nombre, función) de las 4 fuentes de ingesta.

    Se construye en CADA llamada (no es constante de módulo) para que
    los tests puedan mockear con `patch("scheduler.jobs.ejecutar_openaq")`:
    el patch reemplaza el atributo del módulo y esta función lo lee en
    tiempo de ejecución. Una constante de módulo hubiera capturado la
    referencia original antes del patch.
    """
    return (
        ("openaq", ejecutar_openaq),
        ("aqicn", ejecutar_aqicn),
        ("iboca", ejecutar_iboca),
        ("siata", ejecutar_siata),
    )


def _ejecutar_una_fuente(
    fuente: str,
    funcion: Callable[[Session], ResumenIngestion],
    db: Session,
    resumen: dict[str, dict],
) -> None:
    """Ejecuta la ingesta de UNA fuente y guarda el resultado en `resumen`.

    No propaga excepciones: el caller itera las 4 fuentes y quiere que
    una falle sin tumbar a las demás. El error se loguea con stack trace
    (logger.exception) y se registra como `{"error": str(exc)}`.
    """
    try:
        r = funcion(db)
        resumen[fuente] = r.a_dict()
        logger.info(
            "[scheduler] ingesta %s OK: %d estaciones nuevas, "
            "%d lecturas insertadas, %d duplicadas, %d invalidas",
            fuente,
            r.estaciones_nuevas,
            r.lecturas_insertadas,
            r.lecturas_duplicadas,
            r.lecturas_invalidas,
        )
    except Exception as exc:
        # Captura amplia a propósito: cualquier fallo de una fuente (red,
        # rate limit, error de parsing) se registra y se sigue con las
        # demás. Las excepciones específicas (OpenAQError, AQICNError,
        # IBOCAError, SIATAError) ya se manejan dentro de cada cliente y
        # devuelven un resultado parcial; esto es la red de seguridad por
        # si una excepción se escapa igual.
        resumen[fuente] = {"error": str(exc)}
        logger.exception("[scheduler] ingesta %s falló", fuente)


def ejecutar_ingesta(db: Session) -> dict[str, dict]:
    """Ejecuta la ingesta de las 4 fuentes en secuencia.

    Devuelve `{fuente: resumen_a_dict | {"error": str}}`.

    NUNCA lanza: el caller (job_ingesta) no tiene a quién avisarle, y el
    scheduler no debe morir por una fuente caída. Si las 4 fuentes
    fallan, el diccionario va a tener 4 entradas con `error`.

    Sobre la sesión compartida: las 4 fuentes usan la MISMA `db` y cada
    `ejecutar_*` hace su propio commit al final (ver
    `services/ingestion.ingerir`). No hay transacción larga compartida
    entre fuentes: si OpenAQ commitea y después AQICN falla a mitad de
    su transacción, el rollback de AQICN no afecta los datos ya
    persistidos de OpenAQ. Es el comportamiento que queremos (D15: los
    datos de una fuente no dependen de los de otra).
    """
    resumen: dict[str, dict] = {}
    for fuente, funcion in _fuentes_ingesta():
        _ejecutar_una_fuente(fuente, funcion, db, resumen)
    return resumen


def job_ingesta() -> None:
    """Wrapper del job de ingesta: abre y cierra la sesión de base.

    APScheduler lo invoca sin argumentos. Todo el trabajo real está en
    `ejecutar_ingesta`, que sí recibe `db` — así los tests pueden
    inyectar una sesión sin arrancar el scheduler.
    """
    db = SessionLocal()
    try:
        resumen = ejecutar_ingesta(db)
    finally:
        db.close()
    # Log resumen de la corrida completa, para que quede en los logs del
    # proceso aunque cada fuente ya haya logueado su resultado.
    ok = [f for f, r in resumen.items() if "error" not in r]
    fallidas = [f for f, r in resumen.items() if "error" in r]
    logger.info(
        "[scheduler] ingesta completa: %d/%d fuentes OK (%s); fallidas: %s",
        len(ok), len(resumen), ", ".join(ok) or "ninguna",
        ", ".join(fallidas) or "ninguna",
    )


# ---------------------------------------------------------------------------
# Bloque 3 — Job de captura diaria de pronósticos (D62, D89)
# ---------------------------------------------------------------------------
def job_pronosticos() -> None:
    """Wrapper del job de captura diaria de pronósticos (Open-Meteo).

    `capturar_pronosticos` es idempotente por diseño (D62): la primera
    captura del día gana. Si el job corre y ya existen los pronósticos
    del día, no inserta nada nuevo (`pronosticos_insertados=0`,
    `pronosticos_ya_existian>0`). Por eso alcanza con UNA corrida
    diaria, a diferencia de la ingesta que se reparte durante el día.

    Nunca lanza: el scheduler no tiene a quién avisarle. Los errores de
    red/config de Open-Meteo se atrapan y loguean con stack trace.
    """
    db = SessionLocal()
    try:
        r = capturar_pronosticos(db)
        logger.info(
            "[scheduler] captura de pronósticos OK: insertados=%d, "
            "ya_existian=%d, auditorías_creadas=%d, requests=%d, "
            "por_horizonte=%s",
            r.pronosticos_insertados,
            r.pronosticos_ya_existian,
            r.auditorias_creadas,
            r.requests,
            r.por_horizonte,
        )
    except Exception:
        logger.exception("[scheduler] captura de pronósticos falló")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Registro de jobs
# ---------------------------------------------------------------------------
def registrar_jobs(sched: BackgroundScheduler) -> None:
    """Registra todos los jobs del scheduler.

    Cada `add_job` lleva `replace_existing=True`, `max_instances=1` y un
    `misfire_grace_time` razonable. El `id` es el que aparece en los logs
    y en `sched.get_jobs()`, útil para verificar la programación.

    Programación vigente (D89, hora local `America/Bogota`):
        - ingesta:      cada hora, minuto :05
        - pronósticos:  04:10
    """
    sched.add_job(
        job_ingesta,
        trigger="cron",
        hour="*",
        minute=5,
        timezone=ZONA_HORARIA,
        id="ingesta",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=600,
    )
    sched.add_job(
        job_pronosticos,
        trigger="cron",
        hour=4,
        minute=10,
        timezone=ZONA_HORARIA,
        id="pronosticos",
        replace_existing=True,
        max_instances=1,
        # 1 hora de gracia: si el proceso se reinicia y la corrida de las
        # 04:10 se atrasa menos de 60 min, se recupera; si más, se saltea
        # y espera al día siguiente.
        misfire_grace_time=3600,
    )