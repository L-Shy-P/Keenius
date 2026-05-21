"""Configuration management for OpenTeacher.

Reads from .env file and config.yaml. API keys go in .env,
teaching preferences go in config.yaml.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
import yaml

CONFIG_DIR = Path.home() / ".openteacher"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
DATA_DIR = CONFIG_DIR / "data"
PROFILES_DIR = CONFIG_DIR / "profiles"


def ensure_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)


def load_env() -> None:
    """Load .env from project root and ~/.openteacher/.env."""
    project_env = Path.cwd() / ".env"
    if project_env.exists():
        load_dotenv(project_env)
    user_env = CONFIG_DIR / ".env"
    if user_env.exists():
        load_dotenv(user_env, override=True)


def load_config() -> dict:
    """Load config.yaml, returning defaults if it doesn't exist."""
    ensure_dirs()
    if CONFIG_FILE.exists():
        return yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
    return {}


def save_config(config: dict) -> None:
    ensure_dirs()
    CONFIG_FILE.write_text(yaml.dump(config, allow_unicode=True), encoding="utf-8")


DEFAULT_CONFIG = {
    "model": "gpt-4o",
    "api_base": "https://api.openai.com/v1",
    "language": "zh",
    "teaching_style": "socratic",
    "temperature": 0.7,
    "max_turns": 20,
    "context_limit": 8000,
}


def get_api_key() -> str:
    """Get API key from env. Checks OPENAI_API_KEY, then ANTHROPIC_API_KEY."""
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "API_KEY"):
        val = os.getenv(key)
        if val:
            return val
    return ""


def get_api_base() -> str:
    config = load_config()
    return config.get("api_base", DEFAULT_CONFIG["api_base"])


def get_model() -> str:
    config = load_config()
    return config.get("model", DEFAULT_CONFIG["model"])


def get_config_value(key: str, default=None):
    config = load_config()
    return config.get(key, DEFAULT_CONFIG.get(key, default))


def set_env(key: str, value: str) -> None:
    """Write a key=value pair to ~/.openteacher/.env, creating the file if needed."""
    ensure_dirs()
    env_file = CONFIG_DIR / ".env"

    lines = []
    if env_file.exists():
        lines = env_file.read_text(encoding="utf-8").splitlines()

    new_lines = []
    found = False
    for line in lines:
        if line.startswith(f"{key}=") or line.startswith(f"# {key}="):
            if not found:
                new_lines.append(f"{key}={value}")
                found = True
            # skip old duplicates
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"{key}={value}")

    env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.environ[key] = value


def set_config_value(key: str, value) -> None:
    """Write a single key: value to config.yaml, preserving existing keys."""
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)
