# ---------- Etapa 1: compilar TypeScript ----------
FROM node:24-alpine AS build
WORKDIR /app

# Primero solo los manifiestos: esta capa (npm ci) se reutiliza mientras
# no cambien las dependencias.
COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json ./
COPY src ./src
RUN npm run build

# ---------- Etapa 2: imagen final, solo lo necesario para correr ----------
FROM node:24-alpine AS runtime
ENV NODE_ENV=production
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

COPY --from=build /app/dist ./dist

# La imagen oficial de Node ya trae un usuario sin privilegios llamado "node".
USER node

EXPOSE 4000

# Forma de lista: node queda como proceso principal y recibe SIGTERM directo.
CMD ["node", "dist/server.js"]