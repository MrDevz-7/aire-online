# Conceptos de AirE_Online

Registro de los conceptos aprendidos en cada módulo del proyecto. Se completa al cerrar cada módulo, con un resumen corto de ideas (no de tareas).

## M1 — Monorepo y esqueleto del gateway

- **Git y monorepo:** git no guarda "renombres", guarda snapshots y los detecta por similitud de contenido; por eso mover archivos sin modificarlos (`git mv`, todos `R100`) conserva el historial. Un remote es solo una URL guardada, y renombrar el repo en GitHub redirige la URL vieja.
- **Gateway/BFF:** una puerta de entrada única entre el frontend y el engine, que queda interno; es el lugar donde después se agregan autenticación y límites sin repetirlos. CORS lo aplica el navegador, no el servidor: sirve para proteger a los usuarios, no es autenticación.
- **Middleware:** una cadena ordenada de funciones `(req, res, next)`; el orden define el comportamiento (helmet primero, el 404 después de las rutas, el manejador de errores al final, y `cors` responde el preflight antes de que llegue al logging).
- **`createApp` vs `listen` y configuración:** separar construir la app de abrir el puerto, e inyectar la config por parámetro, permite probar sin red. Las variables de entorno llegan como texto, así que se validan al arrancar (*fail fast*), con código de salida distinto de 0, y las del entorno real ganan sobre el `.env`.
- **Docker:** una imagen es la receta congelada y un contenedor es esa receta corriendo; el multi-stage deja el compilador fuera de la imagen final, el orden de las capas aprovecha la caché, y `CMD` en forma de lista hace que Node reciba `SIGTERM` y se apague ordenado.
## M1.1 — Higiene y seguridad

- **Rotar vs. revocar vs. borrar una clave filtrada:** borrarla del archivo actual no alcanza porque sigue viva en el historial de git; revocarla antes de tener el reemplazo funcionando corta el servicio. Rotar es el orden correcto: activar la clave nueva en todos lados, verificar que funciona, y recién ahí matar la vieja — nunca hay una ventana sin ninguna clave válida.
- **`git rm --cached` vs. borrar un archivo:** `--cached` saca el archivo del índice de git (deja de subirse) pero lo conserva en disco; sin `--cached`, git lo borra de los dos lados. Y estar en `.gitignore` no destrackea nada retroactivo: eso previene que un archivo *nuevo* se trackee, no afecta a uno que ya lo estaba.
- **Por qué no se reescribe el historial tras una fuga:** una clave revocada es un string inútil aunque siga visible en commits viejos — el riesgo real ya está neutralizado por la rotación, no por ocultarla. Reescribir historial (`filter-repo`/BFG) cambia el hash de todos los commits posteriores a la fuga, rompiendo cualquier referencia existente (tags, clones) para un beneficio que ya se consiguió gratis.
- **`.gitattributes`:** vive en el repo (a diferencia de `core.autocrlf`, que es config local de cada máquina) y fija una política de fin de línea explícita para cualquiera que clone, sin depender de la configuración personal de cada colaborador.
- **Auto-deploy:** republica el servicio solo con cada push a la rama configurada. Pausarlo no afecta lo que ya está corriendo; evita que pushes intermedios de un desarrollo en curso lleguen a producción antes de estar listos.
- **Cambiar una env var en un servicio ya corriendo no alcanza:** un proceso solo lee sus variables de entorno al arrancar: hace falta un restart o deploy para que una rotación de credenciales sea efectiva, aunque el panel ya muestre el valor nuevo guardado.
