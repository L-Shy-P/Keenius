"""Learning plan data model, storage, and display."""

from __future__ import annotations
import json, datetime
from pathlib import Path
from openteacher.config import PLANS_DIR, PROFILES_DIR


def plan_path(subject: str) -> Path:
    safe = subject.strip().replace(" ", "-") or "general"
    return PLANS_DIR / f"{safe}.json"


def load_plan(subject: str) -> dict | None:
    p = plan_path(subject)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def save_plan(subject: str, plan: dict) -> None:
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    plan["updated_at"] = datetime.datetime.now().isoformat()
    plan_path(subject).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")


def create_plan(subject: str, profile: dict | None = None) -> dict:
    """Initialize a new empty plan."""
    return {
        "subject": subject,
        "created_at": datetime.datetime.now().isoformat(),
        "updated_at": "",
        "profile_snapshot": profile or {},
        "lessons": [],
        "status": "draft",  # draft → active → completed
    }


def add_lesson(subject: str, title: str) -> dict:
    plan = load_plan(subject) or create_plan(subject)
    lesson = {
        "id": len(plan["lessons"]) + 1,
        "title": title,
        "status": "pending",  # pending → in_progress → completed
        "sections": {
            "definition": {"original": "", "intuitive": ""},
            "examples": [],
            "quiz": [],
            "extension": "",
        },
        "student_questions": [],
        "profile_changes": {},  # C/S changes observed during this lesson
        "created_at": datetime.datetime.now().isoformat(),
        "completed_at": None,
    }
    plan["lessons"].append(lesson)
    plan["status"] = "active"
    save_plan(subject, plan)
    return lesson


def update_lesson(subject: str, lesson_id: int, updates: dict) -> dict | None:
    plan = load_plan(subject)
    if not plan:
        return None
    for lesson in plan["lessons"]:
        if lesson["id"] == lesson_id:
            lesson.update(updates)
            lesson["updated_at"] = datetime.datetime.now().isoformat()
            save_plan(subject, plan)
            return lesson
    return None


def mark_lesson_complete(subject: str, lesson_id: int, profile_changes: dict | None = None) -> dict | None:
    plan = load_plan(subject)
    if not plan:
        return None
    for lesson in plan["lessons"]:
        if lesson["id"] == lesson_id:
            lesson["status"] = "completed"
            lesson["completed_at"] = datetime.datetime.now().isoformat()
            if profile_changes:
                lesson["profile_changes"] = profile_changes
            # Check if all done
            if all(l["status"] == "completed" for l in plan["lessons"]):
                plan["status"] = "completed"
            save_plan(subject, plan)
            return lesson
    return None


def get_current_lesson(plan: dict) -> dict | None:
    for lesson in plan.get("lessons", []):
        if lesson["status"] in ("in_progress", "pending"):
            return lesson
    return None


def plan_summary(subject: str) -> str:
    """Render plan as a rich-styled text summary."""
    plan = load_plan(subject)
    if not plan or not plan.get("lessons"):
        return f"暂无 '{subject}' 的学习计划。"

    lines = [f"\n📋 [bold]学习计划: {subject}[/bold]\n"]
    status_icons = {"completed": "✅", "in_progress": "🔄", "pending": "⏳"}

    for lesson in plan["lessons"]:
        icon = status_icons.get(lesson["status"], "❓")
        title = lesson["title"]
        if lesson["status"] == "in_progress":
            title = f"[bold cyan]{title}[/bold cyan]"
        elif lesson["status"] == "completed":
            title = f"[dim]{title}[/dim]"
        lines.append(f"  {icon} {lesson['id']}. {title}")

    done = sum(1 for l in plan["lessons"] if l["status"] == "completed")
    total = len(plan["lessons"])
    lines.append(f"\n  进度: {done}/{total}")
    return "\n".join(lines)
