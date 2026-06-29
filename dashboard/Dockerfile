# --- Build stage ---------------------------------------------------------- #
FROM node:22-alpine AS build
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
WORKDIR /app
# Use pnpm via Corepack; the exact version is pinned by package.json
# ("packageManager": "pnpm@..."), so the build is reproducible.
RUN corepack enable
# Install deps first (separate layer for better caching). --frozen-lockfile
# fails if pnpm-lock.yaml is out of sync with package.json, so CI never silently
# drifts. pnpm-workspace.yaml carries the supply-chain policy (minimumReleaseAge).
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm run build

# --- Runtime stage -------------------------------------------------------- #
FROM nginx:1.27-alpine
# SPA routing config
COPY nginx.conf /etc/nginx/conf.d/default.conf
# Built static assets
COPY --from=build /app/dist /usr/share/nginx/html
# Runtime config generator: nginx base image runs *.sh in this dir before start,
# so config.js is rebuilt from env vars on every container start.
COPY docker-entrypoint.sh /docker-entrypoint.d/40-marnarmon-config.sh
RUN chmod +x /docker-entrypoint.d/40-marnarmon-config.sh

EXPOSE 80
# (nginx base image provides the entrypoint + CMD)
