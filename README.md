# NeuralDocs AI

> Upload any project documents — get a clean, structured English spec with cross-file conflict detection. Powered by Groq (cloud) or LM Studio (local).

## What it does

- Extracts **goals, requirements, tech stack, team, timeline, budget, risks** from any documents (PDF, DOCX, TXT, code files)
- Detects **contradictions across files** — e.g. two docs that specify different budgets or timelines
- Works with documents in **any language** — always outputs a structured English spec
- Exports results to **PDF and DOCX**
- Protected against **prompt injection** via llm-guard
- Results stream to the browser in real time via **Server-Sent Events**

## Live Demo

<!-- Add Railway URL here after first deployment -->

## Quick Start — Self-Hosted (LM Studio)

1. Install [LM Studio](https://lmstudio.ai) and load any instruction-tuned model
2. Enable the local server in LM Studio (default port 1234)
3. Clone this repo and run:
   ```bash
   docker build -t neuraldocs .
   docker run -p 8000:8000 neuraldocs
   ```
4. Open [http://localhost:8000](http://localhost:8000)

## Quick Start — Cloud (Groq)

1. Get a free [Groq API key](https://console.groq.com)
2. Run with your key:
   ```bash
   docker build -t neuraldocs .
   docker run -p 8000:8000 -e GROQ_API_KEY=gsk_... neuraldocs
   ```

## Deploy to Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app)

1. Fork this repo
2. Create a new project on [Railway](https://railway.app) and connect your fork
3. Set `GROQ_API_KEY` in Railway environment variables
4. Deploy — Railway auto-detects the Dockerfile

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GROQ_API_KEY` | Cloud only | — | Enables Groq cloud mode (`llama-3.3-70b-versatile`) |
| `LM_STUDIO_HOST` | No | `host.docker.internal` | LM Studio host for self-hosted mode |
| `LM_STUDIO_MODEL` | No | auto-detected | Override the LM Studio model name |

## Architecture

Documents are processed through a two-phase LLM pipeline:

1. **MAP** — each file is chunked and fact-extracted sequentially using a local or cloud LLM
2. **REDUCE** — all facts are merged, deduplicated, and synthesised into a structured English spec

Cross-file conflicts (e.g. differing budgets across documents) are detected deterministically in Python — not guessed by the LLM. Results stream to the browser via Server-Sent Events as each phase completes.

## Tech Stack

`FastAPI` · `llm-guard` · `Groq / LM Studio` · `MAP-REDUCE pipeline` · `Server-Sent Events` · `Docker`

## License

MIT
