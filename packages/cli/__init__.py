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


@app.command(name="scrape")
def scrape(
    slug: str = typer.Argument(..., help="Project slug to scrape"),
) -> None:
    """Run all configured sources for a project synchronously (no queue)."""
    from packages.engine import run_scrape

    result = run_scrape(slug)
    import json

    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command(name="scrape-list")
def scrape_list() -> None:
    """List projects available to scrape."""
    from packages.api import projects_store

    for p in projects_store.list_projects():
        typer.echo(p.slug)


@app.command(name="clean")
def clean(slug: str) -> None:
    """Run the cleaning pipeline for a project (raw → clean JSONL per poet)."""
    import json

    from packages.pipeline import run_clean

    result = run_clean(slug)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command(name="telegram-login")
def telegram_login() -> None:
    """One-time interactive login for the Telegram MTProto spider.

    Reads /home/agent/.config/dataforge/telegram.env for api_id/hash,
    prompts for your phone + the code Telegram sends to your account,
    then writes a reusable .session file."""
    from telethon import TelegramClient

    from packages.engine.spiders.telegram_mtproto import _load_creds

    creds = _load_creds()
    api_id = int(creds["TELEGRAM_API_ID"])
    api_hash = creds["TELEGRAM_API_HASH"]
    session = creds.get("TELEGRAM_SESSION_PATH") or "/home/agent/.config/dataforge/telegram"
    if session.endswith(".session"):
        session = session[:-8]
    if api_hash == "__SET_ME__":
        typer.echo("Set TELEGRAM_API_HASH in /home/agent/.config/dataforge/telegram.env first.")
        raise typer.Exit(1)

    typer.echo(f"Using session at {session}.session")
    client = TelegramClient(session, api_id, api_hash)
    client.start()  # interactive prompt for phone + code
    me = client.get_me()
    typer.echo(f"Logged in as {me.first_name} (@{me.username}, id={me.id}).")
    client.disconnect()


if __name__ == "__main__":
    app()
