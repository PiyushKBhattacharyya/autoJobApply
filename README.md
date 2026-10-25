# Naukri AI Job Hunter & Resume Customizer 🚀

An automated bot that searches Naukri for targeted job postings matching specific **role**, **city**, and **CTC** criteria, extracts job descriptions (JDs), tailors your master resume using **Google Gemini** for high ATS matching scores, and provides dual application workflows (**Supervised Review** and **Autonomous Mode**).

---

## Features

- 🎯 **Targeted Job Search**: Filters Naukri listings by Role/Keyword, City, Experience, and CTC (LPA range).
- 📄 **PDF Master Resume Extractor**: Automatically parses your existing master resume PDF into an editable, structured profile (`master_profile.json` & `master_resume.md`).
- 🤖 **Gemini AI Resume Tailor**: Customizes your summary and experience bullet points (STAR format) to match exact job requirements without fabricating false claims.
- 📈 **ATS Scoring & Keyword Matching**: Calculates ATS match score (0-100%) and highlights matched vs missing keywords.
- 📑 **ATS-Compliant PDF Generator**: Compiles pixel-perfect, single-column ATS PDFs for every job application using Playwright.
- 🛡️ **Anti-Bot Persistent Session**: Stores your authenticated Naukri session cookies locally in `.browser_context/` so you only log in once.
- 🎛️ **Dual Application Modes**:
  - **Supervised Mode**: Interactive terminal review showing job cards, CTC, ATS match score diff, with options to **Approve & Apply**, **Preview PDF**, **Open Job in Browser**, or **Skip**.
  - **Automated Mode**: Hands-free batch execution that automatically applies to jobs above your target CTC and ATS match threshold.
- 💾 **SQLite Application Tracker**: Tracks application status (`DISCOVERED`, `TAILORED`, `APPROVED`, `APPLIED`, `SKIPPED`, `EXTERNAL_REDIRECT`) to prevent duplicate applications.

---

## Project Structure

```text
autoJobApply/
├── config.yaml               # Target role, city, CTC range, mode, thresholds
├── .env                      # API keys (GEMINI_API_KEY)
├── requirements.txt          # Python dependencies
├── main.py                   # Main CLI entrypoint
├── data/
│   ├── jobs.db               # SQLite database tracking jobs & applications
│   ├── master_resume.pdf     # Place your master resume PDF here
│   └── master_profile.json   # Extracted master resume profile
├── output/
│   └── resumes/              # Generated job-specific tailored PDFs
├── src/
│   ├── applier.py            # Naukri application automation flow
│   ├── config.py             # Config & settings manager
│   ├── db.py                 # SQLite database queries & state management
│   ├── naukri_scraper.py     # Playwright search & JD extractor
│   ├── pdf_generator.py      # HTML+CSS to ATS PDF renderer
│   ├── resume_parser.py      # PDF resume parser into structured JSON
│   ├── tailor.py             # Gemini ATS customization engine
│   └── ui.py                 # Rich terminal dashboard & job cards
└── templates/
    └── resume_ats.html       # ATS-compliant single-column resume template
```

---

## Quick Start Guide

### Step 1: Configure Environment & API Key

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` and add your **Gemini API Key** ([Get a key here](https://aistudio.google.com/app/apikey)):
   ```env
   GEMINI_API_KEY=AIzaSy...
   ```

### Step 2: Configure Your Search & CTC Preferences

Open `config.yaml` to set your target search parameters:
```yaml
search:
  role: "Full Stack Developer"
  city: "Bengaluru"
  min_ctc_lpa: 15
  max_ctc_lpa: 30
  experience_years: 1
  max_results: 20

bot:
  mode: "supervised"       # "supervised" or "auto"
  min_match_score: 70      # Minimum ATS score required for auto-apply
```

### Step 3: Add Your Master Resume PDF

Copy your current resume PDF to:
```text
data/master_resume.pdf
```
Then run the extractor:
```bash
.venv\Scripts\python main.py parse-resume
```
This extracts all contact info, summary, skills, experience, and projects into `data/master_profile.json` and `data/master_profile.md`. You can open and edit `master_profile.json` at any time to update your baseline information.

### Step 4: One-Time Naukri Login (Anti-Bot Session)

To allow the bot to search and apply safely without getting blocked by OTP/CAPTCHAs:
```bash
.venv\Scripts\python main.py login
```
A browser window will open to Naukri. Log in to your account. Once logged in and on the homepage, return to the terminal and press `[ENTER]`. Your login session is saved in `.browser_context/`.

---

## Usage Commands

### 1. Run Complete End-to-End Pipeline
```bash
# Supervised mode (recommended: review each job & tailored resume before applying)
.venv\Scripts\python main.py run --mode supervised

# Autonomous mode (hands-free auto-applying for jobs meeting CTC & match score thresholds)
.venv\Scripts\python main.py run --mode auto
```

### 2. Individual Commands

- **List & Change Gemini Models** (dynamically fetches active models from Google API):
  ```bash
  # View all available active models and interactively switch
  .venv\Scripts\python main.py models

  # Directly switch to a specific model
  .venv\Scripts\python main.py set-model gemini-3.8-flash
  ```

- **Parse Resume** (with optional model override):
  ```bash
  .venv\Scripts\python main.py parse-resume --model gemini-3.8-flash
  ```

- **Search Jobs**:
  ```bash
  .venv\Scripts\python main.py search --role "Python Developer" --city "Bengaluru" --min-ctc 15 --max-ctc 25
  ```

- **Tailor Pending Resumes**:
  ```bash
  .venv\Scripts\python main.py tailor --model gemini-3.8-flash
  ```

- **View Status Dashboard**:
  ```bash
  .venv\Scripts\python main.py status
  ```


---

## Supervised Mode Controls

When running in **Supervised Mode**, for each matched job you will see a card with:
- Job Title, Company, City, and Salary/CTC
- ATS Match Score (%)
- Matched Keywords & Missing Keywords
- Direct Link to generated tailored PDF

Options:
- `[A]` **Approve & Apply**: Submits application with tailored resume.
- `[P]` **Preview PDF**: Opens the generated tailored resume in your system's PDF viewer.
- `[O]` **Open URL**: Opens the job posting in your web browser.
- `[S]` **Skip**: Marks the job as skipped in the database.
- `[Q]` **Quit**: Exits the review session (progress is saved in `data/jobs.db`).
