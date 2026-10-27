import time
import webbrowser
from pathlib import Path
from typing import Any, Dict, Optional
from playwright.sync_api import sync_playwright
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from src.config import BASE_DIR, load_config
from src.db import set_job_easy_apply, update_application
from src.indeed_scraper import IndeedScraper
from src.naukri_scraper import random_human_delay
from src.ui import copy_to_clipboard

console = Console()


class IndeedApplier:
    def __init__(self):
        self.config = load_config()
        self.scraper = IndeedScraper(headless=self.config.bot.headless)

    def apply_to_job(
        self,
        job: Dict[str, Any],
        resume_path: Optional[str] = None,
        easy_apply_only: bool = False,
        interactive: bool = True
    ) -> str:
        job_id = job.get("job_id")
        apply_url = job.get("apply_url")
        resume_path = resume_path or job.get("tailored_resume_path")

        if not apply_url:
            console.print(f"[red]Missing apply URL for job {job_id}[/red]")
            update_application(job_id, status="FAILED", notes="Missing apply URL")
            return "FAILED"

        console.print(f"\n[cyan]Navigating to Indeed application page:[/cyan] {apply_url}")

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

                # Check if it is an external company portal redirect
                company_site_btn = page.query_selector(
                    "button:has-text('Apply on company site'), a:has-text('Apply on company site'), a[data-indeed-apply='false']"
                )
                if company_site_btn:
                    set_job_easy_apply(job_id, is_easy=False)
                    if easy_apply_only:
                        console.print(f"[yellow]Skipping Indeed listing {job.get('company')}: External portal.[/yellow]")
                        update_application(job_id, status="SKIPPED", notes="Skipped: External portal on Indeed")
                        context.close()
                        return "SKIPPED"

                    # Assisted External Apply
                    dest_url = company_site_btn.get_attribute("href") or apply_url
                    resume_abs_str = str(Path(resume_path).resolve()) if resume_path and Path(resume_path).exists() else ""
                    if resume_abs_str:
                        copy_to_clipboard(resume_abs_str)
                    try:
                        webbrowser.open(dest_url)
                    except Exception:
                        pass
                    if interactive:
                        confirmed = Prompt.ask(
                            f"Did you finish submitting your application on {job.get('company')}? [bold green](Y/n)[/bold green]",
                            choices=["y", "n"],
                            default="y"
                        ).lower()
                        status = "APPLIED" if confirmed == "y" else "EXTERNAL_REDIRECT"
                        update_application(job_id, status=status, notes="Applied via external portal from Indeed")
                        context.close()
                        return status

                # Inject floating guidance banner
                try:
                    resume_display_name = Path(resume_path).name if resume_path else "Tailored Resume"
                    page.evaluate(f"""() => {{
                        const banner = document.createElement('div');
                        banner.id = 'autojobapply-banner-indeed';
                        banner.style.position = 'fixed';
                        banner.style.top = '10px';
                        banner.style.left = '50%';
                        banner.style.transform = 'translateX(-50%)';
                        banner.style.zIndex = '999999';
                        banner.style.backgroundColor = '#1e1e2e';
                        banner.style.color = '#a6e3a1';
                        banner.style.border = '2px solid #89b4fa';
                        banner.style.borderRadius = '8px';
                        banner.style.padding = '12px 24px';
                        banner.style.boxShadow = '0 8px 24px rgba(0,0,0,0.5)';
                        banner.style.fontFamily = 'system-ui, sans-serif';
                        banner.style.fontSize = '14px';
                        banner.style.fontWeight = 'bold';
                        banner.innerHTML = `⚡ <b>AutoJobApply (Indeed):</b> Applying to <i>{job.get('company')}</i><br><span style="color:#cdd6f4; font-size:12px; font-weight:normal;">Tailored Resume: {resume_display_name}</span>`;
                        document.body.appendChild(banner);
                    }}""")
                except Exception:
                    pass

                # Indeed Apply Button selectors
                apply_selectors = [
                    "#indeedApplyButton",
                    "button[id*='indeedApplyButton']",
                    "button:has-text('Apply now')",
                    "button:has-text('Easily apply')",
                    "a:has-text('Apply now')"
                ]

                apply_btn = None
                for sel in apply_selectors:
                    b = page.query_selector(sel)
                    if b and b.is_visible():
                        apply_btn = b
                        break

                if not apply_btn:
                    # Capture debug screenshot
                    screenshots_dir = BASE_DIR / "output" / "screenshots"
                    screenshots_dir.mkdir(parents=True, exist_ok=True)
                    shot_path = screenshots_dir / f"indeed_debug_{job_id}.png"
                    try:
                        page.screenshot(path=str(shot_path), full_page=False)
                        console.print(f"[yellow]📸 Screen capture saved: [cyan]{shot_path}[/cyan][/yellow]")
                    except Exception:
                        pass

                    if interactive:
                        console.print(f"[bold yellow]👉 Indeed window is open. Please complete the application or review on screen.[/bold yellow]")
                        user_confirm = Prompt.ask(
                            f"Did you complete the application for {job.get('company')} on Indeed? [bold green](Y/n)[/bold green]",
                            choices=["y", "n"],
                            default="y"
                        ).lower()
                        if user_confirm == "y":
                            update_application(job_id, status="APPLIED", notes="Applied manually on Indeed")
                            context.close()
                            return "APPLIED"

                    console.print(f"[red]No Indeed apply button found.[/red]")
                    update_application(job_id, status="FAILED", notes="Indeed apply button not found")
                    context.close()
                    return "FAILED"

                # Click Apply Now
                console.print(f"[green]Clicking 'Apply now' on Indeed...[/green]")
                apply_btn.click()
                random_human_delay(3.0, 5.0)

                # Look for file upload input to attach tailored resume
                file_input = page.query_selector("input[type='file']")
                if file_input and resume_path and Path(resume_path).exists():
                    console.print(f"[cyan]Uploading tailored resume to Indeed: {resume_path}...[/cyan]")
                    file_input.set_input_files(str(Path(resume_path).resolve()))
                    random_human_delay(3.0, 4.0)

                # Modal navigation loop (Continue / Submit buttons)
                for _ in range(4):
                    submit_btn = page.query_selector("button:has-text('Submit your application'), button:has-text('Apply')")
                    if submit_btn and submit_btn.is_visible():
                        submit_btn.click()
                        random_human_delay(2.5, 4.0)
                        break

                    continue_btn = page.query_selector("button:has-text('Continue'), button:has-text('Next')")
                    if continue_btn and continue_btn.is_visible():
                        continue_btn.click()
                        random_human_delay(2.0, 3.5)
                    else:
                        break

                if interactive:
                    confirm = Prompt.ask(
                        f"Review Indeed modal for {job.get('company')}. Submit completed? [bold green](Y/n)[/bold green]",
                        choices=["y", "n"],
                        default="y"
                    ).lower()
                    if confirm == "y":
                        console.print(f"[bold green]✓ Application submitted on Indeed for {job.get('company')}![/bold green]")
                        update_application(job_id, status="APPLIED", notes="Applied on Indeed")
                        context.close()
                        return "APPLIED"

                update_application(job_id, status="APPLIED", notes="Applied on Indeed auto flow")
                context.close()
                return "APPLIED"

            except Exception as e:
                console.print(f"[red]Error applying on Indeed: {e}[/red]")
                update_application(job_id, status="FAILED", notes=str(e)[:200])
                context.close()
                return "FAILED"
