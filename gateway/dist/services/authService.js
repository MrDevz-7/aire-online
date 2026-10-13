"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.crearAuthService = crearAuthService;
// gateway/src/services/authService.ts
const node_crypto_1 = require("node:crypto");
const errorHandler_1 = require("../middlewares/errorHandler");
const jwt_1 = require("../security/jwt");
const password_1 = require("../security/password");
const tokens_1 = require("../security/tokens");
const internalClient_1 = require("./internalClient");
/** Se calcula UNA vez y se reutiliza en cada login con usuario
 *  inexistente. Su único fin es gastar el mismo tiempo que un
 *  `verifyPassword` real, para no filtrar por timing si el email existe
 *  o no (D78, errores genéricos). */
let HASH_FICTICIO = null;
async function hashFicticio() {
    if (HASH_FICTICIO === null) {
        HASH_FICTICIO = await (0, password_1.hashPassword)("ficticio-para-timing-de-login");
    }
    return HASH_FICTICIO;
}
function userFromUsuario(u) {
    return { id: u.id, email: u.email, rol: u.rol };
}
function fallarCredenciales() {
    throw new errorHandler_1.HttpError(401, "INVALID_CREDENTIALS", "Email o contraseña incorrectos");
}
function crearAuthService(config, http = {
    post: internalClient_1.callInternalPost,
    get: internalClient_1.callInternalGet,
}) {
    const client = {
        engineUrl: config.engineUrl,
        internalApiToken: config.internalApiToken,
        defaultTimeoutMs: config.engineTimeoutMs,
    };
    function opts() {
        return { requestId: (0, node_crypto_1.randomUUID)() };
    }
    function nuevoRefresh() {
        const token = (0, tokens_1.generarRefreshToken)();
        const hash = (0, tokens_1.hashRefreshToken)(token);
        const expira = new Date(Date.now() + config.refreshTtlS * 1000);
        return { token, hash, expira };
    }
    async function login(input) {
        // 1. Buscar usuario por email. Si no existe, hacemos un hash ficticio
        //    para no filtrar por tiempo la existencia del email (D78).
        let usuario;
        try {
            usuario = await http.get(client, "/internal/usuarios/por-email", { email: input.email }, opts());
        }
        catch (err) {
            if (err instanceof errorHandler_1.HttpError && err.status === 404) {
                // Consume tiempo de scrypt para igualar el caso "usuario existe,
                // password incorrecta".
                await (0, password_1.verifyPassword)(input.password, await hashFicticio());
                return fallarCredenciales();
            }
            throw err;
        }
        // 2. Verificar contraseña. Mismo mensaje si falla (D78).
        const ok = await (0, password_1.verifyPassword)(input.password, usuario.password_hash);
        if (!ok || !usuario.activo) {
            return fallarCredenciales();
        }
        // 3. Crear la sesión de refresco en el engine. Guardamos SOLO el
        //    hash: el token en claro lo tiene el cliente.
        const refresh = nuevoRefresh();
        await http.post(client, "/internal/sesiones", {
            usuario_id: usuario.id,
            token_hash: refresh.hash,
            expira_en: refresh.expira.toISOString(),
            registrar_login: true,
        }, opts());
        // 4. Firmar el access token.
        const accessToken = (0, jwt_1.signAccessToken)({ sub: usuario.id, rol: usuario.rol }, { secret: config.jwtSecret, ttlSeconds: config.jwtAccessTtlS });
        return {
            accessToken,
            expiresIn: config.jwtAccessTtlS,
            user: userFromUsuario(usuario),
            refreshToken: refresh.token,
            refreshExpiresAt: refresh.expira,
        };
    }
    async function refresh(refreshToken) {
        // 1. Rotación atómica: el engine valida el token actual, lo revoca,
        //    crea el nuevo y devuelve el usuario. Si el token ya fue rotado,
        //    el engine revoca TODAS las sesiones activas del usuario (D77).
        const nuevo = nuevoRefresh();
        let rotado;
        try {
            rotado = await http.post(client, "/internal/sesiones/rotar", {
                token_hash_actual: (0, tokens_1.hashRefreshToken)(refreshToken),
                token_hash_nuevo: nuevo.hash,
                expira_en_nuevo: nuevo.expira.toISOString(),
            }, opts());
        }
        catch (err) {
            if (err instanceof errorHandler_1.HttpError && err.status === 401) {
                throw new errorHandler_1.HttpError(401, "INVALID_REFRESH", "Sesión inválida o vencida");
            }
            throw err;
        }
        // 2. Firmar access token nuevo.
        const accessToken = (0, jwt_1.signAccessToken)({ sub: rotado.usuario.id, rol: rotado.usuario.rol }, { secret: config.jwtSecret, ttlSeconds: config.jwtAccessTtlS });
        return {
            accessToken,
            expiresIn: config.jwtAccessTtlS,
            user: userFromUsuario(rotado.usuario),
            refreshToken: nuevo.token,
            refreshExpiresAt: nuevo.expira,
        };
    }
    async function logout(refreshToken) {
        try {
            await http.post(client, "/internal/sesiones/revocar", { token_hash: (0, tokens_1.hashRefreshToken)(refreshToken) }, opts());
        }
        catch {
            // Logout es best-effort: si el engine falla, igual borramos la
            // cookie en el gateway. El usuario no debe quedar "atrapado".
        }
    }
    async function me(userId) {
        return http.get(client, `/internal/usuarios/${userId}`, {}, opts());
    }
    return { login, refresh, logout, me };
}
//# sourceMappingURL=authService.js.map