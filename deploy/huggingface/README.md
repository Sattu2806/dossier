---
title: Dossier API
emoji: 📚
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# Dossier — research API

Plans sub-questions, researches them in parallel, drafts a cited report and
fact-checks it against its sources. Source:
https://github.com/Sattu2806/dossier

This Space runs the API only. It is useless without a key, so every endpoint
returns 401 unless you send `Authorization: Bearer <key>`.

## Required secrets

Set these under **Settings → Variables and secrets**:

| secret | value |
|---|---|
| `GEMINI_API_KEY` | from aistudio.google.com |
| `TAVILY_API_KEY` | from tavily.com |
| `DOSSIER_DATABASE_URL` | `postgresql+psycopg://…` from Neon |
| `DOSSIER_BOOTSTRAP_EMAIL` | e.g. `demo@dossier.app` |
| `DOSSIER_BOOTSTRAP_KEY` | a key you invent, e.g. `dsr_` + random text |
| `DOSSIER_BOOTSTRAP_TOKEN_LIMIT` | `100000` |

The bootstrap pair exists because a Space has no shell: the first user is
seeded at startup instead of being created with `dossier user`.

Storage here is ephemeral, so uploaded documents do not survive a rebuild —
runs and users live in Neon, which does.
