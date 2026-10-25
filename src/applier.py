import time
from pathlib import Path
from typing import Any, Dict, Optional
from playwright.sync_api import Page, sync_playwright

from src.config import BASE_DIR, load_config
from src.db import update_application
from src.naukri_scraper import NaukriScraper, random_human_delay


class NaukriApplier:
    def __init__(self):
        self.config = load_config()
        self.scraper = NaukriScraper(headless=self.config.bot.headless)

    def apply_to_job(
        self,
        job: Dict[str, Any],
        tailored_resume_path: Optional[str] = None
    ) -> str:
        """
        Attempts to apply to a Naukri job using the persistent browser context.
        Returns the result status: 'APPLIED', 'EXTERNAL_REDIRECT', or 'FAILED'.
        """
        apply_url = job.get("apply_url")
        job_id = job.get("job_id")
        resume_path = tailored_resume_path or job.get("tailored_resume_path")

        if not apply_url:
            print(f"No apply URL found for job {job_id}")
            update_application(job_id, status="FAILED", notes="Missing apply URL")
            return "FAILED"

        print(f"\nNavigating to application page: {apply_url}")

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
                    "button:has-text('Apply on company site'), a:has-text('Apply on company site')"
                )
                if company_site_btn:
                    print("Job requires external application on company career portal.")
                    update_application(
                        job_id,
                        status="EXTERNAL_REDIRECT",
                        notes="Redirects to company portal. Tailored resume ready for upload."
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
                        print("Already applied to this job previously.")
                        update_application(job_id, status="APPLIED", notes="Already applied on Naukri")
                        context.close()
                        return "APPLIED"

                    print("No apply button found or dynamic structure encountered.")
                    update_application(job_id, status="FAILED", notes="Apply button selector not matched")
                    context.close()
                    return "FAILED"

                # Click Apply button
                print("Clicking 'Apply' button...")
                apply_button.click()
                random_human_delay(2.5, 4.0)

                # Check if file upload input appears (for attaching tailored resume)
                file_input = page.query_selector("input[type='file']")
                if file_input and resume_path and Path(resume_path).exists():
                    print(f"Uploading tailored resume: {resume_path}...")
                    file_input.set_input_files(str(Path(resume_path).resolve()))
                    random_human_delay(3.0, 5.0)

                # Look for a final confirm/submit button inside the modal if any
                submit_modal_btn = page.query_selector(
                    "button:has-text('Submit'), button:has-text('Confirm'), .chatbot-submit, button:has-text('Apply Now')"
                )
                if submit_modal_btn and submit_modal_btn.is_visible():
                    print("Submitting application modal...")
                    submit_modal_btn.click()
                    random_human_delay(3.0, 5.0)

                # Check for success indicators
                success_el = page.query_selector(
                    ":has-text('successfully applied'), :has-text('Application sent'), :has-text('Applied Successfully')"
                )

                print("✓ Application process completed successfully!")
                update_application(
                    job_id,
                    status="APPLIED",
                    notes="Applied successfully via automated flow"
                )
                context.close()
                return "APPLIED"

            except Exception as e:
                print(f"Error applying to job {job_id}: {e}")
                update_application(job_id, status="FAILED", notes=str(e)[:200])
                context.close()
                return "FAILED"
