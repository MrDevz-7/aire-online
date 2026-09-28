"""
Descubre negocios locales vía OpenStreetMap: Nominatim geocodifica la zona,
Overpass API trae los negocios de esa categoría dentro del área resultante.
Decisiones de diseño, limitaciones conocidas y trade-offs frente a Google
Places: ver docs/DECISIONES_TECNICAS.md.
"""
from __future__ import annotations
import logging
import socket
import threading
import time
from contextlib import contextmanager
from typing import Optional
import httpx
from database.config import settings
logger = logging.getLogger(__name__)
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Mirrors públicos de Overpass, en orden de preferencia. Reordenados el
# 26/08 con evidencia real de logs de Render (ver docs/DECISIONES_TECNICAS.md,
# sección "Fallos silenciosos de Overpass"):
# 1. VK Maps (mail.ru): es HOY el único de los 3 que completa el handshake
#    TCP desde el rango de IPs de Render -- los otros dos ni siquiera
#    llegan a responder. Tiene un caveat conocido (reportes de la
#    comunidad de OSM lo describen bloqueado/limitado para ciertos
#    clientes, respondiendo 200 con "remark" en vez de un error claro),
#    pero el fix de más abajo ya detecta eso y no lo confunde con "0
#    resultados reales".
# 2. Private.coffee (ex Kumi Systems): el mirror que la propia wiki de OSM
#    recomienda para uso intensivo (sin rate limit propio, 4 servidores de
#    20 cores/256GB cada uno), pero la wiki de status de Overpass reporta
#    (05/08/2026) timeouts repetidos de conexión desde IPs de US/cloud
#    hacia este mirror y hacia overpass-api.de -- degradación real de la
#    infraestructura pública, no algo que un cambio de código arregle.
# 3. overpass-api.de (el "oficial"): último porque los logs de Render
#    muestran que activamente rechaza la conexión ("Connection refused")
#    desde el rango de IPs de Render, consistente con el mismo reporte.
# Nota: se evaluó agregar overpass.openstreetmap.fr y overpass.openstreetmap.ru
# como mirrors extra. NO se agregaron: a fecha 26/08/2026 ya no figuran en
# la lista oficial de instancias públicas de la wiki de OSM -- agregarlos
# hubiera sido un parche especulativo sin evidencia de que sigan vivos.
OVERPASS_URLS: list[str] = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]
# Categoría (texto libre en español) -> tag(s) de OpenStreetMap.
# Agregar categorías nuevas: https://wiki.openstreetmap.org/wiki/Map_Features
CATEGORY_TAG_MAP: dict[str, list[tuple[str, str]]] = {
    "restaurantes": [("amenity", "restaurant")],
    "cafes": [("amenity", "cafe")],
    "panaderias": [("shop", "bakery")],
    "peluquerias": [("shop", "hairdresser")],
    "barberias": [("shop", "hairdresser")],
    "gimnasios": [("leisure", "fitness_centre")],
    "veterinarias": [("amenity", "veterinary")],
    "odontologos": [("amenity", "dentist")],
    "clinicas dentales": [("amenity", "dentist")],
    "farmacias": [("amenity", "pharmacy")],
    "hoteles": [("tourism", "hotel")],
    "abogados": [("office", "lawyer")],
    "contadores": [("office", "accountant")],
    "talleres mecanicos": [("shop", "car_repair")],
    "salones de belleza": [("shop", "beauty")],
    "tiendas de ropa": [("shop", "clothes")],
    "ferreterias": [("shop", "hardware")],
}
class PlacesAPIError(Exception):
    """Error al descubrir negocios: red, rate limit, zona o categoría
    inválida. Nombre heredado de la integración con Google Places."""
class AllOverpassMirrorsFailedError(PlacesAPIError):
    """
    Subclase específica de PlacesAPIError: TODOS los mirrors de
    OVERPASS_URLS fallaron por red o devolvieron un fallo interno
    (remark) para esta consulta puntual. Existe separada de PlacesAPIError
    para que api/main.py pueda distinguir "la infraestructura pública de
    Overpass está degradada ahora mismo" (donde SÍ tiene sentido buscar un
    respaldo en caché de una corrida anterior) de otros PlacesAPIError
    como categoría no soportada o zona no geocodificable (donde un
    respaldo en caché no tiene sentido -- es un error del input, no de la
    infraestructura). Ver docs/DECISIONES_TECNICAS.md.
    """
def _user_agent() -> str:
    contact = settings.OSM_CONTACT_EMAIL or "sin-contacto-configurado"
    return f"CustoFinder/0.1 (contacto: {contact})"
# Serializa el acceso a _ipv4_client(): como el monkeypatch de
# socket.getaddrinfo() es un estado GLOBAL del proceso, dos threads
# ejecutándolo al mismo tiempo podrían pisarse (uno restaura la función
# original mientras el otro todavía la necesita parcheada). El log real
# de Render del 25/08 mostró que el 502 de esa vez fue por Overpass
# rechazando la conexión, no por esto — pero como ya estamos tocando el
# archivo, cerramos la vulnerabilidad de una vez: con el lock, como
# mucho una request espera unos milisegundos a que la anterior termine
# de resolver el hostname, nunca hay dos parcheos simultáneos.
_getaddrinfo_lock = threading.Lock()
@contextmanager
def _ipv4_client():
    """
    Cliente httpx que fuerza resolución DNS únicamente a IPv4 mientras está
    activo. Necesario en hosts gratuitos sin ruta de salida IPv6 (ej.
    Render). Un intento anterior con httpx.HTTPTransport(local_address=...)
    no alcanzaba: si el DNS devolvía una dirección IPv6 entre los
    candidatos, igual se intentaba usar y fallaba con "Address family for
    hostname not supported". Filtrando en el propio socket.getaddrinfo, esa
    dirección IPv6 nunca llega a proponerse como candidata.
    Thread-safe vía _getaddrinfo_lock (ver comentario arriba).
    Detalle completo: docs/DECISIONES_TECNICAS.md.
    """
    with _getaddrinfo_lock:
        original_getaddrinfo = socket.getaddrinfo
        def ipv4_only_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            return original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
        socket.getaddrinfo = ipv4_only_getaddrinfo
        try:
            with httpx.Client() as client:
                yield client
        finally:
            socket.getaddrinfo = original_getaddrinfo
def _geocode_zone(zone: str, client: httpx.Client) -> tuple[float, float, float, float]:
    """Geocodifica `zone` con Nominatim. Devuelve bbox (south, west, north, east)."""
    params = {"q": f"{zone}, Colombia", "format": "json", "limit": 1}
    headers = {"User-Agent": _user_agent()}
    try:
        response = client.get(NOMINATIM_URL, params=params, headers=headers, timeout=15.0)
    except httpx.RequestError as exc:
        raise PlacesAPIError(f"Error de red llamando Nominatim: {exc}") from exc
    if response.status_code == 429:
        raise PlacesAPIError(
            "Rate limit alcanzado en Nominatim (429). Nominatim permite ~1 "
            "request/segundo; evita disparar búsquedas en paralelo."
        )
    if response.status_code != 200:
        raise PlacesAPIError(
            f"Nominatim falló con status {response.status_code}: {response.text[:300]}"
        )
    results = response.json()
    if not results:
        raise PlacesAPIError(
            f"Nominatim no encontró la zona '{zone}'. Prueba con un nombre "
            "más específico, ej. 'Laureles, Medellín, Colombia'."
        )
    south, north, west, east = (float(v) for v in results[0]["boundingbox"])
    return south, west, north, east
def _overpass_query(
    bbox: tuple[float, float, float, float],
    tags: list[tuple[str, str]],
    client: httpx.Client,
) -> list[dict]:
    """
    Trae los elementos (nodes/ways/relations) que matchean `tags` dentro de
    `bbox`. Prueba cada URL de OVERPASS_URLS en orden: si una falla por red
    (conexión rechazada, timeout), devuelve un status de error, o devuelve
    un JSON con "remark" (la forma en que Overpass reporta fallos internos
    -- cuota agotada, rate limit silencioso, timeout del lado del servidor
    -- SIN usar un status HTTP de error; confirmado el 26/08 que esto
    explica el "200 OK, 0 negocios" que veníamos viendo con mail.ru), sigue
    con la siguiente URL en vez de asumir que la zona no tiene resultados.
    Solo lanza AllOverpassMirrorsFailedError si TODAS fallan, con el
    detalle de cada intento.
    """
    bbox_str = ",".join(str(v) for v in bbox)
    filters = "".join(
        f'node["{k}"="{v}"]({bbox_str});way["{k}"="{v}"]({bbox_str});relation["{k}"="{v}"]({bbox_str});'
        for k, v in tags
    )
    query = f"[out:json][timeout:25];({filters});out center tags;"
    headers = {"User-Agent": _user_agent()}
    # Timeout corto por mirror (sin cambios respecto a la versión anterior:
    # el log real de Render del 25/08 muestra que private.coffee corta a
    # los ~8s y mail.ru responde ~4s después, ~9-12s en total -- ya está
    # bien afinado con evidencia real, no hay motivo para tocarlo sin
    # evidencia nueva de que haga falta).
    overpass_timeout = httpx.Timeout(connect=4.0, read=8.0, write=5.0, pool=5.0)
    errors: list[str] = []
    for url in OVERPASS_URLS:
        try:
            response = client.post(url, data={"data": query}, headers=headers, timeout=overpass_timeout)
        except httpx.RequestError as exc:
            logger.warning("Overpass mirror %s no respondió: %s. Probando el siguiente.", url, exc)
            errors.append(f"{url}: error de red ({exc})")
            continue
        if response.status_code == 429:
            logger.warning("Overpass mirror %s devolvió 429 (rate limit). Probando el siguiente.", url)
            errors.append(f"{url}: rate limit (429)")
            continue
        if response.status_code != 200:
            logger.warning(
                "Overpass mirror %s falló con status %s. Probando el siguiente.",
                url, response.status_code,
            )
            errors.append(f"{url}: status {response.status_code}: {response.text[:200]}")
            continue
        try:
            body = response.json()
        except ValueError as exc:
            # Status 200 pero el cuerpo no es JSON válido (mirrors
            # sobrecargados a veces devuelven una página HTML de error con
            # status 200). Antes de este fix, .json() sin try hubiera
            # propagado la excepción sin control -- posible causa adicional
            # de 502 que no habíamos contemplado.
            logger.warning(
                "Overpass mirror %s devolvió 200 pero el cuerpo no es JSON válido: %s. Probando el siguiente.",
                url, exc,
            )
            errors.append(f"{url}: 200 con cuerpo no-JSON ({exc})")
            continue
        elements = body.get("elements", [])
        remark = body.get("remark")
        if remark and not elements:
            # EL BUG REAL detrás de "200 OK, 0 negocios encontrados"
            # confirmado en logs de Render (25/08) con mail.ru: Overpass
            # reporta fallos internos con status 200 + campo "remark", NO
            # con un status de error. Antes se ignoraba "remark" y se
            # devolvía [] como si la zona genuinamente no tuviera negocios
            # de esa categoría. Detalle: docs/DECISIONES_TECNICAS.md.
            logger.warning(
                "Overpass mirror %s devolvió 200 con remark=%r y 0 elementos "
                "(fallo interno del mirror, no ausencia real de datos). Probando el siguiente.",
                url, remark,
            )
            errors.append(f"{url}: remark={remark!r}")
            continue
        if remark:
            # remark presente pero CON datos: probablemente una respuesta
            # parcial/truncada. Se devuelve igual (mejor datos parciales
            # que nada) pero queda registrado para diagnóstico futuro.
            logger.warning(
                "Overpass mirror %s devolvió remark=%r junto con %d elementos (posible respuesta parcial).",
                url, remark, len(elements),
            )
        return elements
    raise AllOverpassMirrorsFailedError(
        "Todos los mirrors de Overpass fallaron o devolvieron un fallo interno: " + " | ".join(errors)
    )
def _element_to_business_dict(element: dict, zone: str, category: str) -> Optional[dict]:
    """Convierte un elemento crudo de Overpass al dict que espera api/main.py."""
    tags = element.get("tags", {})
    name = tags.get("name")
    if not name:
        return None
    if element["type"] == "node":
        lat, lon = element.get("lat"), element.get("lon")
    else:
        center = element.get("center", {})
        lat, lon = center.get("lat"), center.get("lon")
    website = tags.get("website") or tags.get("contact:website")
    phone = tags.get("phone") or tags.get("contact:phone")
    street = tags.get("addr:street", "")
    housenumber = tags.get("addr:housenumber", "")
    address = f"{street} {housenumber}".strip() or None
    return {
        "place_id": f"osm_{element['type']}_{element['id']}",
        "name": name,
        "category": category,
        "address": address,
        "zone": zone,
        "phone": phone,
        "has_website": bool(website),
        "rating": None,        # OSM no tiene sistema de reseñas.
        "review_count": None,  # idem.
        "latitude": lat,
        "longitude": lon,
    }
def discover_businesses(zone: str, category: str) -> list[dict]:
    """
    Descubre negocios de `category` en `zone` vía OpenStreetMap.
    Returns:
        Lista de dicts: place_id, name, category, address, zone, phone,
        has_website, rating, review_count, latitude, longitude.
    Raises:
        PlacesAPIError: categoría no soportada o zona no geocodificable.
        AllOverpassMirrorsFailedError (subclase de PlacesAPIError): todos
        los mirrors de Overpass fallaron o devolvieron un fallo interno.
    """
    tags = CATEGORY_TAG_MAP.get(category.strip().lower())
    if not tags:
        raise PlacesAPIError(
            f"Categoría '{category}' no está mapeada a un tag de OpenStreetMap "
            f"todavía. Categorías soportadas hoy: {', '.join(sorted(CATEGORY_TAG_MAP))}."
        )
    seen_place_ids: set[str] = set()
    results: list[dict] = []
    with _ipv4_client() as client:
        bbox = _geocode_zone(zone, client)
        time.sleep(1)  # respeta el límite de ~1 req/seg de Nominatim antes de Overpass
        elements = _overpass_query(bbox, tags, client)
        for element in elements:
            biz = _element_to_business_dict(element, zone, category)
            if biz is None:
                continue
            if biz["place_id"] in seen_place_ids:
                continue
            seen_place_ids.add(biz["place_id"])
            results.append(biz)
    if not results:
        logger.info("Overpass sin resultados para zona=%r category=%r", zone, category)
    return results
def find_businesses_with_website_url(zone: str, category: str) -> list[dict]:
    """
    Como discover_businesses(), más la clave "website" (URL cruda de OSM)
    que Playwright necesita para navegar. Separada de discover_businesses()
    para no arriesgar ese flujo — detalle en docs/DECISIONES_TECNICAS.md.
    """
    tags = CATEGORY_TAG_MAP.get(category.strip().lower())
    if not tags:
        supported = ", ".join(sorted(CATEGORY_TAG_MAP.keys()))
        raise PlacesAPIError(
            f"Categoría '{category}' no soportada. Categorías disponibles: {supported}"
        )
    seen_place_ids: set[str] = set()
    results: list[dict] = []
    with _ipv4_client() as client:
        bbox = _geocode_zone(zone, client)
        time.sleep(1)  # mismo respeto al rate limit que discover_businesses()
        elements = _overpass_query(bbox, tags, client)
    for element in elements:
        biz = _element_to_business_dict(element, zone, category)
        if biz is None:
            continue
        if biz["place_id"] in seen_place_ids:
            continue
        seen_place_ids.add(biz["place_id"])
        element_tags = element.get("tags", {})
        biz["website"] = element_tags.get("website") or element_tags.get("contact:website")
        results.append(biz)
    return results