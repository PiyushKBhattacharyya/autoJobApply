from typing import List, Optional
import yaml
from google import genai
from rich.table import Table

from src.config import BASE_DIR, load_config
from src.ui import console


def list_available_models(api_key: Optional[str] = None) -> List[str]:
    """
    Dynamically queries Google Gemini API and returns all active models
    supporting generateContent.
    """
    config = load_config()
    key = api_key or config.gemini.api_key
    if not key:
        raise ValueError("GEMINI_API_KEY is not set. Please set it in .env first.")

    client = genai.Client(api_key=key)
    supported_models = []

    try:
        for m in client.models.list():
            actions = getattr(m, "supported_actions", []) or getattr(m, "supported_generation_methods", [])
            # Filter for content generation models (exclude embedding/audio-only where not applicable)
            if "generateContent" in actions:
                name = m.name.replace("models/", "")
                # Exclude purely specialized models like tts, robotics, live audio unless general
                if not any(k in name for k in ["-tts", "robotics", "native-audio"]):
                    supported_models.append(name)
    except Exception as e:
        console.print(f"[red]Error fetching models from Gemini API: {e}[/red]")
        return ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash", "gemini-flash-latest"]

    return supported_models


def display_models_table(models: List[str], current_model: str):
    """Displays a clean table of available models in the terminal."""
    table = Table(title="Available Google Gemini Models", show_header=True, header_style="bold magenta")
    table.add_column("No.", style="cyan", width=5, justify="right")
    table.add_column("Model Name", style="bold white", width=35)
    table.add_column("Status", style="green", width=15)

    for idx, model in enumerate(models, 1):
        status = "[bold green]ACTIVE (Current)[/bold green]" if model == current_model else "Available"
        table.add_row(str(idx), model, status)

    console.print(table)


def set_active_model_in_config(new_model: str):
    """Updates the model_name field in config.yaml."""
    config_file = BASE_DIR / "config.yaml"
    if not config_file.exists():
        console.print(f"[red]config.yaml not found at {config_file}[/red]")
        return

    with open(config_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if "gemini" not in data:
        data["gemini"] = {}

    data["gemini"]["model_name"] = new_model

    with open(config_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

    console.print(f"[bold green]✓ Updated active model to '{new_model}' in config.yaml[/bold green]")
