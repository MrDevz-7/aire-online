"""
Test de humo para discover_businesses() usando un transporte HTTP simulado.

IMPORTANTE: este test NO llama a Nominatim/Overpass reales. Este entorno
(sandbox de Claude) no tiene salida de red hacia nominatim.openstreetmap.org
ni overpass-api.de, así que no se pudo probar la integración real desde
acá. Este test simula las respuestas de ambos servicios con la MISMA forma
que documentan sus APIs, para validar que el parsing/mapeo a dict de
negocio funciona correctamente. La prueba con las APIs reales queda para
que la corras tú (ver instrucciones aparte para probar con una zona real).

Correr con: python -m scrapers.test_maps_discovery_mock
"""
import httpx

from scrapers import maps_discovery


def fake_transport_handler(request: httpx.Request) -> httpx.Response:
    if "nominatim.openstreetmap.org" in str(request.url):
        return httpx.Response(
            200,
            json=[
                {
                    "boundingbox": ["6.230", "6.260", "-75.600", "-75.580"],
                    "lat": "6.244",
                    "lon": "-75.590",
                    "display_name": "Laureles, Medellín, Antioquia, Colombia",
                }
            ],
        )
    if "overpass-api.de" in str(request.url):
        return httpx.Response(
            200,
            json={
                "elements": [
                    {
                        "type": "node",
                        "id": 111111111,
                        "lat": 6.244,
                        "lon": -75.590,
                        "tags": {
                            "name": "Restaurante La Esquina",
                            "amenity": "restaurant",
                            "addr:street": "Cra 70",
                            "addr:housenumber": "45-12",
                            "phone": "+57 300 1234567",
                        },
                    },
                    {
                        "type": "way",
                        "id": 222222222,
                        "center": {"lat": 6.246, "lon": -75.591},
                        "tags": {
                            "name": "Pizzeria Don Luigi",
                            "amenity": "restaurant",
                            "website": "https://donluigi.example.com",
                        },
                    },
                    {
                        # Sin "name": debe descartarse (no sirve como lead)
                        "type": "node",
                        "id": 333333333,
                        "lat": 6.245,
                        "lon": -75.592,
                        "tags": {"amenity": "restaurant"},
                    },
                ]
            },
        )
    return httpx.Response(404, json={})


def run():
    mock_transport = httpx.MockTransport(fake_transport_handler)
    original_client = httpx.Client

    class PatchedClient(original_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = mock_transport
            super().__init__(*args, **kwargs)

    maps_discovery.httpx.Client = PatchedClient
    # No hay rate limit real contra un mock; evitamos el sleep(1) para que
    # el test corra instantáneo.
    maps_discovery.time.sleep = lambda _seconds: None

    results = maps_discovery.discover_businesses(zone="Laureles, Medellín", category="restaurantes")

    assert len(results) == 2, f"Se esperaban 2 negocios (el 3ro sin 'name' se descarta), llegaron {len(results)}"

    sin_web = next(r for r in results if r["name"] == "Restaurante La Esquina")
    con_web = next(r for r in results if r["name"] == "Pizzeria Don Luigi")

    assert sin_web["has_website"] is False
    assert con_web["has_website"] is True
    assert sin_web["rating"] is None, "OSM no tiene rating, siempre debe ser None"
    assert sin_web["review_count"] is None
    assert sin_web["zone"] == "Laureles, Medellín"
    assert sin_web["latitude"] == 6.244
    assert con_web["latitude"] == 6.246, "El centro de un 'way' debe usarse como lat/lon"
    assert sin_web["address"] == "Cra 70 45-12"

    print("OK - discover_businesses() parsea correctamente las respuestas simuladas de Nominatim + Overpass")
    print(f"Negocios encontrados: {len(results)}")
    print(f"Sin sitio web: {sum(1 for r in results if not r['has_website'])}")
    for r in results:
        print(" -", r["name"], "| has_website=", r["has_website"], "| place_id=", r["place_id"])


if __name__ == "__main__":
    run()