"""
Scraper de sitios de competencia. Dos responsabilidades:
1. find_competitors_with_website(): descubre negocios cercanos (misma
   zona/categoría) que sí tienen sitio web, reutilizando maps_discovery.py.
2. analyze_competitor_site(s)(): visita cada sitio con Playwright y detecta,
   con heurísticas de texto conservadoras, si tiene menú online, reservas,
   e-commerce o blog. Prioriza falsos negativos sobre falsos positivos: si
   no hay señal reconocible, se marca False, no se adivina. Un sitio caído
   o lento nunca tumba el batch completo — cada análisis atrapa sus propios
   errores en el campo "error" del resultado.
"""
import logging
from playwright.sync_api import Browser, TimeoutError as PlaywrightTimeoutError, sync_playwright
from scrapers.maps_discovery import PlacesAPIError, find_businesses_with_website_url

logger = logging.getLogger(__name__)

# Si un sitio individual tarda más que esto, se abandona y se sigue con
# el siguiente, en vez de colgar todo el batch.
SITE_TIMEOUT_MS = 10_000

# Heurísticas de texto (comparadas contra <body> en minúsculas). Listas
# conservadoras a propósito: mejor pocas palabras específicas que muchas
# genéricas que generen falsos positivos.
MENU_KEYWORDS = ["menú", "menu", "carta", "nuestros platos", "food menu"]
BOOKING_KEYWORDS = [
    "reservar", "reserva tu", "reserva ahora", "agendar cita", "agenda tu cita",
    "pedir cita", "book now", "book a table", "booking",
]
ECOMMERCE_KEYWORDS = [
    "añadir al carrito", "agregar al carrito", "add to cart", "carrito de compras",
    "comprar ahora", "finalizar compra", "checkout",
]
BLOG_KEYWORDS = ["blog", "últimas noticias", "últimas novedades", "artículos recientes"]


def find_competitors_with_website(business: dict, limit: int = 5) -> list[dict]:
    """Busca hasta `limit` negocios cercanos (misma zona/categoría que
    `business`, dict con al menos place_id/zone/category) que tengan sitio
    web. Excluye al propio negocio por place_id. Nunca lanza excepción: si
    OSM falla, loguea y devuelve lista vacía — mejor un lead sin
    competencia analizada que un endpoint que responde 500."""
    zone = business.get("zone")
    category = business.get("category")
    if not zone or not category:
        logger.warning(
            "Lead con business_id=%s no tiene zone/category cargados; "
            "no se puede buscar competencia.",
            business.get("place_id"),
        )
        return []
    try:
        candidates = find_businesses_with_website_url(zone=zone, category=category)
    except PlacesAPIError as exc:
        logger.error("No se pudo buscar competencia vía OSM para zone=%s category=%s: %s",
                     zone, category, exc)
        return []
    own_place_id = business.get("place_id")
    competitors = [
        c for c in candidates
        if c.get("website") and c.get("place_id") != own_place_id
    ]
    return competitors[:limit]


def _detect_features(page) -> dict:
    """Corre las heurísticas de texto/selector sobre una página ya cargada."""
    try:
        text = page.inner_text("body").lower()
    except Exception:
        # Sitio raro (todo en iframes, etc.): texto vacío hace que todas
        # las heurísticas den False, que es el resultado conservador correcto.
        text = ""
    has_online_menu = any(keyword in text for keyword in MENU_KEYWORDS)
    has_booking = any(keyword in text for keyword in BOOKING_KEYWORDS)
    if not has_booking:
        try:
            has_booking = page.locator(
                "a[href*='calendly'], iframe[src*='calendly'], a[href*='booking.com'], "
                "a[href*='reservas'], a[href*='booksy']"
            ).count() > 0
        except Exception:
            pass
    has_ecommerce = any(keyword in text for keyword in ECOMMERCE_KEYWORDS)
    if not has_ecommerce:
        try:
            has_ecommerce = page.locator(
                "[class*='cart'], [id*='cart'], a[href*='/cart'], a[href*='/checkout'], "
                "a[href*='shopify'], form[action*='cart']"
            ).count() > 0
        except Exception:
            pass
    has_blog = any(keyword in text for keyword in BLOG_KEYWORDS)
    if not has_blog:
        try:
            has_blog = page.locator("a[href*='/blog'], a[href*='/noticias']").count() > 0
        except Exception:
            pass
    return {
        "has_online_menu": has_online_menu,
        "has_booking": has_booking,
        "has_ecommerce": has_ecommerce,
        "has_blog": has_blog,
    }


def _analyze_with_browser(browser: Browser, url: str) -> dict:
    """Analiza un sitio reutilizando un navegador ya abierto (uso interno)."""
    result = {
        "competitor_url": url,
        "has_online_menu": False,
        "has_booking": False,
        "has_ecommerce": False,
        "has_blog": False,
        "error": None,
    }
    normalized_url = url if url.startswith(("http://", "https://")) else f"https://{url}"
    page = browser.new_page()
    try:
        page.set_default_timeout(SITE_TIMEOUT_MS)
        try:
            # domcontentloaded (no "load"/"networkidle"): no hace falta
            # esperar TODOS los recursos para las heurísticas de texto.
            # Playwright sigue redirects automáticamente.
            page.goto(normalized_url, timeout=SITE_TIMEOUT_MS, wait_until="domcontentloaded")
        except PlaywrightTimeoutError:
            result["error"] = f"Timeout: el sitio no respondió en {SITE_TIMEOUT_MS // 1000}s"
            return result
        except Exception as exc:
            result["error"] = f"No se pudo cargar el sitio: {exc}"
            return result
        result["competitor_url"] = page.url  # URL final, después de redirects
        result.update(_detect_features(page))
    finally:
        page.close()
    return result


def analyze_competitor_site(url: str) -> dict:
    """Analiza UN sitio suelto, abriendo y cerrando su propio Chromium.
    Para varios sitios usar analyze_competitor_sites() — reutiliza un
    solo navegador y es mucho más rápido."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            return _analyze_with_browser(browser, url)
        finally:
            browser.close()


def analyze_competitor_sites(urls: list[str]) -> list[dict]:
    """Versión batch: un solo Chromium reutilizado para todas las URLs.
    Un sitio que falle (timeout, DNS, certificado) no aborta el resto —
    su dict trae "error" con el detalle y se sigue con el siguiente."""
    if not urls:
        return []
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for url in urls:
                results.append(_analyze_with_browser(browser, url))
        finally:
            browser.close()
    return results