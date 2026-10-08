"""
Jobs del scheduler (M10).

D88: los jobs llaman DIRECTO a las funciones de servicio
(`services/ingestion.py`, `services/pronosticos.py`,
`services/auditoria.py`, ...), no hacen HTTP a `/internal/*` ni a
`/api/admin/*` de sí mismos. Mismo proceso, mismo intérprete: la vuelta
de red y el `INTERNAL_API_TOKEN` son innecesarios.

Las purgas (Bloque 5) son la excepción a la regla D88: no hay una función
de servicio que llamar, así que el job ejecuta el DELETE directo. Son dos
consultas SQL; no ameritan un módulo `services/purgas.py`. Si en el
futuro crece, se extrae.

Patrón de cada job real:
    def job_xxx() -> None:
        db = SessionLocal()
        try:
            resumen = funcion_de_servicio(db)   # o el DELETE directo
            logger.info("[scheduler] xxx: %s", resumen)
        except Exception:
            # No dejar que una excepción tumbe el thread del scheduler:
            # se loguea y se espera al próximo ciclo.
            logger.exception("[scheduler] xxx falló")
        finally:
            db.close()

Bloques implementados:
    - Bloque 2: job_ingesta (cada hora al minuto :05).
    - Bloque 3: job_pronosticos (04:10, D89).
    - Bloque 4: job_auditoria (04:40, D89).
    - Bloque 5 (este): job_purgas + job_purgas_sesiones (05:10, D89).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import delete
from sqlalchemy.orm import Session

from database.config import settings
from database.models import Lectura, SesionRefresh
from database.session import SessionLocal
from services.auditoria import calcular_auditorias
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
# Bloque 4 — Job de auditoría diaria (D66, D69, D89)
# ---------------------------------------------------------------------------
def job_auditoria() -> None:
    """Wrapper del job de auditoría diaria.

    `calcular_auditorias` resuelve las auditorías pendientes cuyo día
    objetivo ya terminó (hora local Colombia). Es idempotente: la
    segunda corrida seguida no toca nada, porque las filas ya procesadas
    dejaron de ser 'pendiente'. Correr esto todos los días es lo que
    hace que D69 se cumpla: la cifra pública de error se acumula sola,
    sin que nadie tenga que acordarse de dispararla a mano.

    Nunca lanza: el scheduler no tiene a quién avisarle.
    """
    db = SessionLocal()
    try:
        r = calcular_auditorias(db)
        logger.info(
            "[scheduler] auditoría OK: resueltas=%d, sin_datos=%d, "
            "no_auditables=%d, todavia_no_vencen=%d, "
            "horas_insuficientes=%d, pendientes_antes=%d",
            r.resueltas,
            r.sin_datos,
            r.no_auditables,
            r.todavia_no_vencen,
            r.pendientes_por_horas_insuficientes,
            r.pendientes_antes,
        )
    except Exception:
        logger.exception("[scheduler] auditoría falló")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Bloque 5 — Jobs de purga (D90, D91)
# ---------------------------------------------------------------------------
def job_purgas() -> None:
    """Purga lecturas detalladas más allá de su retención (D15, D90).

    Borra filas de `lecturas` con `medido_en` anterior a
    `now - settings.RETENCION_LECTURAS_DIAS días`. Auditorías y
    comparaciones agregadas se conservan siempre (D15): no tienen FK
    hacia `lecturas`, así que borrar lecturas viejas no las rompe.

    Idempotente: correrlo dos veces seguidas la segunda no borra nada
    (ya no hay filas viejas).

    Nunca lanza: el scheduler no tiene a quién avisarle.
    """
    db = SessionLocal()
    try:
        ahora = datetime.now(timezone.utc)
        corte = ahora - timedelta(days=settings.RETENCION_LECTURAS_DIAS)
        resultado = db.execute(
            delete(Lectura).where(Lectura.medido_en < corte)
        )
        db.commit()
        filas_borradas = resultado.rowcount or 0
        logger.info(
            "[scheduler] purga de lecturas OK: %d filas borradas "
            "(medido_en < %s, retención %d días)",
            filas_borradas, corte.isoformat(), settings.RETENCION_LECTURAS_DIAS,
        )
    except Exception:
        db.rollback()
        logger.exception("[scheduler] purga de lecturas falló")
    finally:
        db.close()


def job_purgas_sesiones() -> None:
    """Purga sesiones de refresh vencidas o revocadas (D91).

    Dos borrados en una sola transacción:
      1. Sesiones VENCIDAS (`expira_en < now()`): se borran de inmediato.
         Ya no sirven para nada.
      2. Sesiones REVOCADAS con `revocada_en` anterior a
         `now - settings.RETENCION_SESIONES_REVOCADAS_HORAS`: se
         conservan un tiempo por si hace falta revisar un log de abuso
         poco después de la revocación.

    Idempotente: correrlo dos veces seguidas la segunda no borra nada.

    Nunca lanza: el scheduler no tiene a quién avisarle.
    """
    db = SessionLocal()
    try:
        ahora = datetime.now(timezone.utc)
        # 1. Vencidas: se borran de inmediato.
        r_vencidas = db.execute(
            delete(SesionRefresh).where(SesionRefresh.expira_en < ahora)
        )
        vencidas_borradas = r_vencidas.rowcount or 0
        # 2. Revocadas con período de gracia.
        corte_revocadas = ahora - timedelta(
            hours=settings.RETENCION_SESIONES_REVOCADAS_HORAS
        )
        r_revocadas = db.execute(
            delete(SesionRefresh).where(
                SesionRefresh.revocada_en.is_not(None),
                SesionRefresh.revocada_en < corte_revocadas,
            )
        )
        revocadas_borradas = r_revocadas.rowcount or 0
        db.commit()
        logger.info(
            "[scheduler] purga de sesiones OK: %d vencidas + %d revocadas "
            "(gracia %d h) = %d filas borradas",
            vencidas_borradas, revocadas_borradas,
            settings.RETENCION_SESIONES_REVOCADAS_HORAS,
            vencidas_borradas + revocadas_borradas,
        )
    except Exception:
        db.rollback()
        logger.exception("[scheduler] purga de sesiones falló")
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
        - ingesta:            cada hora, minuto :05
        - pronósticos:        04:10
        - auditoría:          04:40
        - purgas (lecturas):  05:10
        - purgas (sesiones):  05:10

    El orden de la madrugada es pronosticos -> auditoria -> purgas: la
    auditoría audita el día que YA CERRÓ, y las purgas corren al final
    para no borrar lecturas que la auditoría podría necesitar. Aunque en
    la práctica las purgas solo borran lo muy viejo (60 días), el orden
    correcto es dejar que la auditoría use las lecturas primero.
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
    sched.add_job(
        job_auditoria,
        trigger="cron",
        hour=4,
        minute=40,
        timezone=ZONA_HORARIA,
        id="auditoria",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    sched.add_job(
        job_purgas,
        trigger="cron",
        hour=5,
        minute=10,
        timezone=ZONA_HORARIA,
        id="purgas",
        replace_existing=True,
        max_instances=1,
        # 30 min de gracia: es la última corrida de la ventana de la
        # madrugada, no necesita más margen que eso.
        misfire_grace_time=1800,
    )
    sched.add_job(
        job_purgas_sesiones,
        trigger="cron",
        hour=5,
        minute=10,
        timezone=ZONA_HORARIA,
        id="purgas_sesiones",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=1800,
    )