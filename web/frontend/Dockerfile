FROM node:20-alpine AS build

WORKDIR /app

COPY web/frontend/package.json web/frontend/package-lock.json* ./
RUN npm install

COPY web/frontend/ ./
RUN npm run build

# Serve with nginx
FROM nginx:alpine

# Custom nginx config to proxy /api to backend
COPY web/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
