import math
import random
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from bs4 import BeautifulSoup
from playwright.sync_api import BrowserContext, Page, sync_playwright

from src.config import BASE_DIR, load_config
from src.db import job_exists, save_job


def parse_salary_to_lpa(salary_text: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Parses strings like '12-18 Lacs P.A.', '15-20 LPA', '10 Lacs PA'
    into (min_ctc_lpa, max_ctc_lpa).
    Returns (None, None) if not disclosed or unparseable.
    """
    if not salary_text or "not disclosed" in salary_text.lower():
        return None, None

    # Pattern for range: "12-18 Lacs", "12 - 18 LPA", "12.5 - 18.5 Lacs"
    range_match = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*(?:lacs|lpa|lac)", salary_text, re.IGNORECASE)
    if range_match:
        try:
            return float(range_match.group(1)), float(range_match.group(2))
        except ValueError:
            pass

    # Single value: "15 Lacs", "15 LPA"
    single_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:lacs|lpa|lac)", salary_text, re.IGNORECASE)
    if single_match:
        try:
            val = float(single_match.group(1))
            return val, val
        except ValueError:
            pass

def parse_experience_range(exp_text: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Parses experience strings like '0-1 Yrs', '1-3 Yrs', '2 Yrs', '0-2 Yrs'
    into (min_exp_years, max_exp_years).
    Returns (None, None) if unparseable.
    """
    if not exp_text:
        return None, None

    # Range like "0-1 Yrs", "1-3 Yrs"
    range_match = re.search(r"(\d+)\s*-\s*(\d+)", exp_text)
    if range_match:
        try:
            return int(range_match.group(1)), int(range_match.group(2))
        except ValueError:
            pass

    # Single number like "1 Yr", "2 Yrs"
    single_match = re.search(r"(\d+)", exp_text)
    if single_match:
        try:
            val = int(single_match.group(1))
            return val, val
        except ValueError:
            pass

    return None, None


def random_human_delay(min_sec: float = 2.0, max_sec: float = 5.0):
    time.sleep(random.uniform(min_sec, max_sec))


class NaukriScraper:
    def __init__(self, headless: Optional[bool] = None):
        self.config = load_config()
        self.headless = headless if headless is not None else self.config.bot.headless
        self.context_dir = self.config.bot.browser_context_abs

    def get_browser_context(self, playwright_instance) -> BrowserContext:
        """Launch a persistent context that retains login cookies and session."""
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
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            args=args
        )
        return context

    def interactive_login(self):
        """Opens Naukri login page in headed mode for the user to log in and save session."""
        print("\nOpening Naukri Login in headed browser...")
        print("Please log in using your credentials, OTP, or Google SSO.")
        print("Once logged in and on the homepage/dashboard, press ENTER in the terminal to save session.\n")

        with sync_playwright() as p:
            # Force headed mode for user interaction
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(self.context_dir),
                headless=False,
                viewport={"width": 1366, "height": 768},
                args=["--disable-blink-features=AutomationControlled"]
            )
            page = context.new_page()
            page.goto("https://www.naukri.com/nlogin/login", wait_until="domcontentloaded")

            input(">> Press [ENTER] here after you have successfully logged in on the browser window: ")

            print("Saving login session...")
            random_human_delay(1.0, 2.0)
            context.close()
            print("✓ Session successfully preserved in .browser_context/!")

    def build_search_url(
        self,
        role: str,
        city: str,
        experience: int = 0,
        page_num: int = 1
    ) -> str:
        """Build standard Naukri search URL."""
        role_slug = re.sub(r"[^\w\s-]", "", role).strip().lower()
        role_slug = re.sub(r"[-\s]+", "-", role_slug)

        city_slug = re.sub(r"[^\w\s-]", "", city).strip().lower()
        city_slug = re.sub(r"[-\s]+", "-", city_slug)

        url = f"https://www.naukri.com/{role_slug}-jobs-in-{city_slug}"
        params = []
        if experience > 0:
            params.append(f"experience={experience}")
        if page_num > 1:
            params.append(f"pageNo={page_num}")

        if params:
            url += "?" + "&".join(params)
        return url

    def search_jobs(
        self,
        role: Optional[str] = None,
        city: Optional[str] = None,
        min_ctc_lpa: Optional[float] = None,
        max_ctc_lpa: Optional[float] = None,
        experience: Optional[int] = None,
        max_results: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Searches Naukri for jobs matching role, city, and CTC filters,
        extracts details, and saves to SQLite database.
        """
        role = role or self.config.search.role
        city = city or self.config.search.city
        min_ctc = min_ctc_lpa if min_ctc_lpa is not None else self.config.search.min_ctc_lpa
        max_ctc = max_ctc_lpa if max_ctc_lpa is not None else self.config.search.max_ctc_lpa
        exp = experience if experience is not None else self.config.search.experience_years
        limit = max_results or self.config.search.max_results

        print(f"\n🔍 Searching Naukri for '{role}' in '{city}' (CTC: {min_ctc}-{max_ctc} LPA, Exp: {exp} yrs)...")

        discovered_jobs: List[Dict[str, Any]] = []

        with sync_playwright() as p:
            context = self.get_browser_context(p)
            page = context.new_page()

            # Evade webdriver detection
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            current_page = 1
            while len(discovered_jobs) < limit:
                search_url = self.build_search_url(role, city, exp, page_num=current_page)
                print(f"Loading page {current_page}: {search_url}")

                try:
                    page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
                    random_human_delay(3.0, 5.0)

                    # Scroll down smoothly to trigger lazy-loaded job cards
                    for _ in range(4):
                        page.mouse.wheel(0, 800)
                        time.sleep(0.8)

                    html = page.content()
                    soup = BeautifulSoup(html, "html.parser")

                    # Naukri job card selectors
                    job_cards = soup.select(".srp-jobtuple-wrapper, .cust-job-tuple, article.jobTuple")
                    if not job_cards:
                        # Fallback query for newer naukri card structure
                        job_cards = soup.select("div[data-job-id]")

                    if not job_cards:
                        print("No job cards found on page. Search might have reached end or requires captcha resolution.")
                        break

                    print(f"Found {len(job_cards)} job cards on page {current_page}.")

                    for card in job_cards:
                        if len(discovered_jobs) >= limit:
                            break

                        parsed = self._parse_job_card(card)
                        if not parsed:
                            continue

                        # Experience Filter validation:
                        # Candidate has at most `exp` years of experience.
                        # If a job requires more than `exp` minimum experience (e.g. requires 2+ or 3-5 years), skip it.
                        job_min_exp = parsed.get("min_exp")
                        if job_min_exp is not None and job_min_exp > exp:
                            continue

                        # CTC Filter validation
                        job_min_ctc = parsed.get("min_ctc_lpa")
                        job_max_ctc = parsed.get("max_ctc_lpa")

                        # If job has disclosed CTC, check if within range
                        if job_max_ctc is not None and job_max_ctc < min_ctc:
                            # Below user's minimum CTC expectation
                            continue

                        # Save to DB
                        saved = save_job(parsed)
                        if saved:
                            discovered_jobs.append(parsed)
                            print(f"  + [{parsed['company']}] {parsed['title']} ({parsed['salary_text']})")

                    current_page += 1
                    random_human_delay(2.0, 4.0)

                except Exception as e:
                    print(f"Error during search on page {current_page}: {e}")
                    break

            context.close()

        print(f"\n✓ Discovered & saved {len(discovered_jobs)} matching jobs to data/jobs.db.")
        return discovered_jobs

    def _parse_job_card(self, card) -> Optional[Dict[str, Any]]:
        """Extract attributes from a single job card element."""
        try:
            # Job ID
            job_id = card.get("data-job-id") or card.get("id")

            # Title & Link
            title_el = card.select_one("a.title, .title a, a[title]")
            title = title_el.get_text(strip=True) if title_el else ""
            apply_url = title_el.get("href", "") if title_el else ""

            if not job_id and apply_url:
                # Try extracting job ID from URL (e.g. -job-123456789)
                id_match = re.search(r"-(\d{10,})", apply_url)
                if id_match:
                    job_id = id_match.group(1)

            if not job_id:
                # Generate deterministic fallback ID from title + company
                comp_el = card.select_one(".comp-name, .subTitle, a.subTitle")
                comp_text = comp_el.get_text(strip=True) if comp_el else "unknown"
                job_id = f"job_{abs(hash(title + comp_text))}"

            # Company
            company_el = card.select_one(".comp-name, .subTitle, a.subTitle, .companyInfo a")
            company = company_el.get_text(strip=True) if company_el else "Unknown Company"

            # Experience
            exp_el = card.select_one(".expwdth, .exp-wrap, li.experience, span.ni-job-tuple-icon-experience + span")
            experience = exp_el.get_text(strip=True) if exp_el else ""
            min_exp, max_exp = parse_experience_range(experience)

            # Salary
            sal_el = card.select_one(".sal-wrap, li.salary, span.ni-job-tuple-icon-salary + span")
            salary_text = sal_el.get_text(strip=True) if sal_el else "Not Disclosed"
            min_ctc, max_ctc = parse_salary_to_lpa(salary_text)

            # Location
            loc_el = card.select_one(".loc-wrap, li.location, span.ni-job-tuple-icon-location + span")
            location = loc_el.get_text(strip=True) if loc_el else ""

            # Skills
            skills_els = card.select(".tags-gt li, .tag-li, .tagsAndSkills span, ul.tags li")
            skills_list = [s.get_text(strip=True) for s in skills_els if s.get_text(strip=True)]
            skills_text = ", ".join(skills_list)

            # Job Description snippet
            desc_el = card.select_one(".job-desc, .job-description, .desc")
            job_desc = desc_el.get_text(strip=True) if desc_el else f"{title} at {company}. Skills: {skills_text}"

            # Easy Apply flag
            # External listings often say "Apply on company site" or "Company site" or have specific tags
            card_text_lower = card.get_text(" ", strip=True).lower()
            is_external = "company site" in card_text_lower or "apply on company" in card_text_lower
            
            # Direct apply indicator
            easy_badge = card.select_one(".easy-apply, [data-easy-apply='true'], .ni-job-tuple-icon-easy-apply, .easyApply")
            is_direct_badge = easy_badge is not None or "easy apply" in card_text_lower
            
            # If explicit external tag, is_easy_apply is False. If explicit direct badge, True.
            # Default to False if undetermined to prevent false positives in Easy Apply Only mode.
            is_easy_apply = (not is_external) and is_direct_badge

            return {
                "job_id": str(job_id),
                "title": title,
                "company": company,
                "location": location,
                "experience": experience,
                "min_exp": min_exp,
                "max_exp": max_exp,
                "salary_text": salary_text,
                "min_ctc_lpa": min_ctc,
                "max_ctc_lpa": max_ctc,
                "job_description": job_desc,
                "skills_required": skills_text,
                "apply_url": apply_url,
                "is_easy_apply": is_easy_apply
            }
        except Exception as e:
            return None

    def fetch_full_job_description(self, job_url: str) -> str:
        """Optionally fetches the full extended JD from the job listing page."""
        if not job_url:
            return ""

        full_desc = ""
        with sync_playwright() as p:
            context = self.get_browser_context(p)
            page = context.new_page()
            try:
                page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
                random_human_delay(2.0, 3.5)
                desc_el = page.query_selector(".styles_JDC__dang-inner-html__73O4a, .job-desc-section, .jd-container")
                if desc_el:
                    full_desc = desc_el.inner_text()
            except Exception as e:
                print(f"Could not fetch full JD from {job_url}: {e}")
            context.close()
        return full_desc
