"""Typer CLI. Subcommands grow as milestones land."""
from __future__ import annotations

import typer
import uvicorn

app = typer.Typer(help="Hus-DataForge CLI")


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: bool = False,
) -> None:
    """Run the FastAPI dev server."""
    uvicorn.run("packages.api.app:app", host=host, port=port, reload=reload)


@app.command()
def worker() -> None:
    """Run an RQ worker against the dataforge queue."""
    from packages.api.worker import main

    main()


@app.command()
def init(
    slug: str,
    template: str = typer.Option("generic", help="Template slug (generic | poetry | legal)"),
) -> None:
    """Stub — milestone 5 implements real templates."""
    import yaml

    from packages.api import projects_store

    cfg = {"template": template, "sources": [], "cleaning": {}, "export": {"format": "jsonl"}}
    p = projects_store.create_project(slug, cfg)
    typer.echo(f"created {p.slug} from template {template}")
    typer.echo(yaml.safe_dump(p.config, sort_keys=False, allow_unicode=True))


if __name__ == "__main__":
    app()
