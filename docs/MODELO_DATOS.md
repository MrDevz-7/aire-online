# Modelo de datos de AirE_Online

Base de datos: PostgreSQL 17 (misma mayor que Supabase). Esquema definido en
`engine/database/models.py` y versionado con Alembic (`engine/alembic/versions/`).

```mermaid
erDiagram
    estaciones ||--o{ lecturas : "tiene"
    estaciones ||--o{ emparejamientos : "estacion_a"
    estaciones ||--o{ emparejamientos : "estacion_b"
    emparejamientos ||--o{ comparaciones : "produce"
    estaciones ||--o{ pronosticos : "tiene"
    pronosticos ||--o| auditorias_pronostico : "se audita en"
    estaciones |o--o{ auditorias_pronostico : "estacion_real"
    estaciones |o--o{ alertas : "dispara"
    emparejamientos |o--o{ alertas : "dispara"

    estaciones {
        int id PK
        string fuente
        string id_externo
        string nombre
        float latitud
        float longitud
        string departamento
        string municipio
        boolean activa
        timestamptz primera_vez_vista
        timestamptz ultima_vez_vista
        jsonb metadatos
    }
    lecturas {
        int id PK
        int estacion_id FK
        string contaminante
        float valor
        string unidad
        timestamptz medido_en
        timestamptz capturado_en
    }
    emparejamientos {
        int id PK
        int estacion_a_id FK
        int estacion_b_id FK
        float distancia_km
        timestamptz creado_en
        boolean activo
    }
    comparaciones {
        int id PK
        int emparejamiento_id FK
        string contaminante
        timestamptz ventana_inicio
        timestamptz ventana_fin
        float valor_a
        float valor_b
        string unidad_comun
        float diferencia_abs
        timestamptz calculada_en
    }
    pronosticos {
        int id PK
        string fuente
        int estacion_id FK
        string contaminante
        date fecha_objetivo
        float valor_promedio
        float valor_min
        float valor_max
        date fecha_captura
        timestamptz capturado_en
    }
    auditorias_pronostico {
        int id PK
        int pronostico_id FK
        string estado
        float valor_real
        float error_abs
        float error_rel
        float sesgo
        string fuente_real
        int estacion_real_id FK
        float distancia_km_real
        int n_lecturas_real
        timestamptz resuelta_en
    }
    alertas {
        int id PK
        string tipo
        string severidad
        string estado
        int estacion_id FK
        int emparejamiento_id FK
        string contaminante
        float valor_disparador
        float umbral
        string mensaje
        timestamptz creada_en
        timestamptz actualizada_en
        timestamptz resuelta_en
    }
```

## Qué guarda cada tabla

- **estaciones**: una estación física según UNA fuente; la misma estación real puede aparecer una vez por fuente (UNIQUE `fuente + id_externo`).
- **lecturas**: una medición observada, con valor y unidad nativos de la fuente (sin convertir); una por estación, contaminante e instante.
- **emparejamientos**: vínculo entre dos estaciones de fuentes distintas que se consideran la misma zona; cada par se guarda una vez, en orden canónico (`a < b`).
- **comparaciones**: resultado de comparar dos lecturas emparejadas en una ventana de tiempo; lo llena M5.
- **pronosticos**: valor pronosticado capturado de una fuente (hoy AQICN); se guarda lo mínimo para auditar y la API pública expondrá métricas derivadas, no esta serie cruda.
- **auditorias_pronostico**: el veredicto sobre un pronóstico (valor real, error, sesgo); una por pronóstico.
- **alertas**: tarjetas del kanban; un índice único parcial impide dos alertas abiertas iguales.

## Convenciones

- Nombres en español, snake_case, sin tildes; tablas en plural.
- Enumeraciones como VARCHAR + CHECK (no ENUM nativo de Postgres).
- Timestamps `timestamptz` en UTC. Las fechas de `pronosticos` son `date` en hora local de Colombia.
- El horizonte de un pronóstico (`fecha_objetivo - fecha_captura`) no se guarda: es un dato derivado y se calcula al consultar.
- Sin PostGIS: la distancia entre estaciones se calcula en Python (M5).
- Sin datos semilla ni tabla de usuarios (llega en M8).

## Reglas que la base NO puede garantizar

- Que las dos estaciones de un emparejamiento sean de fuentes distintas (un CHECK no puede consultar otra tabla): la aplica M5 al crear el emparejamiento.