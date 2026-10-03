"""
Capa de ingestión: escribe en Postgres lo que descargaron los clientes.
Separación de responsabilidades (por qué esto NO vive en los clientes):
  - Un CLIENTE (sources/openaq.py, sources/aqicn.py, sources/iboca.py,
    sources/siata.py) sabe hablar con UNA fuente y traducir su formato a
    `sources.tipos`. No conoce la base de datos.
  - Este SERVICIO sabe hablar con la base de datos. No conoce ninguna
    API: solo recibe un `ResultadoDescarga`.

Dos operaciones, dos estrategias distintas:
  ESTACIONES -> UPSERT. Si (fuente, id_externo) ya existe, se actualiza;
    si no, se inserta. Lo resuelve la base en una operación atómica, sin
    hueco entre "mirar si existe" y "escribir".
  LECTURAS -> INSERT ... ON CONFLICT DO NOTHING. Append-only: solo se
    agregan, nunca se corrigen ni se borran; son el registro histórico de
    qué dijo cada fuente y cuándo.

Pronósticos (M5b): los persistía `_upsert_pronosticos` a partir del
`forecast` de AQICN. Retirado en M5c (D58): AQICN solo entregaba días
pasados para Colombia (D57). Los pronósticos de Open-Meteo se manejan en
su propio servicio (services/pronosticos.py, M5c).

Toda la ingestión de una fuente ocurre en UNA transacción.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from database.models import (
    CONTAMINANTES,
    FUENTES,
    Estacion,
    Lectura,
    utcnow,
)
from sources.aqicn import ClienteAQICN
from sources.iboca import ClienteIBOCA
from sources.openaq import ClienteOpenAQ
from sources.siata import ClienteSIATA
from sources.tipos import EstacionNormalizada, ResultadoDescarga

logger = logging.getLogger(__name__)

LONGITUD_MAX_UNIDAD = 20  # columna lecturas.unidad = String(20)


@dataclass
class ResumenIngestion:
    """Qué pasó en una ingestión. Es lo que devuelven los endpoints internos."""
    fuente: str
    estaciones_nuevas: int = 0
    estaciones_actualizadas: int = 0
    estaciones_sin_cambios: int = 0
    estaciones_sin_actividad: int = 0
    lecturas_insertadas: int = 0
    lecturas_duplicadas: int = 0
    lecturas_invalidas: int = 0
    estaciones_fallidas: list[dict[str, str]] = field(default_factory=list)
    estaciones_descartadas: dict[str, int] = field(default_factory=dict)
    abortada: str | None = None

    def a_dict(self) -> dict[str, Any]:
        return {
            "fuente": self.fuente,
            "estaciones_nuevas": self.estaciones_nuevas,
            "estaciones_actualizadas": self.estaciones_actualizadas,
            "estaciones_sin_cambios": self.estaciones_sin_cambios,
            "estaciones_sin_actividad": self.estaciones_sin_actividad,
            "lecturas_insertadas": self.lecturas_insertadas,
            "lecturas_duplicadas": self.lecturas_duplicadas,
            "lecturas_invalidas": self.lecturas_invalidas,
            "estaciones_fallidas": self.estaciones_fallidas,
            "estaciones_descartadas": self.estaciones_descartadas,
            "abortada": self.abortada,
        }


def _cambio(fila: Any, e: EstacionNormalizada) -> bool:
    """¿La estación ya guardada difiere de la que trajo la fuente?"""
    return (
        fila.nombre != e.nombre
        or fila.activa != e.activa
        or not math.isclose(fila.latitud, e.latitud, abs_tol=1e-9)
        or not math.isclose(fila.longitud, e.longitud, abs_tol=1e-9)
    )


def _upsert_estaciones(
    db: Session, fuente: str, estaciones: list[EstacionNormalizada], ahora: datetime,
    resumen: ResumenIngestion,
) -> dict[str, int]:
    """Inserta o actualiza las estaciones. Devuelve {id_externo: id en nuestra base}."""
    unicas = list({e.id_externo: e for e in estaciones}.values())
    if not unicas:
        return {}
    existentes = {
        f.id_externo: f
        for f in db.execute(
            select(Estacion.id_externo, Estacion.nombre, Estacion.latitud,
                   Estacion.longitud, Estacion.activa)
            .where(Estacion.fuente == fuente,
                   Estacion.id_externo.in_([e.id_externo for e in unicas]))
        )
    }
    for e in unicas:
        fila = existentes.get(e.id_externo)
        if fila is None:
            resumen.estaciones_nuevas += 1
        elif _cambio(fila, e):
            resumen.estaciones_actualizadas += 1
        else:
            resumen.estaciones_sin_cambios += 1
        if not e.activa:
            resumen.estaciones_sin_actividad += 1
    filas = [
        {"fuente": fuente, "id_externo": e.id_externo, "nombre": e.nombre,
         "latitud": e.latitud, "longitud": e.longitud, "activa": e.activa,
         "primera_vez_vista": ahora, "ultima_vez_vista": ahora}
        for e in unicas
    ]
    stmt = insert(Estacion).values(filas)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Estacion.fuente, Estacion.id_externo],
        set_={
            "nombre": stmt.excluded.nombre,
            "latitud": stmt.excluded.latitud,
            "longitud": stmt.excluded.longitud,
            "activa": stmt.excluded.activa,
            "ultima_vez_vista": stmt.excluded.ultima_vez_vista,
        },
    ).returning(Estacion.id, Estacion.id_externo)
    return {r.id_externo: r.id for r in db.execute(stmt)}


def _lectura_valida(contaminante: str, valor: Any, unidad: str, medido_en: Any) -> bool:
    """Guard clause por lectura: un dato mal formado no tumba el lote entero."""
    return (
        contaminante in CONTAMINANTES
        and isinstance(valor, (int, float)) and math.isfinite(valor)
        and bool(unidad) and len(unidad) <= LONGITUD_MAX_UNIDAD
        and isinstance(medido_en, datetime) and medido_en.tzinfo is not None
    )


def _insertar_lecturas(
    db: Session, estaciones: list[EstacionNormalizada], ids: dict[str, int],
    ahora: datetime, resumen: ResumenIngestion,
) -> None:
    filas: list[dict[str, Any]] = []
    for e in estaciones:
        estacion_id = ids.get(e.id_externo)
        if estacion_id is None:
            continue
        for lec in e.lecturas:
            if not _lectura_valida(lec.contaminante, lec.valor, lec.unidad, lec.medido_en):
                resumen.lecturas_invalidas += 1
                logger.warning("Lectura inválida descartada (%s/%s)", e.id_externo, lec.contaminante)
                continue
            filas.append({"estacion_id": estacion_id, "contaminante": lec.contaminante,
                          "valor": float(lec.valor), "unidad": lec.unidad,
                          "medido_en": lec.medido_en, "capturado_en": ahora})
    if not filas:
        return
    stmt = (
        insert(Lectura).values(filas)
        .on_conflict_do_nothing(
            index_elements=[Lectura.estacion_id, Lectura.contaminante, Lectura.medido_en]
        )
        .returning(Lectura.id)
    )
    insertadas = len(db.execute(stmt).all())
    resumen.lecturas_insertadas += insertadas
    resumen.lecturas_duplicadas += len(filas) - insertadas


def ingerir(db: Session, resultado: ResultadoDescarga, *, ahora: datetime | None = None) -> ResumenIngestion:
    """Escribe un `ResultadoDescarga` en la base, en una sola transacción."""
    if resultado.fuente not in FUENTES:
        raise ValueError(f"Fuente desconocida: {resultado.fuente!r} (válidas: {FUENTES})")
    ahora = ahora or utcnow()
    resumen = ResumenIngestion(
        fuente=resultado.fuente,
        estaciones_fallidas=[{"id_externo": f.id_externo, "motivo": f.motivo} for f in resultado.fallos],
        estaciones_descartadas=dict(resultado.descartadas),
        abortada=resultado.abortada,
    )
    try:
        ids = _upsert_estaciones(db, resultado.fuente, resultado.estaciones, ahora, resumen)
        _insertar_lecturas(db, resultado.estaciones, ids, ahora, resumen)
        db.commit()
    except Exception:
        db.rollback()
        raise
    logger.info("Ingestión %s: %s", resultado.fuente, resumen.a_dict())
    return resumen


def ejecutar_openaq(db: Session) -> ResumenIngestion:
    with ClienteOpenAQ() as cliente:
        resultado = cliente.descargar()
    return ingerir(db, resultado)


def ejecutar_aqicn(db: Session) -> ResumenIngestion:
    with ClienteAQICN() as cliente:
        resultado = cliente.descargar()
    return ingerir(db, resultado)


def ejecutar_iboca(db: Session) -> ResumenIngestion:
    with ClienteIBOCA() as cliente:
        resultado = cliente.descargar()
    return ingerir(db, resultado)


def ejecutar_siata(db: Session) -> ResumenIngestion:
    with ClienteSIATA() as cliente:
        resultado = cliente.descargar()
    return ingerir(db, resultado)