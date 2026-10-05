"""
Consulta de alertas abiertas (M7 Bloque 2, D75.4).

Las alertas las CREA M5a (services/reconciliacion.py) pero hasta M7
nadie las leía. Este módulo solo LEE: no crea, no modifica, no cierra
alertas.

"Abierta" = estado != 'normalizada' (mismo criterio que el índice único
parcial `uq_alertas_abiertas` de `database/models.py`).
"""
from __future__ import annotations

import unicodedata
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Alerta, Emparejamiento, Estacion
from services.reportes import ciudad_de

LIMITE_DEFAULT = 100
LIMITE_MAXIMO = 500


def _sin_acentos(texto: str) -> str:
    """'Bogotá' y 'Bogota' deben matchear al filtrar por ciudad."""
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def _ciudad_de_estacion(e: Optional[Estacion]) -> Optional[str]:
    if e is None:
        return None
    return ciudad_de(e.fuente, e.nombre)


def _ciudades_de_alerta(
    alerta: Alerta,
    estaciones_por_id: dict[int, Estacion],
    emparejamientos_por_id: dict[int, Emparejamiento],
) -> set[str]:
    """Ciudades posibles de la alerta.

    - `alerta.estacion_id` presente -> la ciudad de esa estación
      (alertas tipo `umbral_aqi`).
    - `alerta.emparejamiento_id` presente -> las ciudades de las dos
      estaciones del emparejamiento (alertas tipo `discrepancia_fuentes`).
      Pueden ser la misma ciudad o dos cercanas.
    Una alerta con ambos campos nulos (no debería pasar) devuelve vacío.
    """
    ciudades: set[str] = set()
    if alerta.estacion_id is not None:
        c = _ciudad_de_estacion(estaciones_por_id.get(alerta.estacion_id))
        if c:
            ciudades.add(c)
    if alerta.emparejamiento_id is not None:
        emp = emparejamientos_por_id.get(alerta.emparejamiento_id)
        if emp is not None:
            for est_id in (emp.estacion_a_id, emp.estacion_b_id):
                c = _ciudad_de_estacion(estaciones_por_id.get(est_id))
                if c:
                    ciudades.add(c)
    return ciudades


def _ciudad_para_mostrar(
    ciudades: set[str], ciudad_filtro: Optional[str]
) -> Optional[str]:
    """Decide qué ciudad exponer en una alerta.

    - Si hay filtro de ciudad y esa ciudad está entre las de la alerta,
      se devuelve esa (la que pidió el usuario), normalizada a su forma
      canónica (ej. "Medellín", no "medellin").
    - Si no, se devuelve la primera alfabéticamente, para que la
      respuesta sea determinista cuando el emparejamiento cruza dos
      ciudades (ej. Bogotá < Medellín).

    El bug que motiva esta función: una alerta de discrepancia entre
    Bogotá y Medellín devolvía "Bogotá" incluso al filtrar por Medellín,
    porque el orden alfabético no sabe del filtro.
    """
    if not ciudades:
        return None
    if ciudad_filtro:
        buscada = _sin_acentos(ciudad_filtro.strip()).lower()
        for c in sorted(ciudades):
            if _sin_acentos(c).lower() == buscada:
                return c
    return sorted(ciudades)[0]


def _alerta_a_dict(
    a: Alerta,
    estaciones_por_id: dict[int, Estacion],
    emparejamientos_por_id: dict[int, Emparejamiento],
    ciudad_filtro: Optional[str] = None,
) -> dict[str, Any]:
    """Serializa la alerta y agrega `ciudad` (derivada).

    `ciudad` es un string único o None. Ver `_ciudad_para_mostrar` para
    la regla de qué ciudad se elige.
    """
    ciudades = _ciudades_de_alerta(a, estaciones_por_id, emparejamientos_por_id)
    return {
        "id": a.id,
        "tipo": a.tipo,
        "severidad": a.severidad,
        "estado": a.estado,
        "estacion_id": a.estacion_id,
        "emparejamiento_id": a.emparejamiento_id,
        "contaminante": a.contaminante,
        "valor_disparador": a.valor_disparador,
        "umbral": a.umbral,
        "mensaje": a.mensaje,
        "creada_en": a.creada_en,
        "actualizada_en": a.actualizada_en,
        "resuelta_en": a.resuelta_en,
        "ciudad": _ciudad_para_mostrar(ciudades, ciudad_filtro),
    }


def listar_alertas(
    db: Session,
    *,
    tipo: Optional[str] = None,
    ciudad: Optional[str] = None,
    limit: int = LIMITE_DEFAULT,
    offset: int = 0,
) -> dict[str, Any]:
    """Alertas abiertas (D75.4).

    Filtros opcionales: `tipo` (`umbral_aqi` | `discrepancia_fuentes`),
    `ciudad`. `ciudad` se resuelve en Python porque `alertas` no tiene
    columna `ciudad`: se infiere de la(s) estación(es) asociada(s) con
    `reportes.ciudad_de`, la misma función que usan las fichas de M6.

    Orden: por `creada_en` descendente (las más nuevas primero).

    Las estaciones y emparejamientos referenciados se resuelven con dos
    SELECT `IN (...)` en bloque, no uno por alerta: evita N+1.
    """
    if limit < 1:
        raise ValueError("limit debe ser >= 1")
    if limit > LIMITE_MAXIMO:
        raise ValueError(f"limit no puede superar {LIMITE_MAXIMO}")
    if offset < 0:
        raise ValueError("offset debe ser >= 0")

    stmt = select(Alerta).where(Alerta.estado != "normalizada")
    if tipo:
        stmt = stmt.where(Alerta.tipo == tipo.strip().lower())
    stmt = stmt.order_by(Alerta.creada_en.desc(), Alerta.id.desc())
    filas = list(db.execute(stmt).scalars())

    # Resolver estaciones y emparejamientos en bloque.
    ids_estacion: set[int] = set()
    ids_emp: set[int] = set()
    for a in filas:
        if a.estacion_id is not None:
            ids_estacion.add(a.estacion_id)
        if a.emparejamiento_id is not None:
            ids_emp.add(a.emparejamiento_id)

    estaciones_por_id: dict[int, Estacion] = {}
    if ids_estacion:
        estaciones_por_id = {
            e.id: e for e in db.execute(
                select(Estacion).where(Estacion.id.in_(ids_estacion))
            ).scalars()
        }

    emparejamientos_por_id: dict[int, Emparejamiento] = {}
    if ids_emp:
        emparejamientos_por_id = {
            e.id: e for e in db.execute(
                select(Emparejamiento).where(Emparejamiento.id.in_(ids_emp))
            ).scalars()
        }
        # Las estaciones del emparejamiento también hacen falta para
        # inferir ciudad.
        ids_est_emp: set[int] = set()
        for e in emparejamientos_por_id.values():
            ids_est_emp.add(e.estacion_a_id)
            ids_est_emp.add(e.estacion_b_id)
        faltantes = ids_est_emp - set(estaciones_por_id.keys())
        if faltantes:
            for e in db.execute(
                select(Estacion).where(Estacion.id.in_(faltantes))
            ).scalars():
                estaciones_por_id[e.id] = e

    # Filtro por ciudad (en Python)
    if ciudad:
        buscada = _sin_acentos(ciudad.strip()).lower()
        filas = [
            a for a in filas
            if buscada in {
                _sin_acentos(c).lower()
                for c in _ciudades_de_alerta(a, estaciones_por_id, emparejamientos_por_id)
            }
        ]

    total = len(filas)
    items = filas[offset : offset + limit]
    return {
        "items": [
            _alerta_a_dict(a, estaciones_por_id, emparejamientos_por_id, ciudad)
            for a in items
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }