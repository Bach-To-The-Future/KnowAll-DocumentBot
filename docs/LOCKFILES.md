# Lockfiles

CI installs with `npm ci` and hashed pip requirements. Both need a committed
lockfile; generate them **in Docker** so the result matches the build image
rather than whatever is on your laptop.

## Node — `frontend/package-lock.json`

```bash
docker run --rm -v "$PWD/frontend":/w -w /w node:22-alpine \
  npm install --package-lock-only --no-audit --no-fund
git add frontend/package-lock.json
```

Then switch the build stage in `frontend/Dockerfile` from `npm install` to
the reproducible form:

```dockerfile
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
```

Regenerate whenever `package.json` changes (`npm ci` fails loudly if the two
disagree — that failure is the point).

## Python — hashed `backend/api/requirements.txt`

Keep direct dependencies in `backend/api/requirements.in`, compile the full
transitive tree with hashes:

```bash
# one-time: move the current pinned list to the source file
git mv backend/api/requirements.txt backend/api/requirements.in

docker run --rm -v "$PWD/backend":/w -w /w python:3.12-slim sh -c \
  "pip install --no-cache-dir uv && \
   uv pip compile api/requirements.in \
     --generate-hashes --output-file api/requirements.txt"

git add backend/api/requirements.in backend/api/requirements.txt
```

`pip install -r api/requirements.txt` then enforces the hashes automatically:
any tampered or substituted artifact aborts the install.

Upgrade a pin by editing `requirements.in` and re-running the compile.

## Where they sit in CI

| Stage | Command | Guarantee |
|---|---|---|
| `frontend` | `npm ci` | Exact transitive tree; fails on lockfile drift |
| `backend` | `pip install -r api/requirements.txt` | Hash-verified transitive tree |
| `e2e` | `docker compose build` | Images built from the same locked inputs |
| `security` | Trivy `HIGH,CRITICAL` | Blocks known-vulnerable base layers |

Until both lockfiles are committed, builds are **not** reproducible: exact
pins in `package.json` / `requirements.txt` constrain direct dependencies
only, leaving every transitive dependency free to float.
