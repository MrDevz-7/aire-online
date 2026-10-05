"""
Fichas determinísticas y plantillas de reporte (M6).
Una "ficha" es un dict con cifras, fuentes, fecha, cobertura, limitaciones
y atribuciones, construido con código normal. Es lo único que se le pasa a
Gemini para narrar, o a la plantilla como fallback. Gemini nunca calcula
(D2, D70).
Dos tipos de ficha: `estado_ciudad` (estado actual por ciudad) y
`auditoria_pronostico` (resumen del mes en curso de la auditoría del
pronóstico de Open-Meteo).
"""
from __future__ import annotations
import hashlib
import json
import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from database.config import settings
from database.models import AuditoriaPronostico, Estacion, Lectura, Pronostico
from services.aqi_escala import categoria_aqi, convertir_a_aqi
from sources.tipos import VENTANA_ACTIVIDAD_DIAS
OFFSET_COLOMBIA = timezone(timedelta(hours=-5))
CIUDAD_GLOBAL = "global"
# Fuentes regionales de una sola ciudad/zona.
_CIUDAD_POR_FUENTE: dict[str, str] = {
    "iboca": "Bogotá",
    "siata": "Medellín",
}
# Ciudades conocidas para inferir por nombre (variantes sin tilde incluidas).
_CIUDADES_CONOCIDAS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Bogotá", ("bogotá", "bogota")),
    ("Medellín", ("medellín", "medellin")),
    ("Cali", ("cali",)),
    ("Barranquilla", ("barranquilla",)),
    ("Cartagena", ("cartagena",)),
    ("Bucaramanga", ("bucaramanga",)),
    ("Pereira", ("pereira",)),
    ("Manizales", ("manizales",)),
)
_ATRIBUCIONES: dict[str, str] = {
    "openaq": "OpenAQ (openaq.org)",
    # M6 Bloque 4.5: los términos de la API de WAQI exigen atribuir al
    # World Air Quality Index Project Y a la agencia (EPA) de origen de
    # cada estación (no alcanza con acreditar al agregador). Ver
    # docs/CONCEPTOS.md, sección "Atribuciones de fuentes de datos".
    "aqicn": (
        "World Air Quality Index Project (aqicn.org) y las agencias "
        "de origen de cada estación"
    ),
    "iboca": "Red de Monitoreo de Calidad del Aire de Bogotá (IBOCA)",
    "siata": "SIATA — Área Metropolitana del Valle de Aburrá",
    "open-meteo": (
        "Copernicus Atmosphere Monitoring Service (CAMS), vía Open-Meteo "
        "Air Quality API (open-meteo.com). Uso no comercial"
    ),
}
_CONTAMINANTES_AUDITADOS: tuple[str, ...] = ("aqi", "pm25", "pm10")
_CONTAMINANTES_NO_AUDITABLES: tuple[str, ...] = ("o3", "no2", "so2", "co")
def _fecha_local(ahora: datetime) -> date:
    return ahora.astimezone(OFFSET_COLOMBIA).date()
def _mes_local(ahora: datetime) -> str:
    return ahora.astimezone(OFFSET_COLOMBIA).strftime("%Y-%m")
def _ciudad_de(fuente: str, nombre: str) -> Optional[str]:
    """Ciudad inferida de una estación, o None si no se puede inferir."""
    directa = _CIUDAD_POR_FUENTE.get(fuente)
    if directa is not None:
        return directa
    bajo = nombre.lower()
    for ciudad, variantes in _CIUDADES_CONOCIDAS:
        if any(v in bajo for v in variantes):
            return ciudad
    return None
def hash_canonico(ficha: dict[str, Any]) -> str:
    """sha256 del JSON canónico (claves ordenadas, sin espacios).
    Estable ante reordenamiento de claves."""
    canonico = json.dumps(
        ficha, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()
# ---------------------------------------------------------------------------
# Ficha: estado_ciudad
# ---------------------------------------------------------------------------
def _lecturas_recientes(db: Session, ahora: datetime) -> list[Any]:
    """Lecturas de estaciones activas dentro de la ventana D31."""
    desde = ahora - timedelta(days=VENTANA_ACTIVIDAD_DIAS)
    return db.execute(
        select(
            Estacion.id, Estacion.fuente, Estacion.nombre,
            Lectura.contaminante, Lectura.valor, Lectura.unidad, Lectura.medido_en,
        )
        .join(Lectura, Lectura.estacion_id == Estacion.id)
        .where(Estacion.activa.is_(True), Lectura.medido_en >= desde)
    ).all()
def _agrupar_por_ciudad(filas: list[Any]) -> dict[str, dict[str, Any]]:
    """Agrupa por ciudad y, dentro, por (contaminante, unidad). Por estación
    se conserva la última lectura de cada (contaminante, unidad)."""
    por_ciudad: dict[str, dict[str, Any]] = {}
    for fila in filas:
        ciudad = _ciudad_de(fila.fuente, fila.nombre)
        if ciudad is None:
            continue
        bucket = por_ciudad.setdefault(ciudad, {
            "contaminantes": {},
            "estaciones": set(),
            "fuentes": set(),
            "ultimo_medido_en": None,
        })
        bucket["estaciones"].add(fila.id)
        bucket["fuentes"].add(fila.fuente)
        clave = (fila.contaminante, fila.unidad)
        cont_bucket = bucket["contaminantes"].setdefault(
            clave, {"ultima_por_estacion": {}}
        )
        previa = cont_bucket["ultima_por_estacion"].get(fila.id)
        if previa is None or fila.medido_en > previa[0]:
            cont_bucket["ultima_por_estacion"][fila.id] = (fila.medido_en, fila.valor)
        ultimo = bucket["ultimo_medido_en"]
        if ultimo is None or fila.medido_en > ultimo:
            bucket["ultimo_medido_en"] = fila.medido_en
    return por_ciudad
def _categoria_para(contaminante: str, valor: float, unidad: str) -> Optional[str]:
    """Categoría AQI cualitativa, si se puede derivar del valor."""
    if unidad.strip().lower() == "aqi" or contaminante == "aqi":
        return categoria_aqi(valor)
    if contaminante in ("pm25", "pm10"):
        convertido = convertir_a_aqi(contaminante, valor, unidad)
        if convertido is None:
            return None
        return categoria_aqi(convertido)
    return None
def _formato_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def _formato_local(dt: datetime) -> str:
    return dt.astimezone(OFFSET_COLOMBIA).strftime("%Y-%m-%d %H:%M -05")
def construir_ficha_estado_ciudad(
    db: Session, alcance: str, *, ahora: Optional[datetime] = None
) -> dict[str, Any]:
    """Ficha del estado actual del aire para `alcance` (una ciudad, o
    `global` para todas las detectadas)."""
    ahora = ahora or datetime.now(timezone.utc)
    fecha_ref = _fecha_local(ahora)
    filas = _lecturas_recientes(db, ahora)
    por_ciudad = _agrupar_por_ciudad(filas)
    if alcance != CIUDAD_GLOBAL:
        por_ciudad = {alcance: por_ciudad[alcance]} if alcance in por_ciudad else {}
    ciudades_ficha: list[dict[str, Any]] = []
    fuentes_totales: set[str] = set()
    for ciudad_nombre in sorted(por_ciudad.keys()):
        bucket = por_ciudad[ciudad_nombre]
        contaminantes_ficha: list[dict[str, Any]] = []
        for (cont, unidad) in sorted(bucket["contaminantes"].keys()):
            info = bucket["contaminantes"][(cont, unidad)]
            valores = [v for _, v in info["ultima_por_estacion"].values()]
            if not valores:
                continue
            promedio = statistics.mean(valores)
            contaminantes_ficha.append({
                "contaminante": cont,
                "unidad": unidad,
                "valor": round(promedio, 3),
                "categoria_aqi": _categoria_para(cont, promedio, unidad),
                "n_estaciones": len(valores),
            })
        fuentes_ciudad = sorted(bucket["fuentes"])
        fuentes_totales.update(fuentes_ciudad)
        ultimo = bucket["ultimo_medido_en"]
        ciudades_ficha.append({
            "nombre": ciudad_nombre,
            "contaminantes": contaminantes_ficha,
            "estaciones_activas": len(bucket["estaciones"]),
            "fuentes_aportantes": fuentes_ciudad,
            "dato_mas_reciente_utc": _formato_utc(ultimo) if ultimo else None,
            "dato_mas_reciente_local": _formato_local(ultimo) if ultimo else None,
        })
    atribuciones = sorted(
        _ATRIBUCIONES[f] for f in fuentes_totales if f in _ATRIBUCIONES
    )
    return {
        "tipo": "estado_ciudad",
        "alcance": alcance,
        "fecha_referencia": fecha_ref.isoformat(),
        "ciudades": ciudades_ficha,
        "limitaciones": [
            "Cobertura real hoy: Bogotá y Valle de Aburrá.",
            "Los valores son promedios de estaciones puntuales, no un promedio del aire de toda la ciudad.",
            "El promedio combina las últimas lecturas disponibles de cada estación; no son simultáneas.",
            "Solo se incluyen estaciones con lecturas dentro de la ventana de actividad (D31).",
        ],
        "atribuciones": atribuciones,
    }
# ---------------------------------------------------------------------------
# Ficha: auditoria_pronostico
# ---------------------------------------------------------------------------
def _conteos_auditoria(
    db: Session, *, desde_mes: date, hasta_mes: date
) -> dict[str, int]:
    """Conteos por estado de las auditorías del mes (por fecha objetivo)."""
    estados = db.execute(
        select(AuditoriaPronostico.estado)
        .join(Pronostico, Pronostico.id == AuditoriaPronostico.pronostico_id)
        .where(
            Pronostico.fecha_objetivo >= desde_mes,
            Pronostico.fecha_objetivo <= hasta_mes,
        )
    ).scalars().all()
    conteos = {
        "capturados": len(estados),
        "pendientes": 0,
        "calculadas": 0,
        "no_auditable": 0,
        "sin_datos": 0,
    }
    for estado in estados:
        if estado == "pendiente":
            conteos["pendientes"] += 1
        elif estado == "resuelta":
            conteos["calculadas"] += 1
        elif estado == "no_auditable":
            conteos["no_auditable"] += 1
        elif estado == "sin_datos":
            conteos["sin_datos"] += 1
    return conteos
def _horizonte_maximo(db: Session) -> int:
    """Máximo `fecha_objetivo - fecha_captura` presente en `pronosticos`."""
    filas = db.execute(
        select(Pronostico.fecha_objetivo, Pronostico.fecha_captura)
    ).all()
    if not filas:
        return 0
    return max((f.fecha_objetivo - f.fecha_captura).days for f in filas)
def _errores_por_contaminante_y_horizonte(
    db: Session, *, min_dias: int
) -> list[dict[str, Any]]:
    """Por (contaminante, horizonte): días objetivo distintos auditados y,
    si alcanzan `min_dias`, el error absoluto promedio y el sesgo. Se
    cuentan días, no filas: estaciones que comparten celda comparten
    pronóstico y no son muestras independientes (D72)."""
    filas = db.execute(
        select(
            Pronostico.contaminante,
            Pronostico.fecha_objetivo,
            Pronostico.fecha_captura,
            AuditoriaPronostico.error_abs,
            AuditoriaPronostico.sesgo,
        )
        .join(AuditoriaPronostico, AuditoriaPronostico.pronostico_id == Pronostico.id)
        .where(
            AuditoriaPronostico.estado == "resuelta",
            AuditoriaPronostico.error_abs.is_not(None),
        )
    ).all()
    grupos: dict[tuple[str, int], dict[str, Any]] = {}
    for fila in filas:
        horiz = (fila.fecha_objetivo - fila.fecha_captura).days
        clave = (fila.contaminante, horiz)
        bucket = grupos.setdefault(
            clave, {"dias": set(), "errores": [], "sesgos": []}
        )
        bucket["dias"].add(fila.fecha_objetivo)
        bucket["errores"].append(fila.error_abs)
        if fila.sesgo is not None:
            bucket["sesgos"].append(fila.sesgo)
    resultado: list[dict[str, Any]] = []
    for (cont, horiz), bucket in sorted(grupos.items()):
        dias = len(bucket["dias"])
        item: dict[str, Any] = {
            "contaminante": cont,
            "horizonte": horiz,
            "dias_auditados": dias,
            "muestra_suficiente": dias >= min_dias,
        }
        if item["muestra_suficiente"]:
            item["error_abs_promedio"] = round(statistics.mean(bucket["errores"]), 3)
            if bucket["sesgos"]:
                item["sesgo_promedio"] = round(statistics.mean(bucket["sesgos"]), 3)
        resultado.append(item)
    return resultado
def construir_ficha_auditoria_pronostico(
    db: Session, alcance: str = CIUDAD_GLOBAL, *, ahora: Optional[datetime] = None
) -> dict[str, Any]:
    """Ficha del resumen del mes en curso de la auditoría del pronóstico."""
    ahora = ahora or datetime.now(timezone.utc)
    fecha_ref = _fecha_local(ahora)
    mes = _mes_local(ahora)
    anio, num_mes = (int(x) for x in mes.split("-"))
    desde_mes = date(anio, num_mes, 1)
    if num_mes == 12:
        hasta_mes = date(anio + 1, 1, 1) - timedelta(days=1)
    else:
        hasta_mes = date(anio, num_mes + 1, 1) - timedelta(days=1)
    conteos = _conteos_auditoria(db, desde_mes=desde_mes, hasta_mes=hasta_mes)
    horizonte_max = _horizonte_maximo(db)
    errores = _errores_por_contaminante_y_horizonte(
        db, min_dias=settings.MIN_DIAS_AUDITADOS_PARA_PROMEDIO
    )
    return {
        "tipo": "auditoria_pronostico",
        "alcance": alcance,
        "fecha_referencia": fecha_ref.isoformat(),
        "mes_en_curso": mes,
        "conteos": conteos,
        "horizonte_maximo_dias": horizonte_max,
        "contaminantes_auditados": list(_CONTAMINANTES_AUDITADOS),
        "contaminantes_no_auditables": list(_CONTAMINANTES_NO_AUDITABLES),
        "errores_por_contaminante_y_horizonte": errores,
        "limitaciones": [
            "El pronóstico es de un modelo regional en grilla (~45 km), no por estación.",
            f"Horizonte medido en este proyecto: {horizonte_max} días.",
            "o3, no2, so2 y co se capturan pero no se auditan (requieren conversión de unidades que el proyecto no hace).",
        ],
        # La ficha mezcla DOS fuentes: el pronóstico (Open-Meteo/CAMS) y la
        # verdad de terreno contra la que se compara (AQICN, hardcodeada en
        # services/auditoria.py al resolver cada fila). Se atribuyen ambas.
        "atribuciones": [_ATRIBUCIONES["open-meteo"], _ATRIBUCIONES["aqicn"]],
    }
# ---------------------------------------------------------------------------
# Plantillas determinísticas (fallback sin Gemini)
# ---------------------------------------------------------------------------
def plantilla_estado_ciudad(ficha: dict[str, Any]) -> str:
    """Narra una ficha `estado_ciudad` sin IA. No agrega cifras fuera de la ficha."""
    fecha = ficha["fecha_referencia"]
    ciudades = ficha.get("ciudades", [])
    if not ciudades:
        return (
            f"Reporte de estado del aire — {fecha}. "
            "No hay datos disponibles con la cobertura actual del sistema."
        )
    parrafos: list[str] = []
    encabezado = f"Reporte de estado del aire — {fecha}."
    if ficha["alcance"] == CIUDAD_GLOBAL:
        encabezado += " Cobertura: " + ", ".join(c["nombre"] for c in ciudades) + "."
    parrafos.append(encabezado)
    for ciudad in ciudades:
        nombre = ciudad["nombre"]
        conts = ciudad["contaminantes"]
        if not conts:
            parrafos.append(f"En {nombre}: sin lecturas disponibles.")
            continue
        partes = []
        for c in conts:
            p = f"{c['contaminante']} {c['valor']} {c['unidad']}"
            if c.get("categoria_aqi"):
                p += f" ({c['categoria_aqi']})"
            partes.append(p)
        reciente = ciudad.get("dato_mas_reciente_local") or "sin dato reciente"
        parrafos.append(
            f"En {nombre}: " + "; ".join(partes) + ". "
            f"Estaciones activas: {ciudad['estaciones_activas']}. "
            f"Fuentes: {', '.join(ciudad['fuentes_aportantes'])}. "
            f"Dato más reciente: {reciente}."
        )
    parrafos.append("Limitaciones: " + " ".join(ficha.get("limitaciones", [])))
    if ficha.get("atribuciones"):
        parrafos.append("Fuentes: " + " ".join(ficha["atribuciones"]) + ".")
    return "\n\n".join(parrafos)
def plantilla_auditoria_pronostico(ficha: dict[str, Any]) -> str:
    """Narra una ficha `auditoria_pronostico` sin IA. No agrega cifras
    fuera de la ficha y respeta el indicador de muestra insuficiente."""
    fecha = ficha["fecha_referencia"]
    conteos = ficha["conteos"]
    parrafos: list[str] = []
    parrafos.append(
        f"Resumen de auditoría del pronóstico del mes {ficha['mes_en_curso']} "
        f"(al {fecha}): {conteos['capturados']} pronósticos capturados, "
        f"{conteos['pendientes']} pendientes, {conteos['calculadas']} calculados, "
        f"{conteos['no_auditable']} no auditables, {conteos['sin_datos']} sin datos."
    )
    parrafos.append(
        f"Horizonte máximo presente: {ficha['horizonte_maximo_dias']} días."
    )
    errores = ficha.get("errores_por_contaminante_y_horizonte", [])
    if not errores:
        parrafos.append("Todavía no hay errores calculados.")
    else:
        partes: list[str] = []
        for e in errores:
            etiqueta = f"{e['contaminante']} (horizonte {e['horizonte']} días)"
            if e.get("muestra_suficiente"):
                fragmento = (
                    f"{etiqueta}: error absoluto promedio "
                    f"{e['error_abs_promedio']}"
                )
                if "sesgo_promedio" in e:
                    fragmento += f", sesgo {e['sesgo_promedio']:+.3f}"
                fragmento += f" ({e['dias_auditados']} días auditados)"
                partes.append(fragmento)
            else:
                partes.append(
                    f"{etiqueta}: todavía no hay suficientes días auditados "
                    f"({e['dias_auditados']} de "
                    f"{settings.MIN_DIAS_AUDITADOS_PARA_PROMEDIO} requeridos)"
                )
        parrafos.append(" ".join(partes) + ".")
    parrafos.append("Limitaciones: " + " ".join(ficha.get("limitaciones", [])))
    if ficha.get("atribuciones"):
        parrafos.append("Fuentes: " + " ".join(ficha["atribuciones"]) + ".")
    return "\n\n".join(parrafos)