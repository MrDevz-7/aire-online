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
        string unidad
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
        int horas_con_lectura
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
    reportes {
        int id PK
        string tipo
        string alcance
        date fecha_referencia
        timestamptz generado_en
        jsonb datos_entrada
        string hash_datos
        text texto
        string origen_texto
        string modelo
        string motivo_fallback
    }