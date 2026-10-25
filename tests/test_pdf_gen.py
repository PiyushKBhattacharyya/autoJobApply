import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pdf_generator import generate_resume_pdf

sample_profile = {
    "name": "Alex Mercer",
    "contact": {
        "email": "alex.mercer@example.com",
        "phone": "+91 98765 43210",
        "location": "Bengaluru, India",
        "linkedin": "https://linkedin.com/in/alex-mercer",
        "github": "https://github.com/alex-mercer"
    },
    "summary": "Results-oriented Senior Full Stack Engineer with 4+ years of experience designing scalable microservices, high-throughput APIs, and modern responsive web apps. Adept at Python, FastAPI, React, and cloud architectures.",
    "skills": {
        "languages": ["Python", "TypeScript", "JavaScript", "SQL"],
        "frameworks": ["FastAPI", "Django", "React", "Node.js"],
        "databases": ["PostgreSQL", "Redis", "MongoDB"],
        "cloud_devops": ["AWS (ECS, S3, RDS)", "Docker", "Kubernetes", "GitHub Actions"],
        "tools_methodologies": ["REST APIs", "GraphQL", "Agile/Scrum", "Microservices"]
    },
    "experience": [
        {
            "company": "TechNova Solutions",
            "role": "Senior Full Stack Engineer",
            "location": "Bengaluru, India",
            "start_date": "06/2022",
            "end_date": "Present",
            "bullets": [
                "Architected and deployed 8 microservices handling 4M+ daily API requests with 99.98% uptime.",
                "Spearheaded database query optimization on PostgreSQL, reducing average response latency by 35%.",
                "Mentored a team of 4 junior developers and led code reviews ensuring high test coverage (>85%)."
            ]
        },
        {
            "company": "Apex Digital Labs",
            "role": "Software Engineer",
            "location": "Pune, India",
            "start_date": "07/2020",
            "end_date": "05/2022",
            "bullets": [
                "Built responsive customer dashboards in React and TypeScript, increasing user engagement by 22%.",
                "Implemented secure OAuth2 authentication flow and integrated payment gateways with Stripe & Razorpay."
            ]
        }
    ],
    "projects": [
        {
            "title": "Cloud-Native Task Orchestrator",
            "tech_stack": ["Python", "FastAPI", "Redis", "Docker"],
            "link": "https://github.com/alex-mercer/orchestrator",
            "bullets": [
                "Designed a distributed background job queue capable of processing 10,000 asynchronous tasks per minute.",
                "Automated zero-downtime deployment pipeline with Docker and GitHub Actions."
            ]
        }
    ],
    "education": [
        {
            "degree": "B.Tech in Computer Science & Engineering",
            "institution": "National Institute of Technology",
            "year": "2020",
            "score": "8.8 CGPA"
        }
    ],
    "certifications": [
        "AWS Certified Solutions Architect – Associate",
        "Certified Kubernetes Application Developer (CKAD)"
    ]
}

if __name__ == "__main__":
    out_file = Path("output/resumes/sample_test_resume.pdf")
    pdf_path = generate_resume_pdf(sample_profile, out_file)
    print(f"Generated test PDF: {pdf_path} (exists={pdf_path.exists()}, size={pdf_path.stat().st_size} bytes)")
