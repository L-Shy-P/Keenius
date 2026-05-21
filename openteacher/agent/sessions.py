"""Session manager with project-level and global storage, pin/auto-load support."""

from __future__ import annotations
import json, datetime
from pathlib import Path
from openteacher.config import DATA_DIR


def project_sessions_dir() -> Path:
    """The .openteacher/sessions/ directory in the current working directory."""
    return Path.cwd() / ".openteacher" / "sessions"


def global_sessions_dir() -> Path:
    """The global sessions directory in ~/.openteacher/data/sessions/."""
    return DATA_DIR / "sessions"


def _all_session_dirs() -> list[Path]:
    dirs = []
    for d in (project_sessions_dir(), global_sessions_dir()):
        if d.exists():
            dirs.append(d)
    return dirs


def scan_sessions() -> list[dict]:
    """Scan both project and global dirs for sessions, sorted by mtime desc."""
    sessions: list[dict] = []
    all_dirs = [project_sessions_dir(), global_sessions_dir()]
    for base_dir in all_dirs:
        if not base_dir.exists():
            continue
        for f in base_dir.glob("*.json"):
            if f.name in ("session_config.json",):
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                sessions.append({
                    "name": f.stem,
                    "filepath": str(f),
                    "source": "project" if str(project_sessions_dir()) in str(f) else "global",
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
    """Get pin/auto-load config for the current project directory."""
    config_file = project_sessions_dir() / "session_config.json"
    if config_file.exists():
        return json.loads(config_file.read_text(encoding="utf-8"))
    return {}


def save_pin_config(config: dict) -> None:
    project_sessions_dir().mkdir(parents=True, exist_ok=True)
    config_file = project_sessions_dir() / "session_config.json"
    config_file.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def set_pinned_session(session_name: str, source: str = "project") -> None:
    """Pin a session for auto-load on next launch in this directory."""
    config = get_pin_config()
    config["auto_load"] = session_name
    config["auto_load_source"] = source
    config["pinned"] = True
    save_pin_config(config)


def clear_pinned_session() -> None:
    config = get_pin_config()
    config.pop("auto_load", None)
    config.pop("auto_load_source", None)
    config["pinned"] = False
    save_pin_config(config)


def get_auto_load_session() -> tuple[str | None, str | None]:
    """Returns (session_name, source) if a session is pinned for auto-load."""
    config = get_pin_config()
    if config.get("pinned") and config.get("auto_load"):
        return config["auto_load"], config.get("auto_load_source", "project")
    return None, None


def load_session_by_name(name: str, source: str = "project") -> dict | None:
    """Load session data by name from the specified source dir."""
    base_dir = project_sessions_dir() if source == "project" else global_sessions_dir()
    filepath = base_dir / f"{name}.json"
    if not filepath.exists():
        return None
    return json.loads(filepath.read_text(encoding="utf-8"))
