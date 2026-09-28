"""
Prueba end-to-end de POST /api/search.

Igual que en test_maps_discovery_mock.py: este sandbox no tiene salida
de red hacia places.googleapis.com, así que no pude pegarle a la Google
Places API real. Este script reemplaza discover_businesses() por datos
simulados (misma forma que produciría la función real) para validar
TODO lo demás: creación de SearchRun, upsert de Business, conteo de
leads_without_website, y que los datos queden persistidos en Postgres.

Correr con: ./venv/bin/python -m scrapers.test_search_endpoint_e2e
"""
from fastapi.testclient import TestClient

import api.main as main_module
from database.session import SessionLocal
from database.models import Business, SearchRun


FAKE_BUSINESSES = [
    {
        "place_id": "E2E_PLACE_1",
        "name": "Restaurante La Esquina",
        "category": "restaurant",
        "address": "Cra 70 #45-12, Laureles, Medellín",
        "zone": "Laureles, Medellín",
        "phone": "+57 300 1234567",
        "has_website": False,
        "rating": 4.3,
        "review_count": 87,
        "latitude": 6.244,
        "longitude": -75.590,
    },
    {
        "place_id": "E2E_PLACE_2",
        "name": "Pizzeria Don Luigi",
        "category": "restaurant",
        "address": "Cra 73 #34-20, Laureles, Medellín",
        "zone": "Laureles, Medellín",
        "phone": None,
        "has_website": True,
        "rating": 4.7,
        "review_count": 210,
        "latitude": 6.246,
        "longitude": -75.591,
    },
    {
        "place_id": "E2E_PLACE_3",
        "name": "Comidas Rapidas El Parche",
        "category": "restaurant",
        "address": "Cra 76 #40-01, Laureles, Medellín",
        "zone": "Laureles, Medellín",
        "phone": "+57 300 9998877",
        "has_website": False,
        "rating": 4.0,
        "review_count": 32,
        "latitude": 6.243,
        "longitude": -75.593,
    },
]


def fake_discover_businesses(zone: str, category: str):
    print(f"[mock] discover_businesses llamado con zone={zone!r} category={category!r}")
    return FAKE_BUSINESSES


def run():
    # Monkeypatch: reemplazamos la función real por la simulada SOLO en
    # el módulo api.main (que es donde el endpoint la llama).
    main_module.discover_businesses = fake_discover_businesses

    client = TestClient(main_module.app)

    # --- Primera corrida: deben insertarse 3 negocios nuevos ---
    response = client.post(
        "/api/search",
        json={"zone": "Laureles, Medellín", "category": "restaurantes"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    print("Respuesta 1ra corrida:", data)
    assert data["businesses_found"] == 3
    assert data["leads_without_website"] == 2  # PLACE_1 y PLACE_3 no tienen web

    run_id_1 = data["run_id"]

    # --- Verificamos directo en Postgres ---
    db = SessionLocal()
    businesses = db.query(Business).filter(Business.zone == "Laureles, Medellín").all()
    print(f"Negocios en DB tras 1ra corrida: {len(businesses)}")
    assert len(businesses) == 3

    search_run = db.query(SearchRun).filter(SearchRun.id == run_id_1).first()
    assert search_run is not None
    assert search_run.zone == "Laureles, Medellín"
    db.close()

    # --- Segunda corrida (misma zona/categoría): NO debe duplicar negocios ---
    response2 = client.post(
        "/api/search",
        json={"zone": "Laureles, Medellín", "category": "restaurantes"},
    )
    assert response2.status_code == 200, response2.text
    data2 = response2.json()
    print("Respuesta 2da corrida (repetida):", data2)

    db = SessionLocal()
    businesses_after = db.query(Business).filter(Business.zone == "Laureles, Medellín").all()
    print(f"Negocios en DB tras 2da corrida (debe seguir en 3, no 6): {len(businesses_after)}")
    assert len(businesses_after) == 3, "El upsert por place_id no está funcionando (hay duplicados)"

    runs_count = db.query(SearchRun).count()
    print(f"SearchRuns totales en DB: {runs_count} (deben ser 2, una por cada llamada)")
    assert runs_count == 2
    db.close()

    print("\nOK - Flujo end-to-end de POST /api/search validado: SearchRun + upsert de Business + conteos correctos.")


if __name__ == "__main__":
    run()
