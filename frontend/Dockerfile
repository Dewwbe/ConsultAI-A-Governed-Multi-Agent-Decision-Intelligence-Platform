# Build the static app, then serve it with nginx. Build context: ./frontend
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# The API address is baked in at build time (it is public configuration, not a secret).
ARG VITE_API_BASE_URL=http://localhost:8000
ARG VITE_AUTH_MODE=dev
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL VITE_AUTH_MODE=$VITE_AUTH_MODE
RUN npm run build

FROM nginx:1.27-alpine
# nginx renders this template at start-up, substituting API_ORIGIN into the CSP.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
ENV API_ORIGIN=http://localhost:8000
EXPOSE 80
