import os
import re
import sys
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from playwright.sync_api import BrowserContext, sync_playwright

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from src.config import BASE_DIR, load_config
from src.db import save_job
from src.naukri_scraper import parse_experience_range, parse_salary_to_lpa, random_human_delay


class LinkedInScraper:
    def __init__(self, headless: Optional[bool] = None):
        self.config = load_config()
        self.headless = headless if headless is not None else self.config.bot.headless
        # Dedicated persistent context directory for LinkedIn session
        self.context_dir = BASE_DIR / ".browser_context_linkedin"
        self.context_dir.mkdir(parents=True, exist_ok=True)

    def get_browser_context(self, playwright_instance) -> BrowserContext:
        """Launch a persistent context retaining LinkedIn login cookies and session."""
        args = [
            "--disable-blink-features=AutomationControlled",
            "--start-maximized",
            "--no-sandbox",
            "--disable-dev-shm-usage"
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
        """Opens LinkedIn login page in headed mode with stealth args for the user to log in."""
        print("\nOpening LinkedIn Login in headed browser...")
        print("Please log in using your LinkedIn credentials, 2FA, or Google SSO.")
        print("Once you are on your LinkedIn feed/dashboard, press ENTER in the terminal to save your session.\n")

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

            # Evade navigator.webdriver detection
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")

            input(">> Press [ENTER] here after you have successfully logged in on LinkedIn: ")

            # Verify if user has session cookie (li_at)
            cookies = context.cookies()
            has_auth = any(c.get("name") == "li_at" for c in cookies)
            if has_auth:
                print("✓ Verified valid LinkedIn authenticated session cookie (li_at)!")
            else:
                print("⚠ Warning: 'li_at' session cookie was not detected. Please ensure you are fully logged in to your feed.")

            print("Saving LinkedIn login session...")
            random_human_delay(1.5, 3.0)
            context.close()
            print("✓ LinkedIn session successfully preserved in .browser_context_linkedin/!")

    def build_search_url(self, role: str, city: str, page_num: int = 1) -> str:
        """
        Builds LinkedIn search URL with 'Easy Apply' filter (f_AL=true).
        """
        keywords = quote_plus(role)
        location = quote_plus(city)
        start = (page_num - 1) * 25
        url = f"https://www.linkedin.com/jobs/search/?keywords={keywords}&location={location}&f_AL=true"
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
        """Searches LinkedIn for jobs matching criteria, strictly filtering for Easy Apply."""
        role = role or self.config.search.role
        city = city or self.config.search.city
        exp = experience if experience is not None else self.config.search.experience_years
        limit = max_results or self.config.search.max_results

        print(f"\n🔍 Searching LinkedIn for '{role}' in '{city}' (Exp <= {exp} yrs, Easy Apply)...")
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
                print(f"Loading LinkedIn page {current_page}: {search_url}")

                try:
                    page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
                    random_human_delay(3.5, 5.5)

                    # Scroll through job list container to trigger lazy rendering
                    for _ in range(4):
                        page.mouse.wheel(0, 800)
                        time.sleep(0.8)

                    # Extract jobs directly from the live browser DOM to handle randomized/obfuscated class names
                    extracted_cards = page.evaluate("""() => {
                        const results = [];
                        // Target job links with /jobs/view/ or data-job-id
                        const linkEls = Array.from(document.querySelectorAll('a[href*="/jobs/view/"], a[data-control-name*="job_card"]'));
                        const seenIds = new Set();

                        for (const a of linkEls) {
                            const href = a.href;
                            const m = href.match(/\\/jobs\\/view\\/(\\d+)/);
                            const rawId = m ? m[1] : null;
                            if (!rawId || seenIds.has(rawId)) continue;
                            seenIds.add(rawId);

                            // Find top-level card container without getting trapped in job-card-list__title
                            const card = a.closest('.job-card-container') ||
                                         a.closest('[data-job-id]') ||
                                         a.closest('[data-occludable-job-id]') ||
                                         a.closest('li.jobs-search-results__list-item') ||
                                         a.closest('li.scaffold-layout__list-item') ||
                                         a.closest('li') ||
                                         a.closest('.base-card') ||
                                         a.closest('div[class*="job-search-card"]') ||
                                         a.parentElement;

                            const title = (a.innerText || a.getAttribute('aria-label') || '').trim();
                            if (!title) continue;

                            const cardText = card ? card.innerText : '';
                            const lines = cardText.split('\\n').map(l => l.trim()).filter(l => l.length > 0);

                            // Find company name in card lines or company link
                            let company = '';
                            const compEl = card ? (
                                card.querySelector('.job-card-container__primary-description, .artdeco-entity-lockup__subtitle, a[href*="/company/"], [class*="company-name"], [class*="primary-description"], span.job-card-container__primary-description')
                            ) : null;
                            if (compEl && compEl.innerText.trim()) {
                                company = compEl.innerText.trim();
                            } else {
                                for (let i = 0; i < lines.length; i++) {
                                    if (lines[i].toLowerCase() === title.toLowerCase() && i + 1 < lines.length) {
                                        company = lines[i + 1];
                                        break;
                                    }
                                }
                            }
                            if (!company) company = 'Unknown Company';

                            // Location
                            let location = '';
                            const locEl = card ? (
                                card.querySelector('.job-card-container__metadata-item, .job-card-container__metadata-wrapper, [class*="metadata-item"]')
                            ) : null;
                            if (locEl && locEl.innerText.trim()) {
                                location = locEl.innerText.trim();
                            } else {
                                for (const line of lines) {
                                    if (line.includes('Bengaluru') || line.includes('Bangalore') || line.includes('India') || line.includes('Hybrid') || line.includes('On-site') || line.includes('Remote')) {
                                        location = line;
                                        break;
                                    }
                                }
                            }

                            // Since the search URL strictly filters with f_AL=true, these listings are Easy Apply
                            const isEasyApply = true;

                            results.push({
                                job_id: 'linkedin_' + rawId,
                                title: title,
                                company: company,
                                location: location,
                                apply_url: href.split('?')[0],
                                card_text: cardText,
                                is_easy_apply: isEasyApply
                            });
                        }
                        return results;
                    }""")

                    if not extracted_cards:
                        print("No job cards found on LinkedIn page.")
                        break

                    print(f"Found {len(extracted_cards)} job cards on LinkedIn page {current_page}.")

                    for item in extracted_cards:
                        if len(discovered_jobs) >= limit:
                            break

                        min_exp, max_exp = parse_experience_range(item.get("card_text", ""))
                        if min_exp is not None and min_exp > exp:
                            continue

                        parsed = {
                            "job_id": item["job_id"],
                            "platform": "linkedin",
                            "title": item["title"],
                            "company": item["company"],
                            "location": item["location"],
                            "experience": f"{min_exp or 0}-{max_exp or 1} Yrs" if min_exp is not None else "",
                            "min_exp": min_exp,
                            "max_exp": max_exp,
                            "salary_text": "Not Disclosed",
                            "min_ctc_lpa": None,
                            "max_ctc_lpa": None,
                            "job_description": f"{item['title']} at {item['company']}. Location: {item['location']}. Details: {item.get('card_text', '')}",
                            "skills_required": item["title"],
                            "apply_url": item["apply_url"],
                            "is_easy_apply": True
                        }

                        saved = save_job(parsed)
                        if saved:
                            discovered_jobs.append(parsed)
                            print(f"  + [LinkedIn | {parsed['company']}] {parsed['title']}")

                    current_page += 1
                    random_human_delay(2.5, 4.5)

                except Exception as e:
                    print(f"Error during LinkedIn search on page {current_page}: {e}")
                    break

            context.close()

        print(f"\n✓ Discovered & saved {len(discovered_jobs)} matching jobs from LinkedIn.")
        return discovered_jobs

    def _parse_job_card(self, card) -> Optional[Dict[str, Any]]:
        """Extracts standardized attributes from a LinkedIn job card."""
        try:
            # Job ID
            job_id = card.get("data-occludable-job-id") or card.get("data-job-id")
            title_el = card.select_one(".job-card-list__title, a.job-card-container__link, strong")
            title = title_el.get_text(strip=True) if title_el else ""

            link_el = card.select_one("a.job-card-container__link, a[href*='/jobs/view/'], a.base-card__full-link")
            apply_url = ""
            if link_el:
                href = link_el.get("href", "")
                if href.startswith("/"):
                    apply_url = f"https://www.linkedin.com{href}"
                else:
                    apply_url = href.split("?")[0]  # Strip tracking query params

            if not job_id and apply_url:
                m = re.search(r"/view/(\d+)", apply_url)
                if m:
                    job_id = m.group(1)

            if not job_id:
                job_id = f"li_{abs(hash(title + apply_url))}"

            if not str(job_id).startswith("linkedin_"):
                job_id = f"linkedin_{job_id}"

            # Company
            company_el = card.select_one(".job-card-container__primary-description, .artdeco-entity-lockup__subtitle, .base-search-card__subtitle")
            company = company_el.get_text(strip=True) if company_el else "Unknown Company"

            # Location
            loc_el = card.select_one(".job-card-container__metadata-item, .job-search-card__location")
            location = loc_el.get_text(strip=True) if loc_el else ""

            # Salary
            sal_el = card.select_one(".job-card-container__metadata-wrapper, .job-search-card__salary-info")
            salary_text = sal_el.get_text(strip=True) if sal_el else "Not Disclosed"
            min_ctc, max_ctc = parse_salary_to_lpa(salary_text)

            # Experience
            card_text = card.get_text(" ", strip=True)
            min_exp, max_exp = parse_experience_range(card_text)

            # Easy Apply Flag
            is_easy = "easy apply" in card_text.lower() or card.select_one(".job-card-container__apply-method") is not None

            # Job Desc snippet
            desc_el = card.select_one(".job-card-list__snippet, .base-search-card__snippet")
            job_desc = desc_el.get_text(strip=True) if desc_el else f"{title} at {company}"

            return {
                "job_id": str(job_id),
                "platform": "linkedin",
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
