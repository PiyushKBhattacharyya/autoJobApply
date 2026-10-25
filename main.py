import os
import sys
import webbrowser
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import click
from rich.prompt import Confirm, Prompt

from src.applier import NaukriApplier
from src.config import BASE_DIR, load_config
from src.db import (
    get_pending_tailoring_jobs,
    get_summary_stats,
    get_tailored_jobs_ready_for_review,
    init_db,
    update_application,
)
from src.naukri_scraper import NaukriScraper
from src.resume_parser import parse_master_resume
from src.tailor import tailor_resume_for_job
from src.ui import (
    console,
    display_job_card,
    display_stats,
    open_file_in_viewer,
    print_banner,
)


@click.group()
def cli():
    """Naukri AI Job Hunter & Resume Customizer CLI"""
    init_db()


@cli.command("init")
def cmd_init():
    """Initialize database and verify configuration."""
    print_banner()
    init_db()
    config = load_config()
    console.print("[green]✓ Database initialized at data/jobs.db[/green]")
    console.print(f"[cyan]Configuration loaded: Role='{config.search.role}', City='{config.search.city}', CTC={config.search.min_ctc_lpa}-{config.search.max_ctc_lpa} LPA[/cyan]")


@cli.command("login")
def cmd_login():
    """Open Naukri in a browser to log in and save session cookies."""
    print_banner()
    scraper = NaukriScraper(headless=False)
    scraper.interactive_login()


@cli.command("parse-resume")
@click.option("--pdf", type=click.Path(exists=True), help="Path to your master resume PDF")
def cmd_parse_resume(pdf):
    """Extract and structure your master resume PDF into JSON and Markdown."""
    print_banner()
    config = load_config()
    pdf_path = Path(pdf) if pdf else config.resume.master_pdf_abs

    if not pdf_path.exists():
        console.print(f"[bold red]Master resume PDF not found at: {pdf_path}[/bold red]")
        console.print("[yellow]Please place your PDF resume at 'data/master_resume.pdf' or pass --pdf <path>.[/yellow]")
        return

    try:
        parse_master_resume(pdf_path=pdf_path)
        console.print("[bold green]✓ Master profile parsed successfully![/bold green]")
        console.print(f"You can review or edit [cyan]{config.resume.master_profile_path}[/cyan] anytime.")
    except Exception as e:
        console.print(f"[bold red]Failed to parse master resume: {e}[/bold red]")


@cli.command("search")
@click.option("--role", help="Target job role")
@click.option("--city", help="Target city")
@click.option("--min-ctc", type=float, help="Minimum CTC in LPA")
@click.option("--max-ctc", type=float, help="Maximum CTC in LPA")
@click.option("--limit", type=int, help="Maximum jobs to fetch")
def cmd_search(role, city, min_ctc, max_ctc, limit):
    """Search Naukri for job postings and save matching listings to DB."""
    print_banner()
    scraper = NaukriScraper()
    jobs = scraper.search_jobs(
        role=role,
        city=city,
        min_ctc_lpa=min_ctc,
        max_ctc_lpa=max_ctc,
        max_results=limit
    )
    console.print(f"[bold green]✓ Discovered {len(jobs)} jobs matching criteria.[/bold green]")


@cli.command("tailor")
def cmd_tailor():
    """Tailor resume and generate ATS-compliant PDFs for all pending discovered jobs."""
    print_banner()
    pending = get_pending_tailoring_jobs()
    if not pending:
        console.print("[yellow]No pending jobs waiting for tailoring. Run `python main.py search` first.[/yellow]")
        return

    console.print(f"[cyan]Found {len(pending)} jobs to tailor with Gemini...[/cyan]\n")
    for idx, job in enumerate(pending, 1):
        console.print(f"[bold]({idx}/{len(pending)}) Tailoring for {job['company']} - {job['title']}...[/bold]")
        try:
            tailor_resume_for_job(job)
        except Exception as e:
            console.print(f"[red]Error tailoring for job {job['job_id']}: {e}[/red]")


@cli.command("run")
@click.option(
    "--mode",
    type=click.Choice(["supervised", "auto"], case_sensitive=False),
    help="Execution mode: supervised (interactive approval) or auto"
)
def cmd_run(mode):
    """Run full workflow: Search -> Tailor -> Apply (Supervised or Auto)."""
    print_banner()
    config = load_config()
    run_mode = (mode or config.bot.mode).lower()
    applier = NaukriApplier()

    console.print(f"[bold magenta]▶ Running in {run_mode.upper()} mode[/bold magenta]\n")

    # 1. Check master profile exists
    if not config.resume.master_profile_abs.exists():
        console.print(f"[yellow]Master profile not found at {config.resume.master_profile_abs}.[/yellow]")
        if config.resume.master_pdf_abs.exists():
            console.print("[cyan]Parsing master resume PDF first...[/cyan]")
            parse_master_resume()
        else:
            console.print("[bold red]Please place your PDF at 'data/master_resume.pdf' or run `python main.py parse-resume --pdf <path>` first.[/bold red]")
            return

    # 2. Check pending jobs or run search
    ready_jobs = get_tailored_jobs_ready_for_review()
    if not ready_jobs:
        pending_tailor = get_pending_tailoring_jobs()
        if not pending_tailor:
            console.print("[cyan]No jobs in queue. Running search first...[/cyan]")
            scraper = NaukriScraper()
            scraper.search_jobs()
            pending_tailor = get_pending_tailoring_jobs()

        # Tailor pending jobs
        console.print(f"[cyan]Tailoring {len(pending_tailor)} discovered jobs...[/cyan]")
        for job in pending_tailor:
            try:
                tailor_resume_for_job(job)
            except Exception as e:
                console.print(f"[red]Failed to tailor: {e}[/red]")

        ready_jobs = get_tailored_jobs_ready_for_review()

    if not ready_jobs:
        console.print("[yellow]No tailored jobs ready for application.[/yellow]")
        return

    console.print(f"\n[bold green]Found {len(ready_jobs)} tailored jobs ready for application review.[/bold green]\n")

    # 3. Process application queue
    for idx, job in enumerate(ready_jobs, 1):
        ats_score = job.get("ats_match_score", 0)
        display_job_card(
            job=job,
            ats_score=ats_score,
            matched_kw=job.get("matched_keywords", ""),
            missing_kw=job.get("missing_keywords", ""),
            resume_path=job.get("tailored_resume_path", "")
        )

        if run_mode == "auto":
            if ats_score >= config.bot.min_match_score:
                console.print(f"[bold green]Auto applying (Score {ats_score}% >= Threshold {config.bot.min_match_score}%)...[/bold green]")
                applier.apply_to_job(job)
            else:
                console.print(f"[yellow]Skipping auto-apply: Score {ats_score}% < Min Threshold {config.bot.min_match_score}%[/yellow]")
                update_application(job["job_id"], status="SKIPPED", notes=f"Score {ats_score}% below threshold")
            continue

        # Supervised Mode: Interactive choices
        action_loop = True
        while action_loop:
            choice = Prompt.ask(
                "[bold cyan]Action[/bold cyan]: [bold green](A)pply[/bold green] | [bold yellow](P)review PDF[/bold yellow] | [bold blue](O)pen URL[/bold blue] | [bold red](S)kip[/bold red] | [bold white](Q)uit[/bold white]",
                choices=["a", "p", "o", "s", "q"],
                default="a"
            ).lower()

            if choice == "a":
                console.print("[green]Applying to job...[/green]")
                applier.apply_to_job(job)
                action_loop = False
            elif choice == "p":
                pdf_path = job.get("tailored_resume_path")
                if pdf_path:
                    open_file_in_viewer(pdf_path)
                else:
                    console.print("[red]No PDF path recorded.[/red]")
            elif choice == "o":
                url = job.get("apply_url")
                if url:
                    webbrowser.open(url)
            elif choice == "s":
                console.print("[yellow]Skipping job...[/yellow]")
                update_application(job["job_id"], status="SKIPPED", notes="User skipped manually")
                action_loop = False
            elif choice == "q":
                console.print("[yellow]Exiting workflow. Progress saved in database.[/yellow]")
                return

    console.print("\n[bold green]✓ Application queue review complete![/bold green]")
    display_stats(get_summary_stats())


@cli.command("status")
def cmd_status():
    """Display overall bot statistics and application progress."""
    print_banner()
    stats = get_summary_stats()
    display_stats(stats)


if __name__ == "__main__":
    cli()
