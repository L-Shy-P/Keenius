"""Keenius 配置管理。

从 .env 文件和 config.yaml 读取配置。API 密钥放在 .env 中，
教学偏好放在 config.yaml 中。
"""

import os
from pathlib import Path
from dotenv import load_dotenv
import yaml

CONFIG_DIR = Path.home() / ".keenius"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
SESSIONS_DIR = CONFIG_DIR / "sessions"
PLANS_DIR = CONFIG_DIR / "plans"
SKILLS_DIR = CONFIG_DIR / "skills"
PROFILES_DIR = CONFIG_DIR / "profiles"
HISTORY_FILE = CONFIG_DIR / "history.txt"
NOTES_DIR = CONFIG_DIR / "notes"
PROGRESS_FILE = CONFIG_DIR / "progress.json"


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, SESSIONS_DIR, PLANS_DIR, SKILLS_DIR, PROFILES_DIR, NOTES_DIR):
        d.mkdir(parents=True, exist_ok=True)


def load_env() -> None:
    """从项目根目录和 ~/.keenius/.env 加载 .env 文件。"""
    project_env = Path.cwd() / ".env"
    if project_env.exists():
        load_dotenv(project_env)
    user_env = CONFIG_DIR / ".env"
    if user_env.exists():
        load_dotenv(user_env, override=True)


def load_config() -> dict:
    """加载 config.yaml，如果不存在则返回默认值。"""
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
    """从环境变量获取 API 密钥。依次检查 OPENAI_API_KEY、ANTHROPIC_API_KEY。"""
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
    """将 key=value 键值对写入 ~/.keenius/.env，如文件不存在则创建。"""
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
            # 跳过旧的重复行
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"{key}={value}")

    env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.environ[key] = value


def set_config_value(key: str, value) -> None:
    """将单个 key: value 写入 config.yaml，保留已有配置项。"""
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)
