import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import pdfplumber
import pypdf
from google import genai
from google.genai import types

from src.config import BASE_DIR, load_config


RESUME_SCHEMA_PROMPT = """
You are an expert resume parser and ATS engineer.
Parse the following raw resume text and extracted clickable hyperlinks from a PDF, and convert it into a structured, clean JSON object.

Strict JSON format to produce:
{
  "name": "Full Name",
  "contact": {
    "email": "user@example.com",
    "phone": "+91...",
    "location": "City, State",
    "linkedin": "https://linkedin.com/in/...",
    "github": "https://github.com/...",
    "portfolio": "https://..."
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
    {
      "name": "Certificate Name",
      "link": "https://..."
    }
  ],
  "publications": [
    {
      "title": "Paper Title",
      "link": "https://doi.org/..."
    }
  ]
}

Instructions:
1. Extract ALL details accurately. Do not omit any work experience or technical skills.
2. CRITICAL - HYPERLINKS & URLs:
   - Pay close attention to the "EXTRACTED CLICKABLE HYPERLINKS" section below.
   - Associate each URL with its proper entity:
     - Map portfolio URL to contact.portfolio
     - Map github URL to contact.github
     - Map linkedin URL to contact.linkedin
     - Map project demo / code URLs to the corresponding item in the projects array as "link"
     - Map certificate drive links to certifications array as "link"
     - Map publication/DOI URLs to publications array as "link"
3. If certain links or contact info are not present, set them to empty strings.
4. Return ONLY valid JSON, with no markdown code blocks or surrounding commentary.
"""


def extract_text_and_links_from_pdf(pdf_path: Path) -> Tuple[str, List[Dict[str, str]]]:
    """
    Extracts visible text and all embedded clickable hyperlinks / annotations
    from a PDF using pdfplumber and pypdf.
    """
    text_content = []
    extracted_links = []

    # 1. Try pdfplumber for both text and hyperlinks
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_idx, page in enumerate(pdf.pages, 1):
                page_text = page.extract_text()
                if page_text:
                    text_content.append(page_text)

                for link in getattr(page, "hyperlinks", []):
                    uri = link.get("uri")
                    if uri:
                        anchor_text = ""
                        try:
                            bbox = (link["x0"], link["top"], link["x1"], link["bottom"])
                            cropped = page.crop(bbox)
                            anchor_text = cropped.extract_text() or ""
                        except Exception:
                            pass
                        extracted_links.append({
                            "page": str(page_idx),
                            "anchor": anchor_text.strip(),
                            "url": uri
                        })
    except Exception as e:
        print(f"pdfplumber extraction note: {e}")

    # Fallback/supplement with pypdf if text or links missing
    if not text_content or not extracted_links:
        try:
            reader = pypdf.PdfReader(str(pdf_path))
            if not text_content:
                for page in reader.pages:
                    t = page.extract_text()
                    if t:
                        text_content.append(t)

            if not extracted_links:
                for page_idx, page in enumerate(reader.pages, 1):
                    if "/Annots" in page:
                        for annot in page["/Annots"]:
                            obj = annot.get_object()
                            if obj.get("/Subtype") == "/Link":
                                action = obj.get("/A")
                                if action and "/URI" in action:
                                    extracted_links.append({
                                        "page": str(page_idx),
                                        "anchor": str(obj.get("/Contents", "")),
                                        "url": str(action["/URI"])
                                    })
        except Exception as e:
            print(f"pypdf extraction note: {e}")

    return "\n\n".join(text_content).strip(), extracted_links


def parse_master_resume(
    pdf_path: Optional[Path] = None,
    output_json_path: Optional[Path] = None,
    api_key: Optional[str] = None,
    model_name: Optional[str] = None
) -> Dict[str, Any]:
    """Parse a master resume PDF into structured JSON using Gemini API."""
    config = load_config()
    target_pdf = pdf_path or config.resume.master_pdf_abs
    target_output = output_json_path or config.resume.master_profile_abs
    gemini_key = api_key or config.gemini.api_key
    selected_model = model_name or config.gemini.model_name

    if not target_pdf.exists():
        raise FileNotFoundError(
            f"Master resume PDF not found at: {target_pdf}\n"
            f"Please copy your resume PDF to '{target_pdf}' and run again."
        )

    if not gemini_key:
        raise ValueError(
            "GEMINI_API_KEY is not set. Please add it to your .env file or environment variables."
        )

    print(f"Extracting raw text and clickable hyperlinks from {target_pdf.name}...")
    raw_text, extracted_links = extract_text_and_links_from_pdf(target_pdf)
    if not raw_text:
        raise ValueError(f"Could not extract any readable text from {target_pdf}. Ensure it is not a scanned image PDF.")

    # Format extracted hyperlinks for the prompt
    links_section_lines = ["\nEXTRACTED CLICKABLE HYPERLINKS IN DOCUMENT:"]
    for idx, l in enumerate(extracted_links, 1):
        anchor = f"'{l['anchor']}'" if l['anchor'] else "(No Anchor Text)"
        links_section_lines.append(f"{idx}. Anchor: {anchor} (Page {l['page']}) -> URL: {l['url']}")

    links_section = "\n".join(links_section_lines)
    print(f"Extracted {len(raw_text)} chars of text and {len(extracted_links)} clickable hyperlinks.")
    print(f"Structuring resume with Gemini [{selected_model}]...")

    client = genai.Client(api_key=gemini_key)
    prompt = f"{RESUME_SCHEMA_PROMPT}\n\nRAW RESUME TEXT:\n{raw_text}\n{links_section}"

    try:
        response = client.models.generate_content(
            model=selected_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2
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

    parsed_data = json.loads(clean_text.strip())

    # Save structured JSON
    target_output.parent.mkdir(parents=True, exist_ok=True)
    with open(target_output, "w", encoding="utf-8") as f:
        json.dump(parsed_data, f, indent=2, ensure_ascii=False)

    # Also save an editable Markdown version for easy user review
    md_path = target_output.with_suffix(".md")
    export_profile_to_markdown(parsed_data, md_path)

    print(f"✓ Successfully created structured master profile:")
    print(f" - JSON: {target_output}")
    print(f" - Markdown: {md_path}")

    return parsed_data


def export_profile_to_markdown(profile: Dict[str, Any], output_path: Path):
    """Exports structured resume profile to a clean, human-readable Markdown format."""
    contact = profile.get("contact", {})
    contact_parts = []
    if contact.get("email"):
        contact_parts.append(f"[{contact['email']}](mailto:{contact['email']})")
    if contact.get("phone"):
        contact_parts.append(contact["phone"])
    if contact.get("location"):
        contact_parts.append(contact["location"])
    if contact.get("linkedin"):
        contact_parts.append(f"[LinkedIn]({contact['linkedin']})")
    if contact.get("github"):
        contact_parts.append(f"[GitHub]({contact['github']})")
    if contact.get("portfolio"):
        contact_parts.append(f"[Portfolio]({contact['portfolio']})")

    contact_line = " | ".join(contact_parts)

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
            title = proj.get("title", "")
            link = proj.get("link", "")
            title_md = f"[{title}]({link})" if link else title
            lines.append(f"### {title_md}{tech}")
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
            if isinstance(cert, dict):
                c_name = cert.get("name", "")
                c_link = cert.get("link", "")
                lines.append(f"- [{c_name}]({c_link})" if c_link else f"- {c_name}")
            else:
                lines.append(f"- {cert}")
        lines.append("")

    if profile.get("publications"):
        lines.append("## Publications")
        for pub in profile.get("publications", []):
            if isinstance(pub, dict):
                p_title = pub.get("title", "")
                p_link = pub.get("link", "")
                lines.append(f"- [{p_title}]({p_link})" if p_link else f"- {p_title}")
            else:
                lines.append(f"- {pub}")
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
