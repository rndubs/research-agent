"""Command-line interface.

Each command maps to a pipeline stage plus a couple of read-only views. Designed
to be driven by cron (``research-agent run``) for the ongoing monitor, or
stage-by-stage during development.

    research-agent run --config config/hexgen.yaml
    research-agent backlog --top 25
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .config import Config
from .models import BacklogStatus, PaperStatus
from .pipeline import STAGES, Pipeline

app = typer.Typer(add_completion=False, help="Ongoing arXiv research monitor -> prioritized backlog.")
console = Console()

DEFAULT_CONFIG = "config/hexgen.yaml"


def _load(config_path: str) -> Config:
    p = Path(config_path)
    if not p.exists():
        console.print(f"[red]Config not found:[/red] {config_path}")
        raise typer.Exit(2)
    return Config.load(p)


def _pipeline(config_path: str) -> Pipeline:
    return Pipeline(_load(config_path))


@app.command()
def init(config: str = typer.Option(DEFAULT_CONFIG, "--config", "-c")) -> None:
    """Initialize the database (idempotent)."""
    with _pipeline(config) as pipe:
        pipe.db.init_schema()
        console.print(f"[green]Initialized[/green] DB at {pipe.config.storage.db_path}")


@app.command()
def source(
    config: str = typer.Option(DEFAULT_CONFIG, "--config", "-c"),
    since: str | None = typer.Option(None, help="ISO date/datetime lower bound (overrides state)"),
) -> None:
    """Stage 1 — harvest new arXiv papers and enrich them."""
    from dateutil.parser import isoparse

    with _pipeline(config) as pipe:
        dt = isoparse(since) if since else None
        papers = pipe.source(since=dt)
        console.print(f"[green]Sourced[/green] {len(papers)} new papers")


@app.command()
def filter(config: str = typer.Option(DEFAULT_CONFIG, "--config", "-c")) -> None:
    """Stage 2 — relevance cascade (keyword -> embedding -> LLM)."""
    with _pipeline(config) as pipe:
        rel = pipe.filter()
        console.print(f"[green]Relevant[/green] this run: {len(rel)}")


@app.command()
def extract(config: str = typer.Option(DEFAULT_CONFIG, "--config", "-c")) -> None:
    """Stage 3 — full-text parse + schema-constrained claim extraction."""
    with _pipeline(config) as pipe:
        ex = pipe.extract()
        console.print(f"[green]Extracted[/green] {len(ex)} papers")


@app.command()
def score(config: str = typer.Option(DEFAULT_CONFIG, "--config", "-c")) -> None:
    """Stage 4 — RICE-style scoring + dependency graph."""
    with _pipeline(config) as pipe:
        items = pipe.score()
        console.print(f"[green]Scored[/green] {len(items)} backlog items")


@app.command()
def deliver(config: str = typer.Option(DEFAULT_CONFIG, "--config", "-c")) -> None:
    """Stage 5 — dedup, ranked backlog + digest."""
    with _pipeline(config) as pipe:
        digest = pipe.deliver()
        out = pipe.config.delivery.output_dir
        console.print(f"[green]Delivered[/green] {digest.new_item_count} new items -> {out}/")


@app.command()
def run(
    config: str = typer.Option(DEFAULT_CONFIG, "--config", "-c"),
    stages: str = typer.Option(",".join(STAGES), help="Comma-separated subset of stages"),
    since: str | None = typer.Option(None),
) -> None:
    """Run the full pipeline (or a subset) end to end."""
    from dateutil.parser import isoparse

    selected = tuple(s.strip() for s in stages.split(",") if s.strip())
    with _pipeline(config) as pipe:
        dt = isoparse(since) if since else None
        results = pipe.run(selected, since=dt)
    table = Table(title="pipeline run")
    table.add_column("stage")
    table.add_column("result")
    for stage, res in results.items():
        table.add_row(stage, str(res))
    console.print(table)


@app.command()
def backlog(
    config: str = typer.Option(DEFAULT_CONFIG, "--config", "-c"),
    top: int = typer.Option(25, "--top", "-n"),
) -> None:
    """Show the current ranked backlog."""
    with _pipeline(config) as pipe:
        items = pipe.db.top_backlog(top)
    if not items:
        console.print("[yellow]Backlog is empty.[/yellow] Run the pipeline first.")
        return
    table = Table(title=f"Top {len(items)} backlog items")
    table.add_column("#", justify="right")
    table.add_column("score", justify="right")
    table.add_column("F")
    table.add_column("title")
    table.add_column("paper")
    for i, item in enumerate(items, 1):
        table.add_row(
            str(i),
            f"{item.score:.3f}",
            "★" if item.foundational else "",
            item.title[:70],
            item.paper_id,
        )
    console.print(table)


@app.command()
def status(config: str = typer.Option(DEFAULT_CONFIG, "--config", "-c")) -> None:
    """Show corpus/backlog counts by processing state."""
    with _pipeline(config) as pipe:
        db = pipe.db
        table = Table(title="pipeline status")
        table.add_column("state")
        table.add_column("count", justify="right")
        for st in PaperStatus:
            table.add_row(st.value, str(db.count_papers(st)))
        table.add_row("[bold]backlog (new)[/bold]", str(sum(1 for _ in db.iter_backlog(BacklogStatus.NEW))))
        last = db.get_last_harvest()
        console.print(table)
        console.print(f"last harvest: {last.isoformat() if last else '—'}")


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
