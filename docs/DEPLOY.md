# Deploying dossier

## What the architecture demands

Two properties rule out serverless for the **API**, and they are worth knowing
before choosing a host:

1. **Work continues after the response.** `POST /api/research` returns `202`
   and then runs the graph in a background task. Serverless platforms freeze or
   kill the execution context once a response is sent, so the run would die
   silently. Making the API serverless means rewriting it into a queue plus a
   worker.
2. **The vector index is on disk.** Chroma persists to `DOSSIER_DATA_DIR`, so
   the API needs a **persistent volume**. (See "Dropping the volume" below for
   the pgvector alternative.)

Add SSE connections held open for the length of a run — measured up to 32s, and
longer when a draft is revised three times — and the API wants an ordinary
long-lived container.

The **web app** has no such constraints and could live anywhere.

## Free: Hugging Face Spaces + Neon + Vercel

No card, three signups, ~20 minutes. This is the cheapest arrangement that
still satisfies the two constraints above.

| piece | host | why it fits |
|---|---|---|
| API | Hugging Face Space (Docker) | free CPU Basic is 2 vCPU / 16 GB RAM, runs any Dockerfile, supports secrets, and only pauses after **48 hours** idle |
| Postgres | Neon free | the Space's disk is wiped on rebuild, so runs and users must live elsewhere |
| Web | Vercel free | its natural home |

What you give up: uploaded documents do not survive a Space rebuild (no
persistent volume on the free tier), and the Space pauses after two idle days,
taking ~30s to wake.

### 1. Neon — the database

Sign up at [neon.tech](https://neon.tech) with GitHub, create a project, copy
the connection string, and **change the scheme** from `postgresql://` to
`postgresql+psycopg://`. SQLAlchemy needs the driver named; this is the single
most common way this deploy fails.

### 2. The Space — the API

Create a **Docker** Space at [huggingface.co/new-space](https://huggingface.co/new-space)
(name it `dossier`, hardware CPU basic — free). Then push the two files from
`deploy/huggingface/` into it:

```bash
git clone https://huggingface.co/spaces/<your-hf-user>/dossier /tmp/dossier-space
cp deploy/huggingface/{Dockerfile,README.md} /tmp/dossier-space/
cd /tmp/dossier-space && git add -A && git commit -m "Deploy dossier API" && git push
```

That Dockerfile installs the package from GitHub, so the Space repo stays two
files and every rebuild picks up your latest `main`.

Then set these under **Settings → Variables and secrets**:

| secret | value |
|---|---|
| `GEMINI_API_KEY` | your key |
| `TAVILY_API_KEY` | your key |
| `DOSSIER_DATABASE_URL` | the Neon string, with `postgresql+psycopg://` |
| `DOSSIER_BOOTSTRAP_EMAIL` | `demo@dossier.app` |
| `DOSSIER_BOOTSTRAP_KEY` | invent one, e.g. `dsr_` plus random text |
| `DOSSIER_BOOTSTRAP_TOKEN_LIMIT` | `100000` |

A Space has **no shell**, so `dossier user` cannot be run there. The bootstrap
pair seeds that first user at startup instead — idempotent, so restarts are
safe and re-deploys do not rotate a working key.

Check it: `curl https://<your-hf-user>-dossier.hf.space/health`

### 3. Vercel — the web app

Import the GitHub repo at [vercel.com/new](https://vercel.com/new), set **Root
Directory** to `web`, and add one environment variable:

`DOSSIER_API_URL = https://<your-hf-user>-dossier.hf.space`

Open the deployed site and paste the bootstrap key into the connect screen.

One caveat: the SSE proxy route holds a connection open for the length of a
run, and Hobby functions cap at 60s. A three-draft run can be cut — it
degrades rather than breaks, because `EventSource` reconnects and
`RunChannel` replays the events that were missed.

## Paid, if the free tier chafes: Railway, one project, three services

Railway is the least ceremony for this shape: managed Postgres, volumes and
Dockerfile builds in one project, with private networking between services and
no cold-start sleeping.

### 1. Postgres

New Project → **Deploy PostgreSQL**. Railway sets `DATABASE_URL` on the
service; you will reference it from the API below.

### 2. The API

**New Service → GitHub repo → `Sattu2806/dossier`**, root directory `/`
(it will use the top-level `Dockerfile`).

Variables:

| variable | value |
|---|---|
| `DOSSIER_DATABASE_URL` | `postgresql+psycopg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}` |
| `GEMINI_API_KEY` | your key |
| `TAVILY_API_KEY` | your key |
| `DOSSIER_DATA_DIR` | `/data/chroma` |
| `DOSSIER_DAILY_TOKEN_LIMIT` | `200000` (see "A public demo" below) |
| `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` | optional, for traces |

Note the driver prefix: SQLAlchemy needs `postgresql+psycopg://`, while
Railway's own `DATABASE_URL` starts `postgresql://`. Copying it unchanged is
the most common way this deploy fails.

Then **Settings → Volumes → add a volume mounted at `/data`** (1 GB is plenty),
and set the health check path to `/health`. Do not set `PORT`: Railway injects
it, and `api.port()` already prefers it.

### 3. The web app

**New Service → same repo**, root directory `web` (it will use
`web/Dockerfile`).

| variable | value |
|---|---|
| `DOSSIER_API_URL` | `http://${{dossier-api.RAILWAY_PRIVATE_DOMAIN}}:8500` |

Using the private domain keeps API traffic off the public internet, and means
the API does not need a public URL at all — only the web service does. Generate
a public domain for the web service only.

### 4. Create a user

Railway's shell, on the API service:

```bash
dossier user you@example.com
```

It prints the key once. Paste it into the web app's connect screen.

## Alternative: Render

Same shape, different buttons: a **Web Service** from the Dockerfile with a
**Disk** mounted at `/data`, plus **Render Postgres**. The free tier spins
services down after inactivity, which means a ~50 second cold start on the
first visit — poor for a portfolio link someone clicks once. Paid instances
start at $7/service.

## Why not Vercel for the API

Vercel is the natural home for the **web app** and nothing is wrong with
splitting it off. Two things to know if you do:

- The SSE proxy route holds a connection open for the whole run. Hobby
  functions cap at 60s, so a three-draft run can be cut off. It degrades
  rather than breaks — `EventSource` reconnects and `RunChannel` replays the
  events it missed — but the tail of a long run may reconnect once.
- `DOSSIER_API_URL` must then be the API's **public** URL, and the API needs a
  public domain.

The API itself cannot go on Vercel at all, for the two reasons at the top.

## A public demo

Every endpoint requires a key, so a recruiter opening the link sees the connect
screen and stops. If you want a live demo:

1. Create a demo user with a small budget:
   `dossier user demo@yourdomain --daily-token-limit 100000`
2. Publish that key in the README.

`DOSSIER_DAILY_TOKEN_LIMIT` then caps the damage: the key is shared, the budget
is not, and a 429 is returned before any paid call once the day's allowance is
gone. Roughly 100k tokens is a dozen or so reports.

## Dropping the volume (optional, later)

The volume exists only for Chroma. Moving vectors into the Postgres you already
run — `pgvector`, via `langchain-postgres` — would leave the API stateless and
deployable anywhere, including platforms without disks. `docstore.py` is a
single seam: `ingest`, `doc_search`, `document_count`. That is the change, and
the tests already fake the store, so they would not need rewriting.

## Before you click deploy

- [ ] `uv run pytest` passes (139 tests, no keys required)
- [ ] `docker compose up --build` works locally — **these images have never
      been built**; there was no Docker daemon on the machine that wrote them,
      so expect to fix something the first time
- [ ] GitHub repository secrets set, if you want the nightly eval job:
      `GEMINI_API_KEY`, `TAVILY_API_KEY`, `LANGSMITH_API_KEY`
- [ ] A run through the deployed UI end to end, watching the API logs
