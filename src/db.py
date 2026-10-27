import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from src.config import BASE_DIR

DB_PATH = BASE_DIR / "data" / "jobs.db"


def get_db_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Table for storing scraped jobs
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            platform TEXT DEFAULT 'naukri',
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT,
            experience TEXT,
            salary_text TEXT,
            min_ctc_lpa REAL,
            max_ctc_lpa REAL,
            job_description TEXT,
            skills_required TEXT,
            apply_url TEXT,
            is_easy_apply INTEGER DEFAULT 0,
            discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Check and add platform column if upgrading from earlier version
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN platform TEXT DEFAULT 'naukri'")
    except sqlite3.OperationalError:
        pass  # Already exists

    # Table for tracking application workflow
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT UNIQUE,
            status TEXT DEFAULT 'DISCOVERED', -- 'DISCOVERED', 'TAILORED', 'APPROVED', 'APPLIED', 'SKIPPED', 'FAILED'
            ats_match_score INTEGER DEFAULT 0,
            missing_keywords TEXT,
            matched_keywords TEXT,
            tailored_resume_path TEXT,
            tailored_profile_json TEXT,
            notes TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES jobs (job_id)
        )
    """)

    conn.commit()
    conn.close()


def save_job(job_data: Dict[str, Any]) -> bool:
    """Save a discovered job and create an initial application record if not exists."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        platform = job_data.get("platform", "naukri")
        cursor.execute("""
            INSERT INTO jobs (
                job_id, platform, title, company, location, experience,
                salary_text, min_ctc_lpa, max_ctc_lpa,
                job_description, skills_required, apply_url,
                is_easy_apply
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                platform = excluded.platform,
                is_easy_apply = excluded.is_easy_apply,
                salary_text = excluded.salary_text,
                min_ctc_lpa = excluded.min_ctc_lpa,
                max_ctc_lpa = excluded.max_ctc_lpa
        """, (
            job_data["job_id"],
            platform,
            job_data.get("title", "Unknown"),
            job_data.get("company", "Unknown"),
            job_data.get("location", ""),
            job_data.get("experience", ""),
            job_data.get("salary_text", ""),
            job_data.get("min_ctc_lpa"),
            job_data.get("max_ctc_lpa"),
            job_data.get("job_description", ""),
            job_data.get("skills_required", ""),
            job_data.get("apply_url", ""),
            1 if job_data.get("is_easy_apply") else 0
        ))

        cursor.execute("""
            INSERT OR IGNORE INTO applications (job_id, status)
            VALUES (?, 'DISCOVERED')
        """, (job_data["job_id"],))

        is_new_discovery = (cursor.rowcount > 0)
        conn.commit()
        return is_new_discovery
    except Exception as e:
        print(f"Error saving job {job_data.get('job_id')}: {e}")
        return False
    finally:
        conn.close()


def set_job_easy_apply(job_id: str, is_easy: bool):
    """Updates the is_easy_apply flag for a job."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE jobs SET is_easy_apply = ? WHERE job_id = ?", (1 if is_easy else 0, job_id))
    conn.commit()
    conn.close()


def job_exists(job_id: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM jobs WHERE job_id = ?", (job_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None


def get_job_application_status(job_id: str) -> Optional[str]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM applications WHERE job_id = ?", (job_id,))
    row = cursor.fetchone()
    conn.close()
    return row["status"] if row else None


def update_application(
    job_id: str,
    status: Optional[str] = None,
    ats_score: Optional[int] = None,
    missing_keywords: Optional[str] = None,
    matched_keywords: Optional[str] = None,
    resume_path: Optional[str] = None,
    tailored_json: Optional[str] = None,
    notes: Optional[str] = None,
):
    conn = get_db_connection()
    cursor = conn.cursor()

    fields = []
    values = []

    if status:
        fields.append("status = ?")
        values.append(status)
    if ats_score is not None:
        fields.append("ats_match_score = ?")
        values.append(ats_score)
    if missing_keywords is not None:
        fields.append("missing_keywords = ?")
        values.append(missing_keywords)
    if matched_keywords is not None:
        fields.append("matched_keywords = ?")
        values.append(matched_keywords)
    if resume_path:
        fields.append("tailored_resume_path = ?")
        values.append(resume_path)
    if tailored_json:
        fields.append("tailored_profile_json = ?")
        values.append(tailored_json)
    if notes:
        fields.append("notes = ?")
        values.append(notes)

    fields.append("updated_at = ?")
    values.append(datetime.utcnow().isoformat())

    values.append(job_id)
    query = f"UPDATE applications SET {', '.join(fields)} WHERE job_id = ?"
    cursor.execute(query, values)
    conn.commit()
    conn.close()


def get_jobs_by_status(status: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT j.*, a.status, a.ats_match_score, a.tailored_resume_path, 
               a.missing_keywords, a.matched_keywords, a.notes
        FROM jobs j
        JOIN applications a ON j.job_id = a.job_id
        WHERE a.status = ?
        ORDER BY j.discovered_at DESC
    """, (status,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_pending_tailoring_jobs(easy_apply_only: bool = False, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    query = """
        SELECT j.*, a.status
        FROM jobs j
        JOIN applications a ON j.job_id = a.job_id
        WHERE a.status = 'DISCOVERED'
    """
    if easy_apply_only:
        query += " AND j.is_easy_apply = 1"
    query += " ORDER BY j.discovered_at DESC"
    if limit is not None and limit > 0:
        query += f" LIMIT {int(limit)}"
    cursor.execute(query)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_tailored_jobs_ready_for_review(easy_apply_only: bool = False, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    query = """
        SELECT j.*, a.status, a.ats_match_score, a.tailored_resume_path,
               a.missing_keywords, a.matched_keywords
        FROM jobs j
        JOIN applications a ON j.job_id = a.job_id
        WHERE a.status = 'TAILORED'
    """
    if easy_apply_only:
        query += " AND j.is_easy_apply = 1"
    query += " ORDER BY a.ats_match_score DESC"
    if limit is not None and limit > 0:
        query += f" LIMIT {int(limit)}"
    cursor.execute(query)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    verified = []
    for r in rows:
        p = r.get("tailored_resume_path")
        if p and Path(p).exists():
            verified.append(r)
        else:
            update_application(r["job_id"], status="DISCOVERED", resume_path=None)
    return verified



def get_summary_stats() -> Dict[str, int]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT status, COUNT(*) as cnt FROM applications GROUP BY status")
    counts = {r["status"]: r["cnt"] for r in cursor.fetchall()}
    cursor.execute("SELECT COUNT(*) as total FROM jobs")
    total = cursor.fetchone()["total"]
    conn.close()
    return {
        "total_jobs": total,
        "discovered": counts.get("DISCOVERED", 0),
        "tailored": counts.get("TAILORED", 0),
        "approved": counts.get("APPROVED", 0),
        "applied": counts.get("APPLIED", 0),
        "skipped": counts.get("SKIPPED", 0),
        "failed": counts.get("FAILED", 0),
    }
