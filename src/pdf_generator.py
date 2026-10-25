from pathlib import Path
from typing import Any, Dict
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright
from src.config import BASE_DIR

TEMPLATES_DIR = BASE_DIR / "templates"


def render_resume_html(profile_data: Dict[str, Any], target_pages: int = 1) -> str:
    """Render profile data into ATS-friendly HTML."""
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("resume_ats.html")
    context = dict(profile_data)
    context["target_pages"] = target_pages
    return template.render(**context)


def generate_resume_pdf(
    profile_data: Dict[str, Any],
    output_pdf_path: Path,
    target_pages: int = 1
) -> Path:
    """
    Renders the profile data using Jinja2 and uses Playwright
    Chromium to compile an ATS-compliant, pixel-perfect PDF.
    """
    output_pdf_path = Path(output_pdf_path)
    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)

    html_content = render_resume_html(profile_data, target_pages=target_pages)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Set content
        page.set_content(html_content, wait_until="networkidle")

        # Generate PDF with @page margins from CSS
        page.pdf(
            path=str(output_pdf_path),
            format="Letter",
            print_background=True,
            prefer_css_page_size=True
        )

        browser.close()

    return output_pdf_path
