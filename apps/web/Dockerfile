# Multi-stage Dockerfile for the React SPA.
#
# - `dev`: runs `vite dev`, source bind-mounted by docker-compose.override.yml
# - `production`: builds static assets and serves them via Caddy file_server.

# ---------- base ----------
FROM node:22-alpine AS base
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install

# ---------- dev ----------
FROM base AS dev
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# ---------- build ----------
FROM base AS build
COPY . .
RUN npm run build

# ---------- production ----------
# Serve the static build with Caddy file_server. Caddy on the host's reverse
# proxy network will proxy here for non-/api/* traffic.
FROM caddy:2-alpine AS production

# Minimal Caddyfile that serves the SPA with HTML5 history fallback.
COPY <<'CADDY' /etc/caddy/Caddyfile
:80 {
    root * /srv
    try_files {path} /index.html
    file_server
    encode zstd gzip
}
CADDY

COPY --from=build /app/dist /srv
EXPOSE 80
