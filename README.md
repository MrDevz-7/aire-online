# AirE_Online

Proyecto en construcción: reconciliación y auditoría de calidad del aire
para Colombia. Nace de la reestructuración de CustoFinder, reutilizando
parte de su base de código.

> Estado actual del desarrollo: [`docs/ESTADO_PROYECTO.md`](./docs/ESTADO_PROYECTO.md)

## Estructura

- [`engine/`](./engine/) — servicio backend (FastAPI + PostgreSQL + SQLAlchemy).
- [`gateway/`](./gateway/) — gateway API (Express + TypeScript).
- [`frontend/`](./frontend/) — interfaz web (Next.js).
- [`docs/`](./docs/) — decisiones técnicas y estado del proyecto.