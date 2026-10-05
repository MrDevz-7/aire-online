"""
Servicio de lectura del engine (M7, D75).

Endpoints de solo lectura que exponen lo que M3/M4/M5/M6 ya dejaron
persistido. NO escriben en la base, NO llaman a Gemini, NO recalculan.

Reutiliza:
  - `services.reportes.ciudad_de`: infiere la ciudad de una estación
    (no hay columna `ciudad` en `estaciones`; ver M6).
  - `services.reportes.ATRIBUCIONES`: el texto de atribución por fuente,
    el mismo que usan las fichas de M6.
"""
from __future__ import annotations

import unicodedata
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database.config import settings
from database.models import Estacion, Lectura
from services.reportes import ATRIBUCIONES, ciudad_de

# ---------------------------------------------------------------------------
# D74 — fuentes sin histórico público
# ---------------------------------------------------------------------------
def _parse_fuentes(raw: str) -> frozenset[str]:
    """'aqicn, SIATA' -> frozenset({'aqicn', 'siata'}). Vacío o solo
    espacios -> frozenset(). Tolera espacios y mayúsculas."""
    return frozenset(
        item.strip().lower() for item in raw.split(",") if item.strip()
    )


def fuentes_sin_historico_publico() -> frozenset[str]:
    """D74: fuentes cuyo histórico NO se expone público. Si una fuente
    aparece acá, `/api/estaciones/{id}/lecturas` devuelve solo su último
    snapshot (una lectura por contaminante) y marca
    `historico_restringido: true`."""
    return _parse_fuentes(settings.FUENTES_SIN_HISTORICO_PUBLICO)

# ---------------------------------------------------------------------------
# Paginación (convención D75)
# ---------------------------------------------------------------------------
LIMITE_DEFAULT = 100
LIMITE_MAXIMO = 500


def limit_y_offset(limit: int, offset: int) -> tuple[int, int]:
    """Valida y devuelve (limit, offset). Los endpoints ya los validan vía
    `Query(ge=..., le=...)` de FastAPI, pero esta función existe para que
    quien llame al servicio desde Python (tests, scripts) no pueda meter
    un valor absurdo."""
    if limit < 1:
        raise ValueError("limit debe ser >= 1")
    if limit > LIMITE_MAXIMO:
        raise ValueError(f"limit no puede superar {LIMITE_MAXIMO}")
    if offset < 0:
        raise ValueError("offset debe ser >= 0")
    return limit, offset

# ---------------------------------------------------------------------------
# Endpoint 1 — GET /api/estaciones
# ---------------------------------------------------------------------------
def _sin_acentos(texto: str) -> str:
    """'Bogotá' y 'Bogota' deben matchear al filtrar por ciudad."""
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def _estacion_a_dict(e: Estacion) -> dict[str, Any]:
    return {
        "id": e.id,
        "fuente": e.fuente,
        "id_externo": e.id_externo,
        "nombre": e.nombre,
        "latitud": e.latitud,
        "longitud": e.longitud,
        "ciudad": ciudad_de(e.fuente, e.nombre),
        "municipio": e.municipio,
        "departamento": e.departamento,
        "activa": e.activa,
        "primera_vez_vista": e.primera_vez_vista,
        "ultima_vez_vista": e.ultima_vez_vista,
    }


def listar_estaciones(
    db: Session,
    *,
    ciudad: Optional[str] = None,
    fuente: Optional[str] = None,
    activa: Optional[bool] = None,
    limit: int = LIMITE_DEFAULT,
    offset: int = 0,
) -> dict[str, Any]:
    """Estaciones con filtros opcionales y paginación (D75.1).

    El filtro por `ciudad` se aplica en Python porque `estaciones` no
    tiene columna `ciudad`: se infiere con `reportes.ciudad_de`. Con unos
    pocos cientos de estaciones esto es aceptable; si el volumen creciera
    mucho habría que materializar la columna (fuera del alcance de M7).

    Los filtros por `fuente` y `activa` sí van al SQL (D31: `activa` es
    la columna derivada de la ventana de actividad, no un cálculo on-the-fly).
    """
    limit, offset = limit_y_offset(limit, offset)
    stmt = select(Estacion)
    if fuente:
        stmt = stmt.where(Estacion.fuente == fuente.strip().lower())
    if activa is not None:
        stmt = stmt.where(Estacion.activa.is_(activa))
    stmt = stmt.order_by(Estacion.id.asc())
    filas = list(db.execute(stmt).scalars())
    if ciudad:
        buscada = _sin_acentos(ciudad.strip()).lower()
        filas = [
            e for e in filas
            if buscada
            and _sin_acentos(ciudad_de(e.fuente, e.nombre) or "").lower() == buscada
        ]
    total = len(filas)
    items = filas[offset : offset + limit]
    return {
        "items": [_estacion_a_dict(e) for e in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }

# ---------------------------------------------------------------------------
# Endpoint 2 — GET /api/estaciones/{id}/lecturas
# ---------------------------------------------------------------------------
class EstacionNoEncontrada(Exception):
    """La estación pedida no existe. El endpoint lo traduce a 404."""


def _lectura_a_dict(lec: Lectura) -> dict[str, Any]:
    return {
        "id": lec.id,
        "estacion_id": lec.estacion_id,
        "contaminante": lec.contaminante,
        "valor": lec.valor,
        "unidad": lec.unidad,
        "medido_en": lec.medido_en,
        "capturado_en": lec.capturado_en,
    }


def _ultimas_por_contaminante(
    db: Session, estacion_id: int, contaminante: Optional[str]
) -> tuple[list[dict[str, Any]], int]:
    """D74: una lectura por contaminante, la más reciente.

    Se usa SELECT DISTINCT ON (contaminante) de Postgres, que deja
    exactamente una fila por grupo, la primera según el ORDER BY. El
    ORDER BY debe arrancar con la misma expresión del DISTINCT ON
    (requisito de Postgres), y desempata por medido_en DESC e id DESC
    para que con dos lecturas del mismo contaminante y la misma hora
    quede la última insertada.
    """
    stmt = (
        select(Lectura)
        .distinct(Lectura.contaminante)
        .where(Lectura.estacion_id == estacion_id)
    )
    if contaminante is not None:
        stmt = stmt.where(Lectura.contaminante == contaminante)
    stmt = stmt.order_by(
        Lectura.contaminante, Lectura.medido_en.desc(), Lectura.id.desc()
    )
    filas = list(db.execute(stmt).scalars())
    # Reordenamos por medido_en DESC para que "lo más reciente" quede arriba.
    filas.sort(key=lambda l: (l.medido_en, l.id), reverse=True)
    return [_lectura_a_dict(l) for l in filas], len(filas)


def _lecturas_en_ventana(
    db: Session,
    estacion_id: int,
    desde: Optional[Any],
    hasta: Optional[Any],
    contaminante: Optional[str],
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    filtros = [Lectura.estacion_id == estacion_id]
    if desde is not None:
        filtros.append(Lectura.medido_en >= desde)
    if hasta is not None:
        filtros.append(Lectura.medido_en <= hasta)
    if contaminante is not None:
        filtros.append(Lectura.contaminante == contaminante)

    total = db.execute(
        select(func.count()).select_from(Lectura).where(*filtros)
    ).scalar_one()

    filas = list(
        db.execute(
            select(Lectura)
            .where(*filtros)
            .order_by(Lectura.medido_en.desc(), Lectura.id.desc())
            .limit(limit)
            .offset(offset)
        ).scalars()
    )
    return [_lectura_a_dict(l) for l in filas], int(total)


def listar_lecturas(
    db: Session,
    estacion_id: int,
    *,
    desde: Optional[Any] = None,
    hasta: Optional[Any] = None,
    contaminante: Optional[str] = None,
    limit: int = LIMITE_DEFAULT,
    offset: int = 0,
) -> dict[str, Any]:
    """Lecturas de una estación (D75.2).

    D74: si la fuente de la estación está en `FUENTES_SIN_HISTORICO_PUBLICO`,
    el endpoint devuelve SOLO la lectura más reciente de cada contaminante
    (el "último snapshot" de la estación, sin histórico) y marca
    `historico_restringido: true`. Los filtros `desde`/`hasta` se ignoran
    en ese caso: no hay histórico que acotar. El filtro `contaminante` sí
    se respeta, porque acota qué contaminantes del snapshot se devuelven.
    """
    limit, offset = limit_y_offset(limit, offset)
    estacion = db.get(Estacion, estacion_id)
    if estacion is None:
        raise EstacionNoEncontrada(f"Estación {estacion_id} no existe")

    restringida = estacion.fuente.lower() in fuentes_sin_historico_publico()
    if restringida:
        items, total = _ultimas_por_contaminante(db, estacion_id, contaminante)
    else:
        items, total = _lecturas_en_ventana(
            db, estacion_id, desde, hasta, contaminante, limit, offset
        )
        # Paginación explícita también en el caso restringido: como el
        # conjunto es chico (a lo sumo un contaminante por fila), la
        # aplicamos sobre la lista resultante para que `limit`/`offset`
        # tengan el mismo significado en ambas ramas.
    if restringida:
        items = items[offset : offset + limit]

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "historico_restringido": restringida,
    }

# ---------------------------------------------------------------------------
# Endpoint 6 — GET /api/atribuciones
# ---------------------------------------------------------------------------
# Orden canónico de las fuentes en la respuesta (el que usa D75.6).
_ORDEN_FUENTES: tuple[str, ...] = ("openaq", "aqicn", "iboca", "siata", "open-meteo")

# Estado de confirmación de los términos/licencia de cada fuente. Sale de
# la investigación documentada en docs/CONCEPTOS.md (M6, Bloque 4.4). El
# TEXTO de atribución NO se duplica acá: se toma de `reportes.ATRIBUCIONES`.
ESTADOS_ATRIBUCION: dict[str, tuple[str, str]] = {
    "openaq": (
        "confirmada",
        "Términos en docs.openaq.org; la API de licencias confirma "
        "atribución obligatoria y uso no comercial permitido.",
    ),
    "aqicn": (
        "confirmada",
        "Términos en aqicn.org/api/tos/: atribución al World Air Quality "
        "Index Project y a la agencia de origen; notificación previa por "
        "email para uso público sin fines de lucro (D74).",
    ),
    "iboca": (
        "parcial",
        "El OAB (Secretaría Distrital de Ambiente) declara no ejercer "
        "derechos de autor sobre sus indicadores (Ley 1712); no es una "
        "licencia abierta formal tipo CC BY.",
    ),
    "siata": (
        "no_confirmada",
        "El portal de datos abiertos del AMVA devolvió 502 durante la "
        "investigación (M6); sin licencia pública verificada.",
    ),
    "open-meteo": (
        "confirmada",
        "Licencia en open-meteo.com/en/licence; atribución a CAMS "
        "(Copernicus/ECMWF) obligatoria. Uso no comercial.",
    ),
}


def listar_atribuciones() -> dict[str, Any]:
    """Atribuciones y estado de confirmación por fuente (D75.6).

    El texto de atribución proviene de `reportes.ATRIBUCIONES` (el mismo
    que usan las fichas de M6): no se duplica. Lo que agrega este endpoint
    es el `estado_confirmacion` y una `nota` breve, que el frontend puede
    mostrar sin depender de leer un markdown.
    """
    items: list[dict[str, Any]] = []
    for fuente in _ORDEN_FUENTES:
        texto = ATRIBUCIONES.get(fuente)
        if texto is None:
            # Fuente del orden canónico que no está en ATRIBUCIONES:
            # no debería pasar, pero se maneja sin romper.
            continue
        estado, nota = ESTADOS_ATRIBUCION.get(
            fuente, ("sin_dato", "Sin información de licencia registrada.")
        )
        items.append({
            "fuente": fuente,
            "texto": texto,
            "estado_confirmacion": estado,
            "nota": nota,
        })
    return {"items": items}