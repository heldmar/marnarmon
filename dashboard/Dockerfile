# --- Build stage ---------------------------------------------------------- #
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

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
