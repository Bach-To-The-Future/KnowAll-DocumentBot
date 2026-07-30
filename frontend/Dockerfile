# All tooling runs in Docker (no host Node required). package-lock.json is
# committed and authoritative: `npm ci` installs it byte-for-byte and FAILS if
# it disagrees with package.json, which is the reproducibility guarantee
# `npm install` cannot give. Regenerate it only in this same base image
# (node:22-alpine) — a lockfile built on glibc omits the musl optional
# binaries that lightningcss/oxide/swc need here.
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
# Standalone output: server.js + pruned node_modules only.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
