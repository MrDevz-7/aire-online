# Conceptos de AirE_Online

Registro de los conceptos aprendidos en cada módulo del proyecto. Se completa al cerrar cada módulo, con un resumen corto de ideas (no de tareas).

## M1 — Monorepo y esqueleto del gateway

- **Git y monorepo:** git no guarda "renombres", guarda snapshots y los detecta por similitud de contenido; por eso mover archivos sin modificarlos (`git mv`, todos `R100`) conserva el historial. Un remote es solo una URL guardada, y renombrar el repo en GitHub redirige la URL vieja.
- **Gateway/BFF:** una puerta de entrada única entre el frontend y el engine, que queda interno; es el lugar donde después se agregan autenticación y límites sin repetirlos. CORS lo aplica el navegador, no el servidor: sirve para proteger a los usuarios, no es autenticación.
- **Middleware:** una cadena ordenada de funciones `(req, res, next)`; el orden define el comportamiento (helmet primero, el 404 después de las rutas, el manejador de errores al final, y `cors` responde el preflight antes de que llegue al logging).
- **`createApp` vs `listen` y configuración:** separar construir la app de abrir el puerto, e inyectar la config por parámetro, permite probar sin red. Las variables de entorno llegan como texto, así que se validan al arrancar (*fail fast*), con código de salida distinto de 0, y las del entorno real ganan sobre el `.env`.
- **Docker:** una imagen es la receta congelada y un contenedor es esa receta corriendo; el multi-stage deja el compilador fuera de la imagen final, el orden de las capas aprovecha la caché, y `CMD` en forma de lista hace que Node reciba `SIGTERM` y se apague ordenado.