# Hus-DataForge

## Project Context

All specs, PRD, milestones, and decisions live in the Obsidian vault:

- Overview: /home/agent/Documents/Second-Brain/10-projects/hus-dataforge/overview.md
- PRD: /home/agent/Documents/Second-Brain/10-projects/hus-dataforge/prd.md
- Milestones: /home/agent/Documents/Second-Brain/10-projects/hus-dataforge/milestones.md
- Progress: /home/agent/Documents/Second-Brain/10-projects/hus-dataforge/progress.md

## What this repo is

A universal scraping → cleaning → packaging pipeline for building LLM training datasets. Python-first monorepo (uv workspace) with a Next.js dashboard consumer.

First application: Arabic poetry corpus for fine-tuning sibawayh-poemaster.
Future: legal corpus (ai-auditor), scientific Arabic, others.

## Architecture

```
packages/engine/    — Scrapy spiders, crawl management
packages/pipeline/  — Cleaning, dedup, normalization, export
packages/api/       — FastAPI REST API (serves dashboard)
packages/cli/       — Typer CLI interface
dashboard/          — Next.js app (thin UI consumer)
projects/           — Project configs + templates
```

## Key Decisions

- Python-first: 90% of work is Python (scraping, cleaning, dedup, HF export)
- uv workspace for dependency management
- File-based storage: JSONL + Parquet (HuggingFace-native)
- Template-based projects: `dataforge init --template <domain>`
- Redis for job queue, medium scale (parallel workers on VPS)
- Dashboard on Vercel, engine on VPS

## Milestone Order

1. Dashboard & API Foundation
2. Scraping Engine
3. Cleaning Pipeline
4. Export & HuggingFace Publishing
5. Multi-Project Template System
