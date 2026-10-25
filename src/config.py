import os
from pathlib import Path
from typing import List, Optional
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load .env file
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


class SearchConfig(BaseModel):
    role: str = "Full Stack Developer"
    city: str = "Bengaluru"
    min_ctc_lpa: float = 12.0
    max_ctc_lpa: float = 30.0
    experience_years: int = 3
    max_results: int = 25


class ResumeConfig(BaseModel):
    master_pdf_path: str = "data/master_resume.pdf"
    master_profile_path: str = "data/master_profile.json"
    output_dir: str = "output/resumes"

    @property
    def master_pdf_abs(self) -> Path:
        return BASE_DIR / self.master_pdf_path

    @property
    def master_profile_abs(self) -> Path:
        return BASE_DIR / self.master_profile_path

    @property
    def output_dir_abs(self) -> Path:
        p = BASE_DIR / self.output_dir
        p.mkdir(parents=True, exist_ok=True)
        return p


class BotConfig(BaseModel):
    mode: str = "supervised"  # "supervised" or "auto"
    min_match_score: int = 65
    headless: bool = False
    human_delay_range: List[float] = [2.5, 6.0]
    auto_easy_apply: bool = True
    browser_context_dir: str = ".browser_context"

    @property
    def browser_context_abs(self) -> Path:
        p = BASE_DIR / self.browser_context_dir
        p.mkdir(parents=True, exist_ok=True)
        return p


class GeminiConfig(BaseModel):
    model_name: str = "gemini-3.8-flash"
    api_key: Optional[str] = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))



class AppConfig(BaseModel):
    search: SearchConfig = Field(default_factory=SearchConfig)
    resume: ResumeConfig = Field(default_factory=ResumeConfig)
    bot: BotConfig = Field(default_factory=BotConfig)
    gemini: GeminiConfig = Field(default_factory=GeminiConfig)


def load_config(config_path: Optional[str] = None) -> AppConfig:
    path = Path(config_path) if config_path else BASE_DIR / "config.yaml"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            return AppConfig(**data)
    return AppConfig()
