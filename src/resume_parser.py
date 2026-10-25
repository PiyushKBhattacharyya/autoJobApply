import json
from pathlib import Path
from typing import Any, Dict, Optional
import pypdf
import pdfplumber
from google import genai
from google.genai import types

from src.config import BASE_DIR, load_config


RESUME_SCHEMA_PROMPT = """
You are an expert resume parser and ATS engineer.
Parse the following raw resume text extracted from a PDF and convert it into a structured, clean JSON object.

Strict JSON format to produce:
{
  "name": "Full Name",
  "contact": {
    "email": "user@example.com",
    "phone": "+91...",
    "location": "City, State",
    "linkedin": "linkedin.com/in/...",
    "github": "github.com/...",
    "portfolio": "..."
  },
  "summary": "Professional summary paragraph...",
  "skills": {
    "languages": ["Python", "JavaScript", ...],
    "frameworks": ["Django", "FastAPI", "React", ...],
    "databases": ["PostgreSQL", "MongoDB", "Redis", ...],
    "cloud_devops": ["AWS", "Docker", "Kubernetes", "CI/CD", ...],
    "tools_methodologies": ["Git", "Agile", "REST APIs", ...]
  },
  "experience": [
    {
      "company": "Company Name",
      "role": "Software Engineer",
      "location": "City, Country",
      "start_date": "MM/YYYY or YYYY",
      "end_date": "Present or MM/YYYY",
      "bullets": [
        "Action verb + quantifiable achievement + technologies used",
        "..."
      ]
    }
  ],
  "projects": [
    {
      "title": "Project Name",
      "tech_stack": ["Tech1", "Tech2"],
      "link": "https://...",
      "bullets": [
        "Description of project, problem solved, impact",
        "..."
      ]
    }
  ],
  "education": [
    {
      "degree": "B.Tech in Computer Science",
      "institution": "University Name",
      "year": "2020",
      "score": "8.5 CGPA or percentage"
    }
  ],
  "certifications": [
    "AWS Certified Solutions Architect",
    "..."
  ]
}

Instructions:
1. Extract ALL details accurately. Do not omit any work experience or technical skills.
2. If certain links or contact info are not present, set them to empty strings.
3. Return ONLY valid JSON, with no markdown code blocks or surrounding commentary.
"""


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract plain text from PDF using pdfplumber, falling back to pypdf."""
    text_content = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    text_content.append(extracted)
    except Exception as e:
        print(f"pdfplumber extraction failed: {e}. Falling back to pypdf.")
        with open(pdf_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text_content.append(extracted)

    return "\n\n".join(text_content).strip()


def parse_master_resume(
    pdf_path: Optional[Path] = None,
    output_json_path: Optional[Path] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """Parse a master resume PDF into structured JSON using Gemini API."""
    config = load_config()
    target_pdf = pdf_path or config.resume.master_pdf_abs
    target_output = output_json_path or config.resume.master_profile_abs
    gemini_key = api_key or config.gemini.api_key

    if not target_pdf.exists():
        raise FileNotFoundError(
            f"Master resume PDF not found at: {target_pdf}\n"
            f"Please copy your resume PDF to '{target_pdf}' and run again."
        )

    if not gemini_key:
        raise ValueError(
            "GEMINI_API_KEY is not set. Please add it to your .env file or environment variables."
        )

    print(f"Extracting raw text from {target_pdf.name}...")
    raw_text = extract_text_from_pdf(target_pdf)
    if not raw_text:
        raise ValueError(f"Could not extract any readable text from {target_pdf}. Ensure it is not a scanned image PDF.")

    print(f"Extracted {len(raw_text)} characters. Structuring resume with Gemini...")
    client = genai.Client(api_key=gemini_key)

    prompt = f"{RESUME_SCHEMA_PROMPT}\n\nRAW RESUME TEXT:\n{raw_text}"
    response = client.models.generate_content(
        model=config.gemini.model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2
        )
    )

    clean_text = response.text.strip()
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    if clean_text.startswith("```"):
        clean_text = clean_text[3:]
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]

    parsed_data = json.loads(clean_text.strip())

    # Save structured JSON
    target_output.parent.mkdir(parents=True, exist_ok=True)
    with open(target_output, "w", encoding="utf-8") as f:
        json.dump(parsed_data, f, indent=2, ensure_ascii=False)

    # Also save an editable Markdown version for easy user review
    md_path = target_output.with_suffix(".md")
    export_profile_to_markdown(parsed_data, md_path)

    print(f"Successfully created structured master profile:")
    print(f" - JSON: {target_output}")
    print(f" - Markdown: {md_path}")

    return parsed_data


def export_profile_to_markdown(profile: Dict[str, Any], output_path: Path):
    """Exports structured resume profile to a clean, human-readable Markdown format."""
    contact = profile.get("contact", {})
    contact_parts = [
        contact.get("email", ""),
        contact.get("phone", ""),
        contact.get("location", ""),
        contact.get("linkedin", ""),
        contact.get("github", "")
    ]
    contact_line = " | ".join([p for p in contact_parts if p])

    lines = [
        f"# {profile.get('name', 'Your Name')}",
        contact_line,
        "",
        "## Professional Summary",
        profile.get("summary", ""),
        "",
        "## Technical Skills"
    ]

    skills = profile.get("skills", {})
    if isinstance(skills, dict):
        for cat, items in skills.items():
            if items:
                cat_title = cat.replace("_", " ").title()
                lines.append(f"- **{cat_title}**: {', '.join(items)}")
    elif isinstance(skills, list):
        lines.append(f"- {', '.join(skills)}")

    lines.append("")
    lines.append("## Professional Experience")
    for exp in profile.get("experience", []):
        header = f"### {exp.get('role', '')} | {exp.get('company', '')}"
        date_loc = f"*{exp.get('start_date', '')} - {exp.get('end_date', '')} | {exp.get('location', '')}*"
        lines.extend([header, date_loc])
        for b in exp.get("bullets", []):
            lines.append(f"- {b}")
        lines.append("")

    if profile.get("projects"):
        lines.append("## Key Projects")
        for proj in profile.get("projects", []):
            tech = f" ({', '.join(proj.get('tech_stack', []))})" if proj.get("tech_stack") else ""
            lines.append(f"### {proj.get('title', '')}{tech}")
            for b in proj.get("bullets", []):
                lines.append(f"- {b}")
            lines.append("")

    if profile.get("education"):
        lines.append("## Education")
        for edu in profile.get("education", []):
            lines.append(f"- **{edu.get('degree', '')}**, {edu.get('institution', '')} ({edu.get('year', '')}) - {edu.get('score', '')}")
        lines.append("")

    if profile.get("certifications"):
        lines.append("## Certifications")
        for cert in profile.get("certifications", []):
            lines.append(f"- {cert}")
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
