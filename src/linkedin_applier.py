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
from src.linkedin_scraper import LinkedInScraper
from src.naukri_scraper import random_human_delay
from src.ui import copy_to_clipboard

console = Console()


class LinkedInApplier:
    def __init__(self):
        self.config = load_config()
        self.scraper = LinkedInScraper(headless=self.config.bot.headless)

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
            console.print(f"[red]Missing apply URL for LinkedIn job {job_id}[/red]")
            update_application(job_id, status="FAILED", notes="Missing apply URL")
            return "FAILED"

        console.print(f"\n[cyan]Navigating to LinkedIn job page:[/cyan] {apply_url}")

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

                # Inject floating guidance banner
                try:
                    resume_display_name = Path(resume_path).name if resume_path else "Tailored Resume"
                    page.evaluate(f"""() => {{
                        const banner = document.createElement('div');
                        banner.id = 'autojobapply-banner-linkedin';
                        banner.style.position = 'fixed';
                        banner.style.top = '10px';
                        banner.style.left = '50%';
                        banner.style.transform = 'translateX(-50%)';
                        banner.style.zIndex = '999999';
                        banner.style.backgroundColor = '#1e1e2e';
                        banner.style.color = '#0077b5';
                        banner.style.border = '2px solid #00a0dc';
                        banner.style.borderRadius = '8px';
                        banner.style.padding = '12px 24px';
                        banner.style.boxShadow = '0 8px 24px rgba(0,0,0,0.5)';
                        banner.style.fontFamily = 'system-ui, sans-serif';
                        banner.style.fontSize = '14px';
                        banner.style.fontWeight = 'bold';
                        banner.innerHTML = `💼 <b>AutoJobApply (LinkedIn Easy Apply):</b> Applying to <i>{job.get('company')}</i><br><span style="color:#ffffff; font-size:12px; font-weight:normal;">Tailored Resume: {resume_display_name}</span>`;
                        document.body.appendChild(banner);
                    }}""")
                except Exception:
                    pass

                # Wait for top card and apply buttons to render
                try:
                    page.wait_for_selector(
                        ".jobs-apply-button, button:has-text('Easy Apply'), [aria-label*='Easy Apply'], button:has-text('Apply'), .jobs-s-apply",
                        timeout=10000
                    )
                except Exception:
                    pass
                random_human_delay(1.5, 3.0)

                # Check if already applied previously
                already_applied = page.query_selector(
                    ".jobs-s-apply :has-text('Applied'), span:has-text('Applied'), button:has-text('Applied')"
                )
                if already_applied and already_applied.is_visible():
                    console.print(f"[yellow]Already applied to {job.get('company')} on LinkedIn previously.[/yellow]")
                    update_application(job_id, status="APPLIED", notes="Already applied on LinkedIn")
                    context.close()
                    return "APPLIED"

                # LinkedIn Easy Apply button selectors
                easy_apply_selectors = [
                    "button.jobs-apply-button",
                    "button:has-text('Easy Apply')",
                    "button[aria-label*='Easy Apply']",
                    "[data-control-name='jobdetails_topcard_inapply']",
                    ".jobs-s-apply button:has-text('Easy Apply')",
                    ".jobs-s-apply button"
                ]

                apply_btn = None
                for sel in easy_apply_selectors:
                    b = page.query_selector(sel)
                    if b and b.is_visible():
                        apply_btn = b
                        break

                if not apply_btn:
                    # Check for login/authwall
                    if "Join LinkedIn" in page.title() or page.query_selector("input[name='session_key'], #username"):
                        console.print(f"[bold red]LinkedIn session expired or authwall detected! Run `python main.py login --platform linkedin` to re-authenticate.[/bold red]")
                        update_application(job_id, status="FAILED", notes="LinkedIn session expired/authwall")
                        context.close()
                        return "FAILED"

                    # Check if standard external Apply button (must NOT contain 'Easy')
                    ext_btn = page.query_selector("a:has-text('Apply'), button:has-text('Apply on company')")
                    if ext_btn and ext_btn.is_visible():
                        set_job_easy_apply(job_id, is_easy=False)
                        if easy_apply_only:
                            console.print(f"[yellow]Skipping LinkedIn listing {job.get('company')}: External portal.[/yellow]")
                            update_application(job_id, status="SKIPPED", notes="Skipped: External portal on LinkedIn")
                            context.close()
                            return "SKIPPED"

                    # Capture debug screenshot
                    screenshots_dir = BASE_DIR / "output" / "screenshots"
                    screenshots_dir.mkdir(parents=True, exist_ok=True)
                    shot_path = screenshots_dir / f"linkedin_debug_{job_id}.png"
                    try:
                        page.screenshot(path=str(shot_path), full_page=False)
                        console.print(f"[yellow]📸 Screen capture saved: [cyan]{shot_path}[/cyan][/yellow]")
                    except Exception:
                        pass

                    if interactive:
                        console.print(f"[bold yellow]👉 LinkedIn window open. Please review or complete apply on screen.[/bold yellow]")
                        user_confirm = Prompt.ask(
                            f"Did you complete the application for {job.get('company')} on LinkedIn? [bold green](Y/n)[/bold green]",
                            choices=["y", "n"],
                            default="y"
                        ).lower()
                        if user_confirm == "y":
                            update_application(job_id, status="APPLIED", notes="Applied manually on LinkedIn")
                            context.close()
                            return "APPLIED"

                    console.print(f"[red]No LinkedIn Easy Apply button found.[/red]")
                    update_application(job_id, status="FAILED", notes="LinkedIn Easy Apply button not found")
                    context.close()
                    return "FAILED"

                # Click Easy Apply
                console.print(f"[green]Clicking 'Easy Apply' on LinkedIn...[/green]")
                apply_btn.click()
                random_human_delay(2.5, 4.0)

                # Modal navigation loop
                resume_uploaded = False
                submitted = False

                for step_idx in range(8):
                    # Check and upload tailored resume at EVERY step if file input is visible
                    if not resume_uploaded and resume_path and Path(resume_path).exists():
                        file_input = page.query_selector("input[type='file']")
                        if file_input:
                            try:
                                console.print(f"[cyan]Uploading tailored resume to LinkedIn: {resume_path}...[/cyan]")
                                file_input.set_input_files(str(Path(resume_path).resolve()))
                                resume_uploaded = True
                                random_human_delay(2.5, 4.0)
                            except Exception as ex:
                                console.print(f"[yellow]Resume upload warning: {ex}[/yellow]")

                    # Check for Submit application button
                    submit_btn = page.query_selector(
                        "button:has-text('Submit application'), [aria-label='Submit application'], button.artdeco-button--primary:has-text('Submit')"
                    )
                    if submit_btn and submit_btn.is_visible():
                        console.print(f"[green]Submitting application on LinkedIn...[/green]")
                        submit_btn.click()
                        random_human_delay(3.0, 5.0)
                        submitted = True
                        break

                    # Check for Review button
                    review_btn = page.query_selector(
                        "button:has-text('Review'), [aria-label='Review your application']"
                    )
                    if review_btn and review_btn.is_visible():
                        review_btn.click()
                        random_human_delay(2.0, 3.5)
                        continue

                    # Check for Next button
                    next_btn = page.query_selector(
                        "button:has-text('Next'), [aria-label='Continue to next step']"
                    )
                    if next_btn and next_btn.is_visible():
                        next_btn.click()
                        random_human_delay(2.0, 3.5)

                        # Check for inline validation errors (required questions)
                        error_elem = page.query_selector(
                            ".artdeco-inline-feedback--error, [data-test-form-builder-error], .fb-form-element--error"
                        )
                        if error_elem and error_elem.is_visible():
                            if interactive:
                                console.print(f"[bold yellow]👉 LinkedIn form requires input for {job.get('company')}. Please complete the required fields in the browser window.[/bold yellow]")
                                Prompt.ask("Press [bold cyan][ENTER][/bold cyan] once you have answered questions or advanced the step")
                            else:
                                break
                    else:
                        break

                # Dismiss post-submission confirmation if present
                try:
                    done_btn = page.query_selector("button:has-text('Done'), [aria-label='Dismiss']")
                    if done_btn and done_btn.is_visible():
                        done_btn.click()
                        submitted = True
                except Exception:
                    pass

                if interactive:
                    confirm = Prompt.ask(
                        f"Review LinkedIn modal for {job.get('company')}. Was application completed/submitted? [bold green](Y/n)[/bold green]",
                        choices=["y", "n"],
                        default="y" if submitted else "n"
                    ).lower()
                    if confirm == "y":
                        console.print(f"[bold green]✓ Application submitted on LinkedIn for {job.get('company')}![/bold green]")
                        update_application(job_id, status="APPLIED", notes="Applied on LinkedIn")
                        context.close()
                        return "APPLIED"
                    else:
                        console.print(f"[yellow]Application not completed for {job.get('company')}.[/yellow]")
                        update_application(job_id, status="FAILED", notes="Incomplete submission by user")
                        context.close()
                        return "FAILED"

                if submitted:
                    update_application(job_id, status="APPLIED", notes="Applied on LinkedIn auto flow")
                    context.close()
                    return "APPLIED"
                else:
                    update_application(job_id, status="FAILED", notes="LinkedIn form incomplete or required questions unanswered")
                    context.close()
                    return "FAILED"

            except Exception as e:
                console.print(f"[red]Error applying on LinkedIn: {e}[/red]")
                update_application(job_id, status="FAILED", notes=str(e)[:200])
                context.close()
                return "FAILED"
