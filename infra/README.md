# Infra

`docker-compose.yml` stays at the repository root deliberately: `docker
compose up` works with zero flags, and build contexts (`./backend`,
`./frontend`) stay short. This directory holds everything else
infrastructure-related as it grows (reverse-proxy configs, k8s manifests,
CI pipelines).

## Topology

```
browser ──► web (Next.js :3000)
              │  /api/backend/[...path] route handler
              │  injects X-API-Key server-side (same-origin: no CORS)
              ▼
            api (FastAPI :8000) ──► qdrant / minio / ollama / redis
            worker (arq)  ◄──────── redis queue
```

No separate reverse proxy is required: the Next.js Route Handler *is* the
proxy, and unlike `next.config` rewrites it can inject the auth header. If
TLS termination or multi-service routing is needed later, put Caddy/Traefik
config here and point it at `web:3000` + `api:8000`.
