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
    "experience": [
      {
        "company": "Company",
        "role": "Role",
        "location": "Location",
        "start_date": "MM/YYYY",
        "end_date": "Present",
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
    "education": [
      {
        "degree": "Degree",
        "institution": "University",
        "year": "YYYY",
        "score": "Score"
      }
    ],
    "certifications": [
      {
        "name": "Certificate Name",
        "link": "https://..."
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


def build_tailoring_prompt(job: Dict[str, Any], master_profile: Dict[str, Any]) -> str:
    """Build the prompt cleanly without string formatting collisions with JSON braces."""
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
1. NO HALLUCINATION: Do NOT invent fake companies, fake degrees, or years of experience the candidate does not have. You may rephrase, reorganize, and emphasize authentic skills and accomplishments from the master profile.
2. ATS OPTIMIZATION: Seamlessly integrate relevant keywords and terminology from the job description into the Professional Summary and Experience bullet points.
3. IMPACT & METRICS: Ensure bullet points follow the STAR framework (Action Verb + Context/Tech + Quantifiable Result/Impact).
4. SUMMARY: Craft a high-impact 3-4 sentence professional summary explicitly positioning the candidate for this specific role at this company.
5. ATS MATCH METRICS: Accurately estimate the candidate's ATS Match Score (0 to 100) based on skill coverage, years of experience, and role alignment. Also list matched keywords and missing keywords.
6. PRESERVE ALL LINKS: Retain all contact links, GitHub, LinkedIn, Portfolio URLs, Project links, Certificate drive links, and Publication DOIs from the master profile.

Return a STRICT JSON response adhering exactly to this schema:
{SCHEMA_FORMAT}

Return ONLY valid raw JSON without markdown code blocks.
"""


def clean_company_name(name: str) -> str:
    """Sanitize company name for clean file naming."""
    clean = re.sub(r"[^\w\s-]", "", name).strip()
    return re.sub(r"[-\s]+", "_", clean)


def tailor_resume_for_job(
    job: Dict[str, Any],
    master_profile: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None,
    model_name: Optional[str] = None
) -> Tuple[Dict[str, Any], Path]:
    """
    Tailor master resume for a specific job using Gemini,
    generate the PDF, and update the application record in SQLite.
    """
    config = load_config()
    gemini_key = api_key or config.gemini.api_key
    selected_model = model_name or config.gemini.model_name

    if not gemini_key:
        raise ValueError("GEMINI_API_KEY is not configured in .env")

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

    print(f"Tailoring resume for [{job.get('title')}] at [{job.get('company')}] using {selected_model}...")
    client = genai.Client(api_key=gemini_key)

    prompt = build_tailoring_prompt(job, master_profile)

    try:
        response = client.models.generate_content(
            model=selected_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3
            )
        )
    except Exception as e:
        err_msg = str(e)
        if "404" in err_msg or "NOT_FOUND" in err_msg or "not found" in err_msg.lower():
            from src.models_manager import display_models_table, list_available_models
            print(f"\n[!] Model '{selected_model}' is not available or has been retired by Google.")
            models = list_available_models(api_key=gemini_key)
            display_models_table(models, current_model=selected_model)
            print("Tip: Run `python main.py set-model <model-name>` or pass `--model <model-name>`.\n")
        raise

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

    # Generate ATS PDF
    generate_resume_pdf(tailored_profile, output_pdf_path)

    # Update database
    update_application(
        job_id=job_id,
        status="TAILORED",
        ats_score=ats_score,
        missing_keywords=", ".join(missing_kw) if isinstance(missing_kw, list) else str(missing_kw),
        matched_keywords=", ".join(matched_kw) if isinstance(matched_kw, list) else str(matched_kw),
        resume_path=str(output_pdf_path),
        tailored_json=json.dumps(tailored_profile, ensure_ascii=False),
        notes=f"ATS Score: {ats_score}%"
    )

    print(f"[OK] Tailored PDF generated: {output_pdf_path} (ATS Score: {ats_score}%)")
    return result, output_pdf_path

