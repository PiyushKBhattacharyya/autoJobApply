import os
import subprocess
import sys
from typing import Any, Dict
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Configure console with UTF-8 safe fallbacks for Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

console = Console()


def print_banner():
    banner = """
================================================================
          NAUKRI AI JOB HUNTER & RESUME CUSTOMIZER              
          ATS-Optimized | Role, City & CTC Tailored Bot         
================================================================
    """
    console.print(banner, style="bold cyan")



def display_stats(stats: Dict[str, int]):
    table = Table(title="Job Pipeline Status", show_header=True, header_style="bold magenta")
    table.add_column("Category", style="cyan", width=20)
    table.add_column("Count", style="bold green", justify="right")

    table.add_row("Total Discovered", str(stats.get("total_jobs", 0)))
    table.add_row("Pending Tailoring", str(stats.get("discovered", 0)))
    table.add_row("Tailored & Ready", str(stats.get("tailored", 0)))
    table.add_row("Applications Submitted", str(stats.get("applied", 0)))
    table.add_row("Skipped", str(stats.get("skipped", 0)))
    table.add_row("Failed / Redirects", str(stats.get("failed", 0)))

    console.print(table)


def copy_to_clipboard(text: str) -> bool:
    """Copies text to the system clipboard on Windows using PowerShell."""
    try:
        # Escape single quotes for PowerShell string literal
        escaped = text.replace("'", "''")
        cmd = f"Set-Clipboard -Value '{escaped}'"
        subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, check=False)
        return True
    except Exception:
        return False


def display_job_card(job: Dict[str, Any], ats_score: int, matched_kw: str, missing_kw: str, resume_path: str):
    score_color = "green" if ats_score >= 75 else ("yellow" if ats_score >= 60 else "red")
    is_easy = job.get("is_easy_apply", True)
    platform = (job.get("platform") or "naukri").capitalize()
    
    if is_easy:
        apply_type = f"[bold green]⚡ Direct Easy Apply ({platform})[/bold green]"
    else:
        apply_type = f"[bold yellow]🌐 Company Career Portal (External via {platform})[/bold yellow]"

    content = f"""
[bold white]Platform:[/bold white] [bold magenta]💼 {platform}[/bold magenta]
[bold white]Title:[/bold white] {job.get('title')}
[bold white]Company:[/bold white] {job.get('company')}
[bold white]Location:[/bold white] {job.get('location')}
[bold white]Experience:[/bold white] {job.get('experience')}
[bold white]Salary / CTC:[/bold white] [bold yellow]{job.get('salary_text')}[/bold yellow]
[bold white]Application Route:[/bold white] {apply_type}

[bold white]ATS Match Score:[/bold white] [{score_color} bold]{ats_score}%[/{score_color} bold]
[bold green]Matched Keywords:[/bold green] {matched_kw or 'None'}
[bold red]Missing Keywords:[/bold red] {missing_kw or 'None'}

[bold cyan]Tailored PDF:[/bold cyan] {resume_path}
[bold blue]Job URL:[/bold blue] {job.get('apply_url')}
    """.strip()

    console.print(Panel(content, title=f"Job Match: {job.get('company')}", border_style="cyan"))


def open_file_in_viewer(file_path: str):
    """Opens a file (e.g. PDF) in the default system viewer on Windows."""
    if os.path.exists(file_path):
        try:
            os.startfile(file_path)
        except Exception as e:
            console.print(f"[red]Could not open file: {e}[/red]")
    else:
        console.print(f"[red]File does not exist: {file_path}[/red]")

