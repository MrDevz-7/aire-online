"""
Paquete del scheduler embebido (M10, D87).

El scheduler vive dentro del proceso de FastAPI. Los jobs llaman directo
a las funciones de servicio (D88), no hacen HTTP a `/internal/*` ni a
`/api/admin/*` de sí mismos. Se arranca y apaga desde el `lifespan` de
`api.main`, condicionado a `settings.SCHEDULER_ENABLED`.

Puntos de entrada:
    from scheduler.scheduler import iniciar_scheduler, detener_scheduler

Módulos:
    scheduler.py  — instancia del BackgroundScheduler y start/stop
    jobs.py       — funciones de los jobs y registro de CronTriggers
"""