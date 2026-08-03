# All tooling runs in Docker (no host Node required). package-lock.json is
# committed and authoritative: `npm ci` installs it byte-for-byte and FAILS if
# it disagrees with package.json, which is the reproducibility guarantee
# `npm install` cannot give. Regenerate it only in this same base image
# (node:22-alpine) — a lockfile built on glibc omits the musl optional
# binaries that lightningcss/oxide/swc need here.
# Base image pinned BY DIGEST, not by tag (finding #25): node:22-alpine is
# republished frequently, and a tag-only build is not reproducible.
#   node:22-alpine as of 2026-07-14
FROM node@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS run
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
