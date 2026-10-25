import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from google import genai
from google.genai import types

from src.config import BASE_DIR, load_config
from src.db import update_application
from src.pdf_generator import generate_resume_pdf


SCHEMA_FORMAT = """{
  "ats_match_score": 85,
  "matched_keywords": ["Python", "FastAPI", "Docker", "Microservices"],
  "missing_keywords": ["Kubernetes", "Kafka"],
  "tailored_profile": {
    "name": "Full Name",
    "contact": {
      "email": "user@example.com",
      "phone": "+91...",
      "location": "City, State",
      "linkedin": "https://linkedin.com/in/...",
      "github": "https://github.com/...",
      "portfolio": "https://..."
    },
    "summary": "Tailored executive summary...",
    "skills": {
      "languages": ["..."],
      "frameworks": ["..."],
      "databases": ["..."],
      "cloud_devops": ["..."],
      "tools_methodologies": ["..."]
    },
    "education": [
      {
        "degree": "Degree",
        "institution": "University",
        "year": "YYYY | YYYY",
        "score": "Score"
      }
    ],
    "experience": [
      {
        "company": "Company",
        "role": "Role",
        "location": "Location",
        "start_date": "MM/YYYY",
        "end_date": "Present",
        "badge_label": "[Certificate]",
        "badge_url": "https://drive.google.com/...",
        "bullets": ["Action verb + quantifiable achievement + relevant technologies"]
      }
    ],
    "projects": [
      {
        "title": "Project Title",
        "tech_stack": ["Tech1", "Tech2"],
        "link": "https://...",
        "bullets": ["Impact and implementation details"]
      }
    ],
    "publications": [
      {
        "title": "Paper Title",
        "link": "https://..."
      }
    ]
  }
}"""


def build_tailoring_prompt(job: Dict[str, Any], master_profile: Dict[str, Any], target_pages: int = 1) -> str:
    """Build the prompt cleanly without string formatting collisions with JSON braces."""
    if target_pages == 1:
        page_density_guidance = (
            "- 1-PAGE RESUME STRICT REQUIREMENT:\n"
            "  * The resume MUST strictly fit onto 1 single page without spilling onto page 2.\n"
            "  * Summary: Strong, concise 2 to 3 sentences (max 60-75 words) focused on candidate's direct fit.\n"
            "  * Experience: Exactly 2 high-impact, metric-driven STAR bullet points for each of the 5 experience entries.\n"
            "  * Projects: Exactly 2 impactful bullets for each of the 2 key projects.\n"
            "  * Publications: Retain all 3 publications.\n"
            "  * Keep bullets punchy, concrete, and tightly worded so they cleanly fit on 1 page."
        )
    else:
        page_density_guidance = (
            "- 2-PAGE RESUME & PAGE FILL REQUIREMENT:\n"
            "  * Provide comprehensive accomplishments across all 5 experiences (3-5 detailed bullet points each).\n"
            "  * Include in-depth architectural and implementation bullets across projects, and all 3 research publications to balance and fill 2 pages evenly."
        )

    return f"""You are an expert Executive Resume Writer and ATS Optimization Specialist.
Your task is to tailor a candidate's master resume profile specifically for a target job posting to maximize ATS keyword scoring, recruiter relevance, and interview conversion.

TARGET JOB DETAILS:
- Title: {job.get('title', '')}
- Company: {job.get('company', '')}
- Location: {job.get('location', '')}
- Experience Required: {job.get('experience', '')}
- Skills Mentioned: {job.get('skills_required', '')}
- Full Job Description:
\"\"\"{job.get('job_description', '')[:4000]}\"\"\"

CANDIDATE MASTER PROFILE (JSON):
\"\"\"{json.dumps(master_profile, ensure_ascii=False)}\"\"\"

CRITICAL RULES:
1. NO HALLUCINATION: Do NOT invent fake companies, fake degrees, or years of experience the candidate does not have. Rephrase, reorganize, and emphasize authentic skills and accomplishments from the master profile.
2. EXACT ORIGINAL HEADINGS - NO SEPARATE CERTIFICATIONS SECTION:
   The candidate's original resume has exactly these 6 sections:
   - Summary
   - Technical Skills
   - Education
   - Experience
   - Projects
   - Publications
   DO NOT create a separate 'Certifications', 'Certifications & Internships', or 'Publications & Research' section.
   In the original resume, certificates were issued by companies for work experience/internships (IOCL, NIELIT, NIC, IIT Guwahati).
   Preserve them directly inside their respective Experience entries as `badge_label` (e.g., "[Certificate]" or "[Project]") and `badge_url`.
3. FILL THE RESUME (ELIMINATE EMPTY SPACES):
   Empty space or large blank areas on a resume look unprofessional. Ensure bullet points are descriptive, metric-driven, and technical. Each bullet should be substantive, providing concrete context, tools used, and quantifiable results to fill the page height evenly and completely.
   {page_density_guidance}
4. ATS OPTIMIZATION: Seamlessly integrate relevant keywords and terminology from the job description into the Summary, Technical Skills, and Experience bullet points.
5. ATS MATCH METRICS: Accurately estimate the candidate's ATS Match Score (0 to 100) based on skill coverage, years of experience, and role alignment. List distinct matched keywords and missing keywords.
6. PRESERVE ALL LINKS: Retain all contact links, GitHub, LinkedIn, Portfolio URLs, Project links, Certificate drive links, and Publication DOIs from the master profile.

Return a STRICT JSON response adhering exactly to this schema:
{SCHEMA_FORMAT}

Return ONLY valid raw JSON without markdown code blocks.
"""


def clean_company_name(name: str) -> str:
    """Sanitize company name for clean file naming."""
    clean = re.sub(r"[^\w\s-]", "", name).strip()
    return re.sub(r"[-\s]+", "_", clean)


def print_api_key_help():
    """Prints clear, friendly instructions on how to obtain and configure a Gemini API key."""
    from rich.console import Console
    from rich.panel import Panel
    c = Console()
    msg = """
[bold red]Google Gemini API Key Error Detected[/bold red]

Your Gemini API Key is missing, invalid, or does not have sufficient permissions.

[bold cyan]How to fix this in 3 easy steps:[/bold cyan]
1. Get a free API key from Google AI Studio:
   [bold blue underline]https://aistudio.google.com/app/apikey[/bold blue underline]

2. Open the [bold yellow].env[/bold yellow] file in your project folder:
   [bold white]d:\\Projects\\autoJobApply\\.env[/bold white]

3. Update the key:
   [bold green]GEMINI_API_KEY=AIzaSy...your_actual_key_here[/bold green]

4. Save the file and re-run your command.
    """.strip()
    c.print(Panel(msg, title="[bold red]API Key Troubleshooting Guide[/bold red]", border_style="red"))


def tailor_resume_for_job(
    job: Dict[str, Any],
    master_profile: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
    target_pages: Optional[int] = None
) -> Tuple[Dict[str, Any], Path]:
    """
    Tailor master resume for a specific job using Gemini,
    generate the PDF, and update the application record in SQLite.
    """
    config = load_config()
    gemini_key = api_key or config.gemini.api_key
    selected_model = model_name or config.gemini.model_name
    pages = target_pages or config.resume.target_pages

    if not gemini_key:
        print_api_key_help()
        raise ValueError("GEMINI_API_KEY is not configured in .env. Please follow the instructions above.")

    # Load master profile if not passed
    if master_profile is None:
        profile_path = config.resume.master_profile_abs
        if not profile_path.exists():
            raise FileNotFoundError(
                f"Master profile JSON not found at {profile_path}. "
                "Run `python main.py parse-resume` first."
            )
        with open(profile_path, "r", encoding="utf-8") as f:
            master_profile = json.load(f)

    print(f"Tailoring resume ({pages}-page) for [{job.get('title')}] at [{job.get('company')}] using {selected_model}...")
    client = genai.Client(api_key=gemini_key)

    prompt = build_tailoring_prompt(job, master_profile, target_pages=pages)

    models_to_try = [selected_model]
    for m_cand in ["gemini-3.6-flash", "gemini-3.5-flash"]:
        if m_cand not in models_to_try:
            models_to_try.append(m_cand)

    response = None
    last_err = None

    for curr_model in models_to_try:
        max_retries = 2
        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model=curr_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.3
                    )
                )
                if curr_model != selected_model:
                    print(f"✓ Succeeded using fallback model: {curr_model}")
                break
            except Exception as e:
                last_err = e
                err_msg = str(e)
                if "API_KEY_INVALID" in err_msg or "INVALID_ARGUMENT" in err_msg and "key" in err_msg.lower() or "PERMISSION_DENIED" in err_msg or "UNAUTHENTICATED" in err_msg:
                    print_api_key_help()
                    raise
                elif "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "quota" in err_msg.lower():
                    print(f"[!] Model '{curr_model}' hit quota limit (429).")
                    break  # Break inner retry loop to try next fallback model
                elif "503" in err_msg or "UNAVAILABLE" in err_msg:
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 3
                        print(f"[!] Gemini busy (503). Retrying in {wait_time}s...")
                        import time
                        time.sleep(wait_time)
                        continue
                elif "404" in err_msg or "NOT_FOUND" in err_msg:
                    print(f"[!] Model '{curr_model}' not found (404).")
                    break
                else:
                    raise

        if response is not None:
            break

    if response is None:
        raise last_err or RuntimeError("Failed to generate tailored resume with available Gemini models.")


    clean_text = response.text.strip()
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    if clean_text.startswith("```"):
        clean_text = clean_text[3:]
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]

    result = json.loads(clean_text.strip())

    ats_score = int(result.get("ats_match_score", 70))
    matched_kw = result.get("matched_keywords", [])
    missing_kw = result.get("missing_keywords", [])
    tailored_profile = result.get("tailored_profile", master_profile)

    # Output PDF path
    job_id = job.get("job_id", "unknown")
    company_slug = clean_company_name(job.get("company", "company"))
    pdf_filename = f"{job_id}_{company_slug}.pdf"
    output_pdf_path = config.resume.output_dir_abs / pdf_filename

    # Generate ATS PDF with target_pages styling
    generate_resume_pdf(tailored_profile, output_pdf_path, target_pages=pages)

    # Update database
    update_application(
        job_id=job_id,
        status="TAILORED",
        ats_score=ats_score,
        missing_keywords=", ".join(missing_kw) if isinstance(missing_kw, list) else str(missing_kw),
        matched_keywords=", ".join(matched_kw) if isinstance(matched_kw, list) else str(matched_kw),
        resume_path=str(output_pdf_path),
        tailored_json=json.dumps(tailored_profile, ensure_ascii=False),
        notes=f"ATS Score: {ats_score}% ({pages}-page)"
    )

    print(f"[OK] Tailored PDF generated ({pages}-page): {output_pdf_path} (ATS Score: {ats_score}%)")
    return result, output_pdf_path
