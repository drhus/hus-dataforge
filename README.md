# Hus-DataForge

Universal scraping → cleaning → packaging pipeline for building LLM training datasets.

Subject-agnostic: configure a new domain by running \`dataforge init --template <domain>\`.

## Architecture

Python-first monorepo (\`uv\` workspace) with a Next.js dashboard.

\`\`\`
packages/
  engine/     — Scrapy spiders, crawl management
  pipeline/   — Cleaning, dedup, normalization, export
  api/        — FastAPI REST API
  cli/        — Typer CLI
dashboard/    — Next.js web UI
projects/     — Templates + active project configs
\`\`\`

## First Use Case

**Arabic poetry corpus** for LLM fine-tuning — feeding [hus-poemaster](https://github.com/drhus/hus-poemaster).

## Status

Planning / scaffold. See [milestones](https://github.com/drhus/hus-dataforge/wiki) and project docs in Obsidian vault.

## Quick Start

\`\`\`bash
# Install (Python 3.11+)
uv sync

# Create a new dataset project
dataforge init --template poetry my-poetry-dataset

# Scrape sources
dataforge scrape my-poetry-dataset

# Clean and deduplicate
dataforge clean my-poetry-dataset

# Export and push to HuggingFace
dataforge export my-poetry-dataset
dataforge push my-poetry-dataset
\`\`\`

## License

MIT
