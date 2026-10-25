import time
import webbrowser
from pathlib import Path
from typing import Any, Dict, Optional
from playwright.sync_api import Page, sync_playwright
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from src.config import BASE_DIR, load_config
from src.db import update_application, set_job_easy_apply
from src.naukri_scraper import NaukriScraper, random_human_delay
from src.ui import copy_to_clipboard

console = Console()


class NaukriApplier:
    def __init__(self):
        self.config = load_config()
        self.scraper = NaukriScraper(headless=self.config.bot.headless)

    def apply_to_job(
        self,
        job: Dict[str, Any],
        tailored_resume_path: Optional[str] = None,
        easy_apply_only: bool = False,
        interactive: bool = True
    ) -> str:
        """
        Attempts to apply to a Naukri job.
        If Direct Apply: uploads tailored PDF and submits via Naukri.
        If External Company Portal:
          - If easy_apply_only is True: skips the job.
          - If easy_apply_only is False: opens external portal, copies resume path to clipboard,
            and allows interactive confirmation.
        Returns: 'APPLIED', 'EXTERNAL_REDIRECT', 'SKIPPED', or 'FAILED'.
        """
        apply_url = job.get("apply_url")
        job_id = job.get("job_id")
        resume_path = tailored_resume_path or job.get("tailored_resume_path")

        if not apply_url:
            console.print(f"[red]No apply URL found for job {job_id}[/red]")
            update_application(job_id, status="FAILED", notes="Missing apply URL")
            return "FAILED"

        console.print(f"\n[cyan]Navigating to application page:[/cyan] {apply_url}")

        with sync_playwright() as p:
            context = self.scraper.get_browser_context(p)
            page = context.new_page()

            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            try:
                page.goto(apply_url, wait_until="domcontentloaded", timeout=45000)
                random_human_delay(3.0, 5.0)

                # Check if it is an external redirect ("Apply on company site")
                company_site_btn = page.query_selector(
                    "button:has-text('Apply on company site'), a:has-text('Apply on company site'), [id*='company-site']"
                )
                if company_site_btn:
                    set_job_easy_apply(job_id, is_easy=False)
                    if easy_apply_only:
                        console.print(f"[yellow]Skipping {job.get('company')}: Requires external company portal (Easy Apply Only mode enabled).[/yellow]")
                        update_application(
                            job_id,
                            status="SKIPPED",
                            notes="Skipped: External company portal (Easy Apply Only mode)"
                        )
                        context.close()
                        return "SKIPPED"

                    # Assisted External Application
                    console.print(f"\n[bold yellow]🌐 Job requires external application on {job.get('company')} career portal.[/bold yellow]")
                    dest_url = company_site_btn.get_attribute("href") or apply_url

                    resume_abs_str = ""
                    if resume_path and Path(resume_path).exists():
                        resume_abs_str = str(Path(resume_path).resolve())
                        copied = copy_to_clipboard(resume_abs_str)
                        if copied:
                            console.print(f"[bold cyan]📋 Tailored resume path copied to your clipboard:[/bold cyan]")
                            console.print(f"   [green]{resume_abs_str}[/green]")

                    console.print(f"[bold blue]Opening external application page in your browser...[/bold blue]")
                    try:
                        webbrowser.open(dest_url)
                    except Exception:
                        pass

                    instructions = f"""
[bold green]Assisted External Application Flow:[/bold green]
1. Career portal opened for [bold white]{job.get('company')}[/bold white].
2. Tailored resume PDF path is copied on your clipboard:
   [bold cyan]{resume_abs_str}[/bold cyan]
3. When uploading your resume on the portal, simply press [bold yellow]Ctrl + V[/bold yellow] in the file dialog.
4. Complete any company-specific questions and click Submit.
                    """.strip()
                    console.print(Panel(instructions, title=f"External Application: {job.get('company')}", border_style="yellow"))

                    if interactive:
                        confirmed = Prompt.ask(
                            f"Did you finish submitting your application on {job.get('company')}? [bold green](Y/n)[/bold green]",
                            choices=["y", "n"],
                            default="y"
                        ).lower()
                        if confirmed == "y":
                            console.print(f"[bold green]✓ Recorded as APPLIED for {job.get('company')}![/bold green]")
                            update_application(
                                job_id,
                                status="APPLIED",
                                notes="Applied via company career portal (Assisted mode)"
                            )
                            context.close()
                            return "APPLIED"
                        else:
                            console.print(f"[yellow]Marked as EXTERNAL_REDIRECT (pending manual submission).[/yellow]")
                            update_application(
                                job_id,
                                status="EXTERNAL_REDIRECT",
                                notes="Opened external portal - pending user finish"
                            )
                            context.close()
                            return "EXTERNAL_REDIRECT"
                    else:
                        update_application(
                            job_id,
                            status="EXTERNAL_REDIRECT",
                            notes="Opened external portal in auto mode"
                        )
                        context.close()
                        return "EXTERNAL_REDIRECT"

                # Look for Naukri Direct Apply button
                apply_button = page.query_selector(
                    "#apply-button, button.apply-button, button:has-text('Apply'), [id*='apply']"
                )

                if not apply_button:
                    # Check if already applied
                    already_applied = page.query_selector(
                        ":has-text('Already Applied'), button:has-text('Applied')"
                    )
                    if already_applied:
                        console.print(f"[yellow]Already applied to {job.get('company')} previously.[/yellow]")
                        update_application(job_id, status="APPLIED", notes="Already applied on Naukri")
                        context.close()
                        return "APPLIED"

                    console.print(f"[red]No apply button found or unexpected page structure.[/red]")
                    update_application(job_id, status="FAILED", notes="Apply button selector not matched")
                    context.close()
                    return "FAILED"

                # Click Apply button
                console.print(f"[green]Clicking 'Apply' button on Naukri...[/green]")
                apply_button.click()
                random_human_delay(2.5, 4.0)

                # Check if file upload input appears (for attaching tailored resume)
                file_input = page.query_selector("input[type='file']")
                if file_input and resume_path and Path(resume_path).exists():
                    console.print(f"[cyan]Uploading tailored resume: {resume_path}...[/cyan]")
                    file_input.set_input_files(str(Path(resume_path).resolve()))
                    random_human_delay(3.0, 5.0)

                # Look for a final confirm/submit button inside the modal if any
                submit_modal_btn = page.query_selector(
                    "button:has-text('Submit'), button:has-text('Confirm'), .chatbot-submit, button:has-text('Apply Now')"
                )
                if submit_modal_btn and submit_modal_btn.is_visible():
                    console.print(f"[cyan]Submitting application modal...[/cyan]")
                    submit_modal_btn.click()
                    random_human_delay(3.0, 5.0)

                console.print(f"[bold green]✓ Application submitted successfully directly on Naukri![/bold green]")
                update_application(
                    job_id,
                    status="APPLIED",
                    notes="Applied successfully via automated 1-click flow on Naukri"
                )
                context.close()
                return "APPLIED"

            except Exception as e:
                console.print(f"[red]Error applying to job {job_id}: {e}[/red]")
                update_application(job_id, status="FAILED", notes=str(e)[:200])
                context.close()
                return "FAILED"

