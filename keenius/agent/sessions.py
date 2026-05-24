"""会话管理器 — 全局存储。可通过配置固定 / 自动加载。"""

from __future__ import annotations
import json
from pathlib import Path
from keenius.config import SESSIONS_DIR, CONFIG_DIR


def sessions_dir() -> Path:
    return SESSIONS_DIR


def scan_sessions() -> list[dict]:
    """扫描全局会话目录，按修改时间降序排列。"""
    sessions: list[dict] = []
    if not SESSIONS_DIR.exists():
        return sessions
    for f in SESSIONS_DIR.glob("*.json"):
        if f.name == "session_config.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            sessions.append({
                "name": f.stem,
                "filepath": str(f),
                "source": "global",
                "subject": data.get("subject", ""),
                "model": data.get("model", ""),
                "messages": len(data.get("messages", [])),
                "turn_count": data.get("turn_count", 0),
                "phase": data.get("phase", ""),
                "created_at": data.get("created_at", "")[:16],
                "saved_at": data.get("saved_at", "")[:16],
                "mtime": f.stat().st_mtime,
            })
        except (json.JSONDecodeError, KeyError):
            continue
    sessions.sort(key=lambda s: s["mtime"], reverse=True)
    return sessions


def get_pin_config() -> dict:
    config_file = CONFIG_DIR / "session_config.json"
    if config_file.exists():
        return json.loads(config_file.read_text(encoding="utf-8"))
    return {}


def save_pin_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (CONFIG_DIR / "session_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def set_pinned_session(session_name: str, _source: str = "") -> None:
    config = get_pin_config()
    config["auto_load"] = session_name
    config["pinned"] = True
    save_pin_config(config)


def clear_pinned_session() -> None:
    config = get_pin_config()
    config.pop("auto_load", None)
    config["pinned"] = False
    save_pin_config(config)


def get_auto_load_session() -> tuple[str | None, str | None]:
    config = get_pin_config()
    if config.get("pinned") and config.get("auto_load"):
        return config["auto_load"], "global"
    return None, None


def load_session_by_name(name: str, _source: str = "") -> dict | None:
    filepath = SESSIONS_DIR / f"{name}.json"
    if not filepath.exists():
        return None
    return json.loads(filepath.read_text(encoding="utf-8"))
