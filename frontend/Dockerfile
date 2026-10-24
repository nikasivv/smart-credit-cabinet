# 1. Сборка TypeScript
FROM node:22.12.0-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY tsconfig.json ./
COPY src ./src
RUN npm run build

# 2. Раздача статики и проксирование API
FROM nginx:1.27.3-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY public /usr/share/nginx/html
COPY --from=build /web/dist /usr/share/nginx/html/js
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
