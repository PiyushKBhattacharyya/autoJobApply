import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from playwright.sync_api import BrowserContext, sync_playwright

from src.config import BASE_DIR, load_config
from src.db import save_job
from src.naukri_scraper import parse_experience_range, parse_salary_to_lpa, random_human_delay


class IndeedScraper:
    def __init__(self, headless: Optional[bool] = None):
        self.config = load_config()
        self.headless = headless if headless is not None else self.config.bot.headless
        # Dedicated persistent context directory for Indeed session
        self.context_dir = BASE_DIR / ".browser_context_indeed"
        self.context_dir.mkdir(parents=True, exist_ok=True)

    def get_browser_context(self, playwright_instance) -> BrowserContext:
        """Launch a persistent context retaining Indeed login cookies and session."""
        args = [
            "--disable-blink-features=AutomationControlled",
            "--start-maximized",
            "--no-sandbox"
        ]
        context = playwright_instance.chromium.launch_persistent_context(
            user_data_dir=str(self.context_dir),
            headless=self.headless,
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
            args=args
        )
        return context

    def interactive_login(self):
        """Opens Indeed login page in headed mode with stealth args for the user to log in."""
        print("\nOpening Indeed Login in headed browser...")
        print("Please log in using your Google SSO, email, or credentials.")
        print("Once logged in to your Indeed dashboard, press ENTER in the terminal to save your session.\n")

        with sync_playwright() as p:
            args = [
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(self.context_dir),
                headless=False,
                viewport={"width": 1366, "height": 768},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/128.0.0.0 Safari/537.36"
                ),
                args=args
            )
            page = context.new_page()

            # Evade navigator.webdriver detection (Cloudflare Turnstile evasion)
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            # Direct to the actual Indeed account sign-in page
            page.goto("https://secure.indeed.com/auth", wait_until="domcontentloaded")

            input(">> Press [ENTER] here after you have successfully logged in on Indeed: ")

            print("Saving Indeed login session...")
            random_human_delay(1.5, 3.0)
            context.close()
            print("✓ Indeed session successfully preserved in .browser_context_indeed/!")

    def build_search_url(self, role: str, city: str, page_num: int = 1) -> str:
        """
        Builds Indeed search URL with 'Easily apply' filter (iareq=1).
        """
        q = quote_plus(role)
        l = quote_plus(city)
        start = (page_num - 1) * 10
        url = f"https://in.indeed.com/jobs?q={q}&l={l}&iareq=1"
        if start > 0:
            url += f"&start={start}"
        return url

    def search_jobs(
        self,
        role: Optional[str] = None,
        city: Optional[str] = None,
        experience: Optional[int] = None,
        max_results: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Searches Indeed for jobs matching criteria, filtering for candidate's max experience."""
        role = role or self.config.search.role
        city = city or self.config.search.city
        exp = experience if experience is not None else self.config.search.experience_years
        limit = max_results or self.config.search.max_results

        print(f"\n🔍 Searching Indeed for '{role}' in '{city}' (Exp <= {exp} yrs, Easily Apply)...")
        discovered_jobs: List[Dict[str, Any]] = []

        with sync_playwright() as p:
            context = self.get_browser_context(p)
            page = context.new_page()

            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            current_page = 1
            while len(discovered_jobs) < limit and current_page <= 3:
                search_url = self.build_search_url(role, city, page_num=current_page)
                print(f"Loading Indeed page {current_page}: {search_url}")

                try:
                    page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
                    random_human_delay(3.0, 5.0)

                    # Scroll smoothly to load job cards
                    for _ in range(3):
                        page.mouse.wheel(0, 700)
                        time.sleep(0.7)

                    html = page.content()
                    soup = BeautifulSoup(html, "html.parser")

                    # Indeed card selectors
                    job_cards = soup.select(".job_seen_beacon, div.cardOutline, td.resultContent")
                    if not job_cards:
                        job_cards = soup.select("div[data-jk]")

                    if not job_cards:
                        print("No job cards found on Indeed page (or captcha verification required).")
                        break

                    print(f"Found {len(job_cards)} job cards on Indeed page {current_page}.")

                    for card in job_cards:
                        if len(discovered_jobs) >= limit:
                            break

                        parsed = self._parse_job_card(card)
                        if not parsed:
                            continue

                        # Experience Filter
                        job_min_exp = parsed.get("min_exp")
                        if job_min_exp is not None and job_min_exp > exp:
                            continue

                        # Save to DB
                        saved = save_job(parsed)
                        if saved:
                            discovered_jobs.append(parsed)
                            print(f"  + [Indeed | {parsed['company']}] {parsed['title']} ({parsed['salary_text']})")

                    current_page += 1
                    random_human_delay(2.0, 4.0)

                except Exception as e:
                    print(f"Error during Indeed search on page {current_page}: {e}")
                    break

            context.close()

        print(f"\n✓ Discovered & saved {len(discovered_jobs)} matching jobs from Indeed.")
        return discovered_jobs

    def _parse_job_card(self, card) -> Optional[Dict[str, Any]]:
        """Extracts standardized attributes from an Indeed job card."""
        try:
            # Job ID (Indeed data-jk)
            job_id = card.get("data-jk")
            if not job_id:
                link_el = card.select_one("a[data-jk], a[id*='job_']")
                if link_el:
                    job_id = link_el.get("data-jk") or link_el.get("id")

            # Title & Link
            title_el = card.select_one("h2.jobTitle span, a.jcs-JobTitle, .jobTitle a")
            title = title_el.get_text(strip=True) if title_el else ""

            apply_link_el = card.select_one("a.jcs-JobTitle, a[data-jk], h2.jobTitle a")
            apply_url = ""
            if apply_link_el:
                href = apply_link_el.get("href", "")
                if href.startswith("/"):
                    apply_url = f"https://in.indeed.com{href}"
                elif href.startswith("http"):
                    apply_url = href

            if not job_id and apply_url:
                m = re.search(r"jk=([a-zA-Z0-9]+)", apply_url)
                if m:
                    job_id = m.group(1)

            if not job_id:
                job_id = f"indeed_{abs(hash(title + apply_url))}"

            # Ensure unique prefix for Indeed
            if not str(job_id).startswith("indeed_"):
                job_id = f"indeed_{job_id}"

            # Company
            company_el = card.select_one("[data-testid='company-name'], span.css-63koeb, .companyName")
            company = company_el.get_text(strip=True) if company_el else "Unknown Company"

            # Location
            loc_el = card.select_one("[data-testid='text-location'], div.css-1p0sjhy, .companyLocation")
            location = loc_el.get_text(strip=True) if loc_el else ""

            # Salary
            sal_el = card.select_one("[data-testid='attribute_snippet_testid'], .salary-snippet-container, div.metadata.salary-snippet-container")
            salary_text = sal_el.get_text(strip=True) if sal_el else "Not Disclosed"
            min_ctc, max_ctc = parse_salary_to_lpa(salary_text)

            # Experience snippet
            card_text = card.get_text(" ", strip=True)
            min_exp, max_exp = parse_experience_range(card_text)

            # Easy Apply Flag on Indeed
            is_easy = "easily apply" in card_text.lower() or "responsive employer" in card_text.lower() or card.select_one(".iaIcon, [data-testid='indeedApply']") is not None

            # Snippet description
            desc_el = card.select_one(".job-snippet, ul, .css-9446fg")
            job_desc = desc_el.get_text(strip=True) if desc_el else f"{title} at {company}"

            return {
                "job_id": str(job_id),
                "platform": "indeed",
                "title": title,
                "company": company,
                "location": location,
                "experience": f"{min_exp or 0}-{max_exp or 1} Yrs" if min_exp is not None else "",
                "min_exp": min_exp,
                "max_exp": max_exp,
                "salary_text": salary_text,
                "min_ctc_lpa": min_ctc,
                "max_ctc_lpa": max_ctc,
                "job_description": job_desc,
                "skills_required": title,
                "apply_url": apply_url,
                "is_easy_apply": is_easy
            }
        except Exception:
            return None
