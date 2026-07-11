# bookworm (glibc) instead of alpine: the lockfile is generated on a glibc host,
# and npm's optional-deps handling skips the musl rollup binary (npm/cli#4828)
FROM node:20-bookworm-slim AS build

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 5173
