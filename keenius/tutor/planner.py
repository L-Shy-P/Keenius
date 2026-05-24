"""文件夹嵌套式课程存储，使用 Markdown 课程文件。

目录结构 ~/.keenius/plans/<学科>/ ：

    python/
    ├── _meta.json              # 学科级元数据
    ├── test/                   # 学科级测试
    │   └── *.md
    ├── 01-基础概念/             # 章节
    │   ├── _meta.json
    │   ├── test/
    │   │   └── *.md
    │   ├── 01-变量与类型/       # 单元
    │   │   ├── _meta.json
    │   │   ├── test/
    │   │   │   └── *.md
    │   │   ├── 01-什么是变量.md  # 课程
    │   │   └── 02-数据类型.md
    │   └── 02-控制流/
    │       └── ...
    └── 02-进阶/
        └── ...

每个 .md 课程文件包含 YAML frontmatter 元数据和 markdown 正文。
"""

from __future__ import annotations
import json
import re
import datetime
from pathlib import Path
from keenius.config import PLANS_DIR, PROFILES_DIR

_YAML_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


# ═══════════════════════════════════════════════════════════════════════
# 路径辅助函数
# ═══════════════════════════════════════════════════════════════════════

def subject_dir(subject: str) -> Path:
    safe = subject.strip().replace(" ", "-") or "general"
    return PLANS_DIR / safe


def ensure_subject(subject: str) -> Path:
    d = subject_dir(subject)
    d.mkdir(parents=True, exist_ok=True)
    meta = d / "_meta.json"
    if not meta.exists():
        meta.write_text(json.dumps({
            "subject": subject, "status": "active",
            "created": datetime.datetime.now().isoformat(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "test").mkdir(exist_ok=True)
    return d


def list_subjects() -> list[str]:
    """列出所有已有学习计划的学科。"""
    if not PLANS_DIR.exists():
        return []
    return [d.name for d in PLANS_DIR.iterdir() if d.is_dir() and (d / "_meta.json").exists()]


# ═══════════════════════════════════════════════════════════════════════
# YAML frontmatter 辅助函数
# ═══════════════════════════════════════════════════════════════════════

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """从 markdown 文本中解析 --- YAML frontmatter ---。返回 (meta, body)。"""
    m = _YAML_RE.match(text)
    if m:
        try:
            meta = yaml_safe_load(m.group(1)) or {}
        except Exception:
            meta = {}
        body = text[m.end():].strip()
        return meta, body
    return {}, text


def _dump_frontmatter(meta: dict, body: str) -> str:
    """将 YAML frontmatter + 正文写入 markdown 字符串。"""
    fm = yaml_dump(meta)
    return f"---\n{fm}---\n\n{body}"


def yaml_safe_load(text: str) -> dict:
    try:
        import yaml
        return yaml.safe_load(text) or {}
    except Exception:
        # 最小化的手动 key: value 解析器
        result = {}
        for line in text.strip().split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                result[k.strip()] = v.strip().strip("\"'")
        return result


def yaml_dump(meta: dict) -> str:
    try:
        import yaml
        return yaml.dump(meta, allow_unicode=True, default_flow_style=False).strip()
    except Exception:
        return "\n".join(f"{k}: {v}" for k, v in meta.items())


# ═══════════════════════════════════════════════════════════════════════
# 元数据辅助函数
# ═══════════════════════════════════════════════════════════════════════

def _read_meta(folder: Path) -> dict:
    f = folder / "_meta.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {}


def _write_meta(folder: Path, meta: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════
# 课程 CRUD
# ═══════════════════════════════════════════════════════════════════════

def add_lesson(subject: str, section_title: str, unit_title: str,
               lesson_title: str, content: str = "") -> Path:
    """创建新的 .md 课程文件。返回文件路径。"""
    base = ensure_subject(subject)
    sec_dir = _find_or_create_child(base, section_title)
    unit_dir = _find_or_create_child(sec_dir, unit_title)
    unit_dir.mkdir(parents=True, exist_ok=True)
    (unit_dir / "test").mkdir(exist_ok=True)

    existing = sorted(unit_dir.glob("*.md"))
    num = len(existing) + 1
    fname = f"{num:02d}-{lesson_title[:40].replace('/', '-')}.md"
    fp = unit_dir / fname
    meta = {
        "id": num, "title": lesson_title,
        "status": "pending",
        "created": datetime.datetime.now().isoformat(),
    }
    if not content:
        content = f"# {lesson_title}\n\n## 定义原文\n\n## 直观解释\n\n## 方法典例\n\n## 当堂测试\n\n## 拓展内容\n"
    fp.write_text(_dump_frontmatter(meta, content), encoding="utf-8")
    return fp


def read_lesson(path: Path) -> tuple[dict, str]:
    """读取 .md 课程文件。返回 (frontmatter_meta, markdown_body)。"""
    return _parse_frontmatter(path.read_text(encoding="utf-8"))


def write_lesson(path: Path, meta: dict, body: str) -> None:
    """写入 .md 课程文件，更新 frontmatter 和正文。"""
    path.write_text(_dump_frontmatter(meta, body), encoding="utf-8")


def update_lesson_status(path: Path, status: str) -> None:
    """仅更新课程 frontmatter 中的状态。"""
    meta, body = read_lesson(path)
    meta["status"] = status
    if status == "completed":
        meta["completed_at"] = datetime.datetime.now().isoformat()
    write_lesson(path, meta, body)


def delete_lesson(path: Path) -> None:
    """删除课程文件。"""
    if path.exists():
        path.unlink()


# ═══════════════════════════════════════════════════════════════════════
# 目录导航
# ═══════════════════════════════════════════════════════════════════════

def _find_or_create_child(parent: Path, title: str) -> Path:
    """按 _meta.json title 查找已有编号子文件夹，不存在则创建新文件夹。"""
    for child in sorted(parent.iterdir()):
        if child.is_dir() and (child / "_meta.json").exists():
            m = _read_meta(child)
            if m.get("title") == title:
                return child
    # 创建新文件夹
    existing = [d for d in parent.iterdir() if d.is_dir() and (d / "_meta.json").exists()]
    num = len(existing) + 1
    fname = f"{num:02d}-{title[:30].replace('/', '-')}"
    child = parent / fname
    child.mkdir(parents=True, exist_ok=True)
    (child / "test").mkdir(exist_ok=True)
    _write_meta(child, {"title": title, "created": datetime.datetime.now().isoformat()})
    return child


def scan_tree(subject: str) -> list[dict]:
    """扫描文件夹树并返回层级结构。

    返回包含嵌套单元和课程的章节字典列表。
    每个节点：{title, type, path, status?, children?}
    """
    base = subject_dir(subject)
    if not base.exists():
        return []

    tree = []
    # 元数据
    meta = _read_meta(base)
    # 遍历章节
    for sec_path in sorted(base.iterdir()):
        if not sec_path.is_dir() or sec_path.name == "test" or sec_path.name.startswith("_"):
            continue
        sec_meta = _read_meta(sec_path)
        snode = {
            "title": sec_meta.get("title", sec_path.name),
            "type": "section", "path": str(sec_path), "children": []
        }
        for unit_path in sorted(sec_path.iterdir()):
            if not unit_path.is_dir() or unit_path.name == "test" or unit_path.name.startswith("_"):
                continue
            unit_meta = _read_meta(unit_path)
            unode = {
                "title": unit_meta.get("title", unit_path.name),
                "type": "unit", "path": str(unit_path), "children": []
            }
            # 课程是 .md 文件
            for les_path in sorted(unit_path.glob("*.md")):
                les_meta, _body = read_lesson(les_path)
                status = les_meta.get("status", "pending")
                icon = {"completed": "✅", "in_progress": "🔄", "pending": "⏳", "skipped": "⏭️"}.get(status, "⏳")
                unode["children"].append({
                    "title": les_meta.get("title", les_path.stem),
                    "type": "lesson", "path": str(les_path),
                    "status": status, "icon": icon,
                    "id": les_meta.get("id", 0),
                    "children": _lesson_content_nodes(les_meta, _body),
                })
            # 同时检查测试文件夹内容
            test_dir = unit_path / "test"
            if test_dir.exists():
                for test_file in sorted(test_dir.glob("*.md")):
                    unode["children"].append({
                        "title": f"🧪 {test_file.stem}", "type": "test",
                        "path": str(test_file), "status": "pending", "icon": "🧪",
                        "children": [],
                    })
            snode["children"].append(unode)

        # 章节测试文件夹
        test_dir = sec_path / "test"
        if test_dir.exists():
            for test_file in sorted(test_dir.glob("*.md")):
                snode["children"].append({
                    "title": f"🧪 {test_file.stem}", "type": "test",
                    "path": str(test_file), "status": "pending", "icon": "🧪",
                    "children": [],
                })
        tree.append(snode)

    # 学科级测试
    test_dir = base / "test"
    if test_dir.exists():
        for test_file in sorted(test_dir.glob("*.md")):
            tree.append({
                "title": f"🧪 {test_file.stem}", "type": "test",
                "path": str(test_file), "status": "pending", "icon": "🧪",
                "children": [],
            })

    return tree


def _lesson_content_nodes(meta: dict, body: str) -> list[dict]:
    """从课程正文中提取标题作为内容子节点。"""
    children = []
    # 解析 ## 标题
    for m in re.finditer(r"^## (.+)$", body, re.MULTILINE):
        heading = m.group(1).strip()
        # 获取该标题下内容的预览
        start = m.end()
        next_heading = re.search(r"^## ", body[start:], re.MULTILINE)
        end = start + next_heading.start() if next_heading else len(body)
        preview = body[start:end].strip()[:60].replace("\n", " ")
        children.append({
            "title": f"{heading}: {preview}",
            "type": "content", "data": preview, "children": [],
        })
    return children


# ═══════════════════════════════════════════════════════════════════════
# 旧版兼容
# ═══════════════════════════════════════════════════════════════════════

def load_plan(subject: str) -> dict | None:
    """旧版：返回树形字典以保持向后兼容。推荐使用 scan_tree()。"""
    tree = scan_tree(subject)
    if not tree:
        return None
    return {
        "subject": subject,
        "sections": tree,
        "status": _read_meta(subject_dir(subject)).get("status", "active"),
    }


def save_plan(subject: str, plan: dict) -> None:
    """旧版存根 — 文件夹写入通过 add_lesson / write_lesson / delete_lesson 完成。"""
    ensure_subject(subject)


def create_plan(subject: str, profile: dict | None = None) -> dict:
    ensure_subject(subject)
    return {"subject": subject, "sections": [], "status": "active"}


def mark_lesson_complete(subject: str, lesson_id: int, profile_changes: dict | None = None) -> dict | None:
    """按 ID 标记课程完成（搜索树）。"""
    base = subject_dir(subject)
    for md_file in base.rglob("*.md"):
        if md_file.parent.name == "test":
            continue
        meta, body = read_lesson(md_file)
        if meta.get("id") == lesson_id:
            update_lesson_status(md_file, "completed")
            return meta
    return None


def get_current_lesson(plan: dict) -> dict | None:
    """查找第一个进行中或待处理的课程。"""
    for sec in plan.get("sections", []):
        for unit in sec.get("children", []):
            for les in unit.get("children", []):
                if les.get("type") == "lesson" and les.get("status") in ("in_progress", "pending"):
                    return les
    return None


def plan_summary(subject: str) -> str:
    """渲染学习计划的简单文本摘要。"""
    tree = scan_tree(subject)
    if not tree:
        return f"暂无 '{subject}' 的学习计划。"

    lines = [f"\n📋 学习计划: {subject}\n"]
    done = 0
    total = 0
    for sec in tree:
        lines.append(f"  📁 {sec['title']}")
        for unit in sec.get("children", []):
            if unit.get("type") == "test":
                lines.append(f"    🧪 {unit['title']}")
                continue
            lines.append(f"    📂 {unit['title']}")
            for les in unit.get("children", []):
                if les.get("type") == "test":
                    lines.append(f"      🧪 {les['title']}")
                    continue
                icon = les.get("icon", "⏳")
                title = les.get("title", "")
                total += 1
                if les.get("status") == "completed":
                    done += 1
                    title = f"[dim]{title}[/dim]"
                elif les.get("status") == "in_progress":
                    title = f"[bold cyan]{title}[/bold cyan]"
                lines.append(f"      {icon} {title}")
    lines.append(f"\n  进度: {done}/{total}")
    return "\n".join(lines)


def update_lesson(subject: str, lesson_id: int, updates: dict) -> dict | None:
    """按 ID 更新课程元数据。"""
    base = subject_dir(subject)
    for md_file in base.rglob("*.md"):
        if md_file.parent.name == "test":
            continue
        meta, body = read_lesson(md_file)
        if meta.get("id") == lesson_id:
            meta.update(updates)
            meta["updated_at"] = datetime.datetime.now().isoformat()
            write_lesson(md_file, meta, body)
            return meta
    return None
