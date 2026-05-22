"""Interactive REPL shell using prompt-toolkit.

This is the main user interface — a rich terminal chat with the AI teacher.
"""

from __future__ import annotations
from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style
from prompt_toolkit.history import FileHistory
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.document import Document

from openteacher.agent.display import (
    console,
    print_logo,
    print_welcome,
    print_assistant_header,
    print_markdown,
    print_error,
    print_info,
    print_success,
)
from openteacher.agent.loop import ConversationLoop
from openteacher.config import DATA_DIR

# ── Toolbar helpers: strip Rich markup for prompt_toolkit (plain text only) ─

def _plain(text: str) -> str:
    """Strip Rich markup tags for prompt_toolkit bottom toolbar."""
    import re
    return re.sub(r"\[/?\w+\]|\[/?\w+ [^\]]*\]", "", text)

# ── Slash command registry ────────────────────────────────────────────

SLASH_COMMANDS: dict[str, dict] = {
    "session": {
        "/new":     ("开始新对话（重置上下文）", lambda ctx: ctx.get("loop").reset() or "对话已重置。输入问题开始吧！"),
        "/save":    ("保存当前会话 /save [名称]", lambda ctx, a: _cmd_save(ctx, a), True),
        "/load":    ("加载历史会话 /load <名称>", lambda ctx, a: _cmd_load(ctx, a), True),
        "/sessions": ("列出所有已保存的会话", lambda ctx: _cmd_list_sessions()),
        "/picker":   ("重新打开会话选择界面", lambda ctx: _cmd_reopen_picker(ctx)),
        "/subject": ("切换学习主题 /subject <主题>", lambda ctx, a: setattr(ctx["loop"], "subject", a) or f"主题已切换为: {a}", True),
        "/mode":    ("切换教学模式 /mode <guided|direct|mixed>", lambda ctx, a: _cmd_mode(ctx, a), True),
        "/style":   ("切换教学风格 /style <socratic|direct|coaching>", lambda ctx, a: setattr(ctx["loop"], "teaching_style", a) or f"教学风格已切换为: {a}", True),
    },
    "config": {
        "/setup":    ("配置 API Key 和模型", lambda _: run_setup_wizard()),
        "/config":   ("查看当前配置", lambda _: show_config()),
        "/plan":     ("查看学习计划", lambda _: show_plan()),
        "/profile":  ("查看学生画像评估", lambda _: show_profile()),
        "/progress": ("查看学习进度", lambda _: show_progress()),
    },
    "help": {
        "/help": ("显示帮助信息", lambda _: show_help()),
        "/quit": ("退出 OpenTeacher", lambda _: "EXIT"),
        "/q":    ("退出（别名）", lambda _: "EXIT"),
    },
}

_all_flat: dict[str, dict] = {}
for _cmds in SLASH_COMMANDS.values():
    _all_flat.update(_cmds)


# ── Completer for slash commands ──────────────────────────────────────

class SlashCompleter(Completer):
    def get_completions(self, document: Document, complete_event):
        text = document.text_before_cursor.lstrip()
        if not text.startswith("/"):
            return

        # Completing command name
        if " " not in text:
            partial = text
            for cmd, (desc, *_rest) in _all_flat.items():
                if cmd.startswith(partial):
                    yield Completion(cmd, start_position=-len(partial), display_meta=desc)
        # Completing subcommand args
        else:
            parts = text.split(" ", 1)
            cmd_name = parts[0]
            arg_part = parts[1] if len(parts) > 1 else ""

            if cmd_name == "/subject":
                suggestions = ["python", "机器学习", "线性代数", "深度学习", "C++", "JavaScript"]
            elif cmd_name == "/style":
                suggestions = ["socratic", "direct", "coaching"]
            else:
                return

            for s in suggestions:
                if s.startswith(arg_part.lower()) or not arg_part:
                    yield Completion(s, start_position=-len(arg_part))


# ── Key bindings for REPL ─────────────────────────────────────────────

repl_bindings = KeyBindings()


@repl_bindings.add("c-d")
def _(event):
    event.app.exit(result="EXIT")


@repl_bindings.add("c-c")
def _(event):
    event.app.exit(result="INTERRUPT")


@repl_bindings.add("escape", "enter")
def _(event):
    """Alt+Enter / Ctrl+Enter for newline."""
    event.app.current_buffer.insert_text("\n")


# ── Standard picker key bindings (Tab=cycle, Up/Down=select, Enter=confirm) ─

def _picker_kb(idx_ref: list, count: int, on_select, on_cancel=None):
    """Build standard key bindings for a list picker.
    idx_ref: mutable list [current_index]
    count: total items
    on_select: callable, receives index
    on_cancel: callable or None
    """
    kb = KeyBindings()

    @kb.add("up")
    def _(event): idx_ref[0] = (idx_ref[0] - 1) % count

    @kb.add("down")
    def _(event): idx_ref[0] = (idx_ref[0] + 1) % count

    @kb.add("tab")
    def _(event): idx_ref[0] = (idx_ref[0] + 1) % count

    @kb.add("s-tab")
    def _(event): idx_ref[0] = (idx_ref[0] - 1) % count

    @kb.add("enter")
    def _(event): on_select(idx_ref[0])

    @kb.add("escape")
    def _(event):
        if on_cancel:
            on_cancel()
        event.app.exit(result=None)

    @kb.add("c-c")
    def _(event): event.app.exit(result=None)

    return kb


# ── Error handling ────────────────────────────────────────────────────

def _handle_startup_error(err: Exception) -> None:
    msg = str(err)
    from openteacher.config import get_api_key

    if not get_api_key():
        print_error("未配置 API Key，无法连接 AI 导师。")
        console.print()
        console.print("[bold yellow]请输入 [bold]/setup[/bold] 配置 API 连接[/bold yellow]")
        console.print()
        return

    if "401" in msg or "Incorrect API key" in msg or "invalid_api_key" in msg:
        print_error("API Key 无效或过期。")
        console.print()
        console.print("[bold yellow]请输入 [bold]/setup[/bold] 重新配置[/bold yellow]")
        console.print()
        return

    if "Connection" in msg or "connect" in msg.lower() or "timed out" in msg.lower():
        print_error(f"网络连接失败。请检查网络和 API Base URL。\n   {msg}")
        return

    print_error(f"启动失败: {msg}")


# ── Setup wizard ──────────────────────────────────────────────────────

def run_setup_wizard() -> str:
    from openteacher import config
    from openteacher.agent.display import (
        print_setup_banner, provider_selector, print_success, print_error as display_error,
    )
    from prompt_toolkit import prompt

    existing_key = config.get_api_key()
    if existing_key:
        console.print(f"[dim]检测到已配置 API Key[/dim]")
        if prompt("是否重新配置？[y/N] ").strip().lower() not in ("y", "yes"):
            return "保持现有配置。"

    print_setup_banner()
    provider_selector()

    # Keyboard-driven provider selection
    providers = [
        ("1", "OpenAI", "OPENAI_API_KEY", "https://api.openai.com/v1", "gpt-4o"),
        ("2", "DeepSeek", "DEEPSEEK_API_KEY", "https://api.deepseek.com/v1", "deepseek-chat"),
        ("3", "Anthropic", "ANTHROPIC_API_KEY", "https://api.anthropic.com/v1", "claude-sonnet-4-6"),
        ("4", "自定义", "API_KEY", "", ""),
    ]
    provider_opts = [{"num": p[0], "text": f"{p[1]} ({p[3]})"} for p in providers]
    choice_idx = _pick_provider_interactive(provider_opts)
    if choice_idx is None:
        return "配置取消。"
    _, name, env_key, default_base, default_model = providers[choice_idx]

    console.print(f"[dim]已选择: {name}[/dim]")
    console.print()
    api_key = prompt("API Key (输入会隐藏): ", is_password=True).strip()
    if not api_key:
        display_error("API Key 不能为空，配置取消。")
        return "配置取消。"

    console.print()
    if choice_idx == 3:  # custom
        base_url = prompt("Base URL: ").strip()
        if not base_url:
            display_error("Base URL 不能为空，配置取消。")
            return "配置取消。"
    else:
        base_url = prompt(f"API Base URL (默认: {default_base}): ").strip() or default_base

    model = prompt(f"模型名称 (默认: {default_model}): ").strip() or default_model

    config.set_env(env_key, api_key)
    config.set_config_value("api_base", base_url)
    config.set_config_value("model", model)

    print_success(f"配置完成！已保存至 {config.CONFIG_DIR / '.env'}")
    console.print(f"  [dim]{env_key} | {base_url} | {model}[/dim]")
    return ""


def _pick_provider_interactive(options: list) -> int | None:
    """Keyboard-driven provider selection."""
    kb = _picker_kb(
        idx_ref := [0], len(options),
        on_select=lambda i: None,  # handled below
    )
    # Override enter to return index
    kb = KeyBindings()
    idx = [0]

    @kb.add("up")
    def _(event): idx[0] = (idx[0] - 1) % len(options)
    @kb.add("down")
    def _(event): idx[0] = (idx[0] + 1) % len(options)

    @kb.add("tab")
    def _(event): idx[0] = (idx[0] + 1) % len(options)

    @kb.add("s-tab")
    def _(event): idx[0] = (idx[0] - 1) % len(options)
    @kb.add("tab")
    def _(event): idx[0] = (idx[0] + 1) % len(options)
    @kb.add("s-tab")
    def _(event): idx[0] = (idx[0] - 1) % len(options)
    @kb.add("enter")
    def _(event): event.app.exit(result=idx[0])
    @kb.add("escape")
    def _(event): event.app.exit(result=None)
    @kb.add("c-c")
    def _(event): event.app.exit(result=None)

    def _toolbar():
        lines = []
        for i, opt in enumerate(options):
            marker = "▶" if i == idx[0] else " "
            lines.append(f"{marker} [{opt['num']}] {opt['text']}")
        lines.append("↑↓/Tab 选择  Enter 确认  Esc 取消")
        return "  ".join(lines)

    from prompt_toolkit import PromptSession as PS
    ps = PS(key_bindings=kb, bottom_toolbar=_toolbar, style=CHAT_STYLE)
    try:
        return ps.prompt("")
    except (EOFError, KeyboardInterrupt):
        return None


# ── Show config ───────────────────────────────────────────────────────

def show_config() -> str:
    from openteacher import config
    cfg = config.load_config()
    has_key = bool(config.get_api_key())
    return (
        f"\n📋 当前配置\n"
        f"  Model:       [cyan]{cfg.get('model', '未设置')}[/cyan]\n"
        f"  API Base:    [dim]{cfg.get('api_base', '未设置')}[/dim]\n"
        f"  API Key:     {'[green]已配置[/green]' if has_key else '[red]未配置[/red]'}\n"
        f"  教学语言:    {cfg.get('language', 'zh')}\n"
        f"  教学风格:    {cfg.get('teaching_style', 'socratic')}"
    )


def show_profile() -> str:
    import json
    from openteacher.config import PROFILES_DIR

    pf = PROFILES_DIR / "default.json"
    if not pf.exists():
        return "暂无学生画像数据。使用过程中 Agent 会自动构建。"
    data = json.loads(pf.read_text(encoding="utf-8"))

    lines = ["\n🎯 [bold]学生画像[/bold]\n"]

    orient = data.get("learning_orientation", "")
    if orient:
        labels = {
            "theory_focused": "理论导向", "practice_focused": "实践导向",
            "exam_focused": "应试导向", "curiosity_driven": "兴趣驱动",
            "project_driven": "项目驱动",
        }
        lines.append(f"  学习倾向: {labels.get(orient, orient)}")

    summary = data.get("overall_summary", "")
    if summary:
        lines.append(f"  总体评估: {summary}")

    # Concept levels
    concept_levels = data.get("concept_levels", {})
    if concept_levels:
        lines.append("\n  [bold]📚 概念掌握度 (C 轴)[/bold]")
        for name, info in sorted(concept_levels.items()):
            ev = f" — {info.get('evidence', '')}" if info.get("evidence") else ""
            lines.append(f"    {info['level']}  {name}{ev}")

    # Skill levels
    skill_levels = data.get("skill_levels", {})
    if skill_levels:
        lines.append("\n  [bold]🛠️ 应用/执行能力 (S 轴)[/bold]")
        for name, info in sorted(skill_levels.items()):
            ev = f" — {info.get('evidence', '')}" if info.get("evidence") else ""
            lines.append(f"    {info['level']}  {name}{ev}")

    if not concept_levels and not skill_levels:
        lines.append("  [dim]尚未评估具体知识维度[/dim]")

    # Cognitive / personality traits
    cognitive_fields = {
        "memory_style": "🧠 记忆模式",
        "cognitive_strength": "💡 认知优势",
        "grasp_speed": "⚡ 理解速度",
        "discipline": "🎯 自律程度",
    }
    for field, label in cognitive_fields.items():
        if data.get(field):
            lines.append(f"  {label}: {data[field]}")

    # Notes
    notes = data.get("cognitive_notes", {})
    if notes:
        for field, info in notes.items():
            if info.get("evidence"):
                lines.append(f"    [dim]依据: {info['evidence']}[/dim]")

    lines.append(f"\n[dim]数据文件: {pf}[/dim]")
    return "\n".join(lines)


def show_plan() -> str:
    from openteacher.config import PLANS_DIR
    import json
    files = list(PLANS_DIR.glob("*.json"))
    if not files:
        return "暂无学习计划。开始学习后 Agent 会自动创建。"
    # Show most recent plan
    latest = max(files, key=lambda p: p.stat().st_mtime)
    plan = json.loads(latest.read_text(encoding="utf-8"))
    from openteacher.tutor.planner import plan_summary
    return plan_summary(plan["subject"])


def show_progress() -> str:
    import json
    progress_file = DATA_DIR / "progress.json"
    if not progress_file.exists():
        return "暂无学习进度记录。输入内容开始学习吧！"
    data = json.loads(progress_file.read_text(encoding="utf-8"))
    if not data:
        return "暂无学习进度记录。"
    lines = ["\n📊 学习进度\n"]
    for item in data:
        emoji = {"mastered": "✅", "in_progress": "🔄", "needs_review": "📌"}.get(item.get("status", ""), "📎")
        lines.append(f"  {emoji} [cyan]{item['concept']}[/cyan]: {item['status']}")
        if item.get("notes"):
            lines.append(f"     [dim]{item['notes']}[/dim]")
    return "\n".join(lines)


# ── Session commands ──────────────────────────────────────────────────

def _cmd_save(ctx: dict, args: str) -> str:
    loop = ctx["loop"]
    name = args.strip() if args.strip() else ""
    saved_name = loop.save(name if name else None)
    return f"✓ 会话已保存为 [cyan]{saved_name}[/cyan]"


def _cmd_load(ctx: dict, args: str) -> str:
    name = args.strip()
    if name:
        # Direct load by name
        loop = ctx["loop"]
        if loop.load(name):
            loop.subject = loop.subject or ""
            return f"✓ 已加载会话 [cyan]{name}[/cyan]\n  {loop.turn_count} 轮对话, {len(loop.messages)} 条消息\n\n输入内容继续对话。"
        return f"未找到会话: {name}\n输入 /sessions 查看可用的会话列表。"

    # No name given — show interactive picker
    sessions = ConversationLoop.list_sessions()
    if not sessions:
        return "暂无保存的会话。"
    from openteacher.agent.sessions import load_session_by_name
    options = []
    for s in sessions:
        options.append({
            "num": len(options) + 1,
            "text": f"{s['name']:20s}  📚 {s['subject'] or '(无)':16s}  💬 {s['messages']}条  {s['saved_at']}",
            "session": s,
        })
    options.append({"num": len(options) + 1, "text": "取消"})
    choice_idx = _pick_from_list(options, "📂 加载会话 — ↑↓ 选择  Enter 加载  Esc 取消")
    if choice_idx is None or choice_idx >= len(sessions):
        return "已取消。"
    s = sessions[choice_idx]
    data = load_session_by_name(s["name"], s["source"])
    if data is None:
        return "加载失败。"
    loop = ctx["loop"]
    loop.__dict__.update(ConversationLoop.from_dict(data).__dict__)
    return f"✓ 已加载会话 [cyan]{s['name']}[/cyan]\n  输入内容继续对话。"


def _cmd_mode(ctx: dict, args: str) -> str:
    mode = args.strip()
    if mode not in ("guided", "direct", "mixed"):
        return "模式需为 guided（引导式）/ direct（讲解式）/ mixed（混合式）"
    ctx["loop"].mode = mode
    names = {"guided": "引导式 — 提问让你推导", "direct": "讲解式 — 直接告诉你", "mixed": "混合式 — 先讲再确认"}
    return f"教学模式: {names[mode]}"


def _cmd_reopen_picker(ctx: dict) -> str:
    """Reopen the session picker from within the REPL. Returns EXIT to trigger restart."""
    from openteacher.agent.sessions import scan_sessions, get_auto_load_session, load_session_by_name
    sessions = scan_sessions()
    if not sessions:
        return "暂无已保存的会话。"
    choice = session_picker(sessions)
    if choice == "NEW":
        ctx["loop"].reset()
        return "已创建新会话。输入问题开始吧！"
    elif choice is None:
        return "已取消。"
    else:
        data = load_session_by_name(choice["name"], choice["source"])
        if data:
            ctx["loop"].__dict__.update(ConversationLoop.from_dict(data).__dict__)
            return f"已加载会话: {choice['name']}"
        return "加载失败。"


def _cmd_list_sessions() -> str:
    sessions = ConversationLoop.list_sessions()
    if not sessions:
        return "暂无保存的会话。输入 /save 保存当前会话。"

    from openteacher.agent.sessions import load_session_by_name

    # Build options for keyboard picker
    options = []
    for s in sessions:
        options.append({
            "num": len(options) + 1,
            "text": f"{s['name']:20s}  📚 {s['subject'] or '(无)':16s}  💬 {s['messages']}条  {s['saved_at']}",
            "session": s,
        })
    options.append({"num": len(options) + 1, "text": "取消"})

    choice_idx = _pick_from_list(options, "📂 已保存的会话 — ↑↓ 选择  Enter 加载  Esc 取消")
    if choice_idx is None or choice_idx >= len(sessions):
        return "已取消。"

    s = sessions[choice_idx]
    data = load_session_by_name(s["name"], s["source"])
    if data:
        return f"✓ 已加载会话: {s['name']}\n  输入内容继续对话。"
    return "加载失败。"


def _pick_from_list(options: list, title: str = "") -> int | None:
    """Generic keyboard list picker. Returns index or None."""
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit import PromptSession as PS

    kb = KeyBindings()
    idx = [0]

    def _toolbar():
        lines = [f"[bold]{title}[/bold]"] if title else []
        for i, opt in enumerate(options):
            marker = "▶" if i == idx[0] else " "
            lines.append(f"{marker} [{opt['num']}] {opt['text'][:100]}")
        lines.append("↑↓ 选择  Enter 确认  Esc 取消")
        return "  ".join(lines)

    @kb.add("up")
    def _(event): idx[0] = (idx[0] - 1) % len(options)

    @kb.add("down")
    def _(event): idx[0] = (idx[0] + 1) % len(options)

    @kb.add("tab")
    def _(event): idx[0] = (idx[0] + 1) % len(options)

    @kb.add("s-tab")
    def _(event): idx[0] = (idx[0] - 1) % len(options)

    @kb.add("enter")
    def _(event): event.app.exit(result=idx[0])

    @kb.add("escape")
    def _(event): event.app.exit(result=None)

    @kb.add("c-c")
    def _(event): event.app.exit(result=None)

    ps = PS(key_bindings=kb, bottom_toolbar=_toolbar, style=CHAT_STYLE)
    try:
        return ps.prompt("")
    except (EOFError, KeyboardInterrupt):
        return None


# ── Help ──────────────────────────────────────────────────────────────

def show_help() -> str:
    lines = ["\n📖 [bold]可用命令[/bold]\n"]
    category_names = {"session": "💬 会话", "config": "⚙️ 配置", "help": "❓ 其他"}
    for cat_key, cmds in SLASH_COMMANDS.items():
        lines.append(f"  [bold]{category_names.get(cat_key, cat_key)}[/bold]")
        for cmd, (desc, *_rest) in cmds.items():
            lines.append(f"    [cyan]{cmd:12s}[/cyan] {desc}")
    lines.append("")
    lines.append("[dim]Tip: Tab 键自动补全  |  Ctrl+Enter 换行  |  Ctrl+D 退出[/dim]")
    return "\n".join(lines)


# ── Slash command dispatch ─────────────────────────────────────────────

def handle_slash_command(text: str, context: dict) -> str | None:
    if not text.startswith("/"):
        return None

    parts = text.strip().split(None, 1)
    cmd = parts[0]
    args = parts[1] if len(parts) > 1 else ""

    if cmd in ("/quit", "/q"):
        return "EXIT"

    cmd_info = _all_flat.get(cmd)
    if cmd_info is None:
        return f"未知命令: {cmd}\n输入 /help 查看可用命令。"

    desc, action, *rest = cmd_info
    has_args = rest[0] if rest else False
    if has_args:
        if not args:
            return f"需要参数: {desc}"
        return action(context, args)
    return action(context)


# ── Progress persistence ──────────────────────────────────────────────

def save_progress(concept: str, status: str, notes: str = "") -> None:
    import json
    progress_file = DATA_DIR / "progress.json"
    data = json.loads(progress_file.read_text(encoding="utf-8")) if progress_file.exists() else []
    for item in data:
        if item.get("concept") == concept:
            item["status"] = status
            item["notes"] = notes or item.get("notes", "")
            break
    else:
        data.append({"concept": concept, "status": status, "notes": notes})
    progress_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_assessment(dimension: str, value: str, concept: str = "", evidence: str = "") -> None:
    """Persist student assessment to ~/.openteacher/profiles/default.json."""
    import json, datetime
    from openteacher.config import PROFILES_DIR, ensure_dirs

    ensure_dirs()
    profile_file = PROFILES_DIR / "default.json"

    if profile_file.exists():
        profile = json.loads(profile_file.read_text(encoding="utf-8"))
    else:
        profile = {
            "created_at": datetime.datetime.now().isoformat(),
            "learning_orientation": "",
            "concept_levels": {},
            "skill_levels": {},
            # Cognitive / personality (global, cross-subject)
            "memory_style": "",
            "cognitive_strength": "",
            "grasp_speed": "",
            "discipline": "",
            "overall_summary": "",
            "cognitive_notes": {},
            "history": [],
        }

    now = datetime.datetime.now().isoformat()

    if dimension in ("learning_orientation", "overall_summary"):
        profile[dimension] = value
    elif dimension == "concept_level":
        profile["concept_levels"][concept] = {"level": value, "evidence": evidence, "updated_at": now}
    elif dimension == "skill_level":
        profile["skill_levels"][concept] = {"level": value, "evidence": evidence, "updated_at": now}
    elif dimension in ("memory_style", "cognitive_strength", "grasp_speed", "discipline"):
        # Cognitive/personality traits: write directly to profile root
        profile[dimension] = value
        profile.setdefault("cognitive_notes", {})[dimension] = {"value": value, "evidence": evidence, "updated_at": now}

    profile["history"].append({
        "dimension": dimension, "value": value, "concept": concept,
        "evidence": evidence, "recorded_at": now,
    })

    profile_file.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Prompt styling ────────────────────────────────────────────────────

CHAT_STYLE = Style.from_dict({
    "prompt": "bold cyan",
    "bottom-toolbar": "dim italic",
})


# ── Session picker UI ─────────────────────────────────────────────────

def session_picker(sessions: list[dict]) -> dict | str | None:
    """Interactive session picker with keyboard navigation.
    Up/Down to select, Enter to open, Space to pin, N for new, Q/Esc to quit."""
    from openteacher.agent.sessions import set_pinned_session, clear_pinned_session, get_pin_config
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit import PromptSession as PS

    pin_config = get_pin_config()
    pinned_name = [pin_config.get("auto_load", "")]  # mutable

    idx = [0]
    sessions_list = sessions  # capture

    def _picker_toolbar():
        lines = []
        for i, s in enumerate(sessions_list):
            marker = "▶" if i == idx[0] else " "
            pin_mark = "📌" if s["name"] == pinned_name[0] else ""
            src = "项目" if s["source"] == "project" else "全局"
            subj = s["subject"] or "(无)"
            lines.append(
                f"{marker} {pin_mark} [cyan]{s['name']:20s}[/cyan] "
                f"📚 {subj:16s} 💬 {s['messages']:3d}条  {s['saved_at']}  {src}"
            )
        lines.append(
            f"{'▶' if idx[0] == len(sessions_list) else ' '} [bold]＋新建会话[/bold]"
        )
        lines.append("")
        lines.append("↑↓ 选择  Enter 打开  Space 固定/取消  N 新建  Q 退出")
        if pinned_name[0]:
            lines.append(f"📌 已固定: {pinned_name[0]}（启动时自动加载）")
        return "  ".join(lines)

    kb = KeyBindings()

    @kb.add("up")
    def _(event): idx[0] = (idx[0] - 1) % (len(sessions_list) + 1)

    @kb.add("down")
    def _(event): idx[0] = (idx[0] + 1) % (len(sessions_list) + 1)

    @kb.add("enter")
    def _(event):
        if idx[0] < len(sessions_list):
            event.app.exit(result=sessions_list[idx[0]])
        else:
            event.app.exit(result="NEW")

    @kb.add("space")
    def _(event):
        if idx[0] < len(sessions_list):
            s = sessions_list[idx[0]]
            if s["name"] == pinned_name[0]:
                clear_pinned_session()
                pinned_name[0] = ""
            else:
                set_pinned_session(s["name"], s["source"])
                pinned_name[0] = s["name"]

    @kb.add("n")
    def _(event): event.app.exit(result="NEW")

    @kb.add("q")
    def _(event): event.app.exit(result=None)

    @kb.add("escape")
    def _(event): event.app.exit(result=None)

    @kb.add("c-c")
    def _(event): event.app.exit(result=None)

    ps = PS(key_bindings=kb, bottom_toolbar=_picker_toolbar, style=CHAT_STYLE)
    try:
        return ps.prompt("")
    except (EOFError, KeyboardInterrupt):
        return None


def run_shell_with_session(data: dict) -> None:
    """Start REPL with a pre-loaded session."""
    from openteacher.agent.display import console, print_info
    from openteacher.agent.sessions import load_session_by_name, set_pinned_session

    loop = ConversationLoop.from_dict(data)
    print_info(f"已加载会话: {data.get('session_name', '')}  |  {loop.turn_count} 轮对话")
    _run_repl_loop(loop)


# ── Main REPL ─────────────────────────────────────────────────────────

def run_shell(
    subject: str = "",
    language: str = "zh",
    teaching_style: str = "socratic",
    model: str | None = None,
) -> None:
    from openteacher.config import DATA_DIR

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch_track_progress()

    # ── Init agent ──────────────────────────────────────────────────
    loop = ConversationLoop(
        subject=subject, language=language,
        teaching_style=teaching_style, model=model,
    )

    print_logo()
    print_welcome()

    try:
        loop.start()
    except Exception as e:
        _handle_startup_error(e)
        _run_offline_repl(loop)
        return

    _run_repl_loop(loop)


def _run_repl_loop(loop: ConversationLoop) -> None:
    """Main REPL: online, full agent interaction."""
    from openteacher.config import DATA_DIR
    from openteacher import config as cfg

    history_file = DATA_DIR / "chat_history.txt"
    session = PromptSession(
        history=FileHistory(str(history_file)),
                completer=SlashCompleter(),
        complete_while_typing=True,
        key_bindings=repl_bindings,
        style=CHAT_STYLE,
        bottom_toolbar=lambda: _toolbar_text(loop),
    )

    context = {"loop": loop}

    while loop.running:
        try:
            user_input = session.prompt(
                [("class:prompt", "\n❯ ")],
                multiline=False,
            ).strip()
        except (EOFError, KeyboardInterrupt):
            _auto_save_on_exit(loop)
            print_info("\n再见！学习愉快 📚")
            break

        if user_input == "EXIT":
            _auto_save_on_exit(loop)
            print_info("再见！学习愉快 📚")
            break
        if user_input == "INTERRUPT":
            print_info("已中断")
            continue
        if not user_input:
            continue

        # Slash command?
        cmd_result = handle_slash_command(user_input, context)
        if cmd_result is not None:
            if cmd_result == "EXIT":
                _auto_save_on_exit(loop)
                print_info("再见！学习愉快 📚")
                break
            console.print(cmd_result)
            continue

        # Agent interaction
        try:
            response = loop.send_message(user_input)
        except Exception as e:
            msg = str(e)
            if "401" in msg or "Incorrect API key" in msg or "invalid_api_key" in msg:
                print_error("API Key 无效。")
                console.print("[bold yellow]请输入 [bold]/setup[/bold] 重新配置[/bold yellow]")
            else:
                print_error(f"请求失败: {msg}")
            continue

        # Auto-save after meaningful conversation
        _auto_save_silent(loop)

        # Interactive choice picking
        options = _extract_options(response)
        if options:
            selected = _pick_choice_interactive(options, session, loop)
            if selected:
                loop.messages.append({"role": "user", "content": selected})
                response = loop.send_message(selected)
                _auto_save_silent(loop)
                print_assistant_header()
                continue

        # Curriculum review — if lesson plan has pending lessons, offer review
        if loop.phase == "planning":
            from openteacher.config import PLANS_DIR
            import json
            plan_files = list(PLANS_DIR.glob("*.json"))
            if plan_files:
                latest = max(plan_files, key=lambda p: p.stat().st_mtime)
                plan = json.loads(latest.read_text(encoding="utf-8"))
                lessons = plan.get("lessons", [])
                pending = [l for l in lessons if l["status"] == "pending" and not l.get("skipped")]
                if len(pending) >= 2:  # Only offer review if there's meaningful content
                    skipped_ids = _review_curriculum(pending)
                    if skipped_ids is not None:
                        # Mark skipped lessons
                        for lesson in lessons:
                            if lesson["id"] in skipped_ids:
                                lesson["skipped"] = True
                                lesson["status"] = "completed"
                        from openteacher.tutor.planner import save_plan
                        save_plan(plan["subject"], plan)
                        if skipped_ids:
                            loop.messages.append({
                                "role": "user",
                                "content": f"我已学会以下课程，请从计划中移除并调整后续内容: {', '.join(str(i) for i in skipped_ids)}",
                            })
                            response = loop.send_message(
                                f"我已学会以下课程，请从计划中移除并调整后续内容: {', '.join(str(i) for i in skipped_ids)}"
                            )
                            _auto_save_silent(loop)
                            print_assistant_header()
                            continue

        print_assistant_header()


def _extract_options(text: str) -> list | None:
    import re
    options = []

    # Match all common option formats: [1], 1., 1), (1)
    patterns = [
        r"(?:^|\n)\[(\d+)\]\s*(.+?)(?=\n\[(?:\d+)\]|\n\d+[\.\)]|\Z)",
        r"(?:^|\n)(\d+)[\.\)]\s*(.+?)(?=\n\d+[\.\)]|\Z)",
        r"(?:^|\n)\((\d+)\)\s*(.+?)(?=\n\(\d+\)|\Z)",
        r"\[(\d+)\]\s*([^\[]+?)(?=\[|\Z)",  # loose fallback
    ]
    for pattern in patterns:
        for m in re.finditer(pattern, text, re.DOTALL):
            num = int(m.group(1))
            desc = m.group(2).strip().rstrip(".。,， ")
            if not any(o["num"] == num for o in options):
                options.append({"num": num, "text": desc})
        if len(options) >= 2:
            break

    return options if len(options) >= 2 else None


def _pick_choice_interactive(options: list, session, loop):
    """Arrow keys to navigate, Enter to select, Space for notes, Esc skip."""
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit import PromptSession as PS

    kb = KeyBindings()
    idx = [0]
    note_mode = [False]
    notes = [""]

    def _toolbar():
        lines = []
        for i, opt in enumerate(options):
            marker = "▶" if i == idx[0] else " "
            lines.append(f"{marker} [{opt['num']}] {opt['text'][:100]}")
        if note_mode[0]:
            lines.append(f"  备注: {notes[0]}_")
        else:
            lines.append("↑↓ 选择  Enter 确认  Space 备注  Esc 跳过")
        return "  ".join(lines)

    @kb.add("up")
    def _(event): idx[0] = (idx[0] - 1) % len(options)

    @kb.add("down")
    def _(event): idx[0] = (idx[0] + 1) % len(options)

    @kb.add("tab")
    def _(event): idx[0] = (idx[0] + 1) % len(options)

    @kb.add("s-tab")
    def _(event): idx[0] = (idx[0] - 1) % len(options)

    @kb.add("enter")
    def _(event):
        result = options[idx[0]]["text"]
        if notes[0]:
            result += f"。补充: {notes[0]}"
        event.app.exit(result=result)

    @kb.add("space")
    def _(event): note_mode[0] = True

    @kb.add("escape")
    def _(event): event.app.exit(result=None)

    @kb.add("<any>")
    def _(event):
        if note_mode[0]:
            if event.data == "backspace":
                notes[0] = notes[0][:-1]
            elif len(event.data) == 1:
                notes[0] += event.data

    ps = PS(key_bindings=kb, bottom_toolbar=_toolbar, style=CHAT_STYLE)
    try:
        return ps.prompt("")
    except (EOFError, KeyboardInterrupt):
        return None


def _review_curriculum(lessons: list) -> list[int]:
    """Interactive curriculum review. Space=toggle, A=all, I=invert, Enter=confirm.
    Returns list of skipped lesson IDs (lessons user already knows)."""
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit import PromptSession as PS

    skipped = set()  # lesson IDs marked as "already know"
    idx = [0]
    lesson_list = lessons
    count = len(lessons)

    kb = KeyBindings()

    def _toggle():
        lid = lesson_list[idx[0]]["id"]
        if lid in skipped:
            skipped.discard(lid)
        else:
            skipped.add(lid)

    def _toolbar():
        lines = ["[bold]审核课程 — 勾掉已会的内容[/bold]"]
        lines.append("")
        for i, lesson in enumerate(lesson_list):
            marker = "▶" if i == idx[0] else " "
            check = "[x]" if lesson["id"] in skipped else "[ ]"
            lines.append(f"{marker} {check} {lesson['title']}")
            if lesson.get("description"):
                lines.append(f"     [dim]{lesson['description']}[/dim]")
        lines.append("")
        lines.append(
            f"第 {idx[0]+1}/{count} 课  Space 勾选/取消  A 全选  I 反选  "
            f"↑↓/Tab 移动  Enter 确认  已勾 {len(skipped)}"
        )
        return "  ".join(lines)

    @kb.add("up")
    def _(event): idx[0] = (idx[0] - 1) % count

    @kb.add("down")
    def _(event): idx[0] = (idx[0] + 1) % count

    @kb.add("tab")
    def _(event): idx[0] = (idx[0] + 1) % count

    @kb.add("s-tab")
    def _(event): idx[0] = (idx[0] - 1) % count

    @kb.add("space")
    def _(event): _toggle()

    @kb.add("a")
    def _(event):
        for lesson in lesson_list:
            skipped.add(lesson["id"])

    @kb.add("i")
    def _(event):
        for lesson in lesson_list:
            lid = lesson["id"]
            if lid in skipped:
                skipped.discard(lid)
            else:
                skipped.add(lid)

    @kb.add("enter")
    def _(event): event.app.exit(result=list(skipped))

    @kb.add("escape")
    def _(event): event.app.exit(result=None)

    @kb.add("c-c")
    def _(event): event.app.exit(result=None)

    ps = PS(key_bindings=kb, bottom_toolbar=_toolbar, style=CHAT_STYLE)
    try:
        return ps.prompt("")
    except (EOFError, KeyboardInterrupt):
        return None


def _auto_save_silent(loop: ConversationLoop) -> None:
    """Silent auto-save after each meaningful exchange."""
    if loop.turn_count > 0:
        try:
            loop.save()
        except Exception:
            pass


def _auto_save_on_exit(loop: ConversationLoop) -> None:
    """Auto-save session if it has meaningful conversation."""
    if loop.turn_count > 0:
        try:
            name = loop.save()
            print_info(f"会话已自动保存为: {name}")
        except Exception:
            pass


def _run_offline_repl(loop: ConversationLoop) -> None:
    """Offline REPL: no API key, only slash commands work."""
    from openteacher.config import DATA_DIR

    history_file = DATA_DIR / "chat_history.txt"
    session = PromptSession(
        history=FileHistory(str(history_file)),
        completer=SlashCompleter(),
        complete_while_typing=True,
        key_bindings=repl_bindings,
        style=CHAT_STYLE,
        bottom_toolbar=lambda: "⚙️  离线模式 — 请输入 /setup 配置 API 或 /help 查看帮助",
    )

    context = {"loop": loop}

    while True:
        try:
            user_input = session.prompt(
                [("class:prompt", "\n❯ ")],
                multiline=False,
            ).strip()
        except (EOFError, KeyboardInterrupt):
            _auto_save_on_exit(loop)
            print_info("\n再见！")
            break

        if user_input in ("EXIT", "/quit", "/q"):
            _auto_save_on_exit(loop)
            print_info("再见！")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            cmd_result = handle_slash_command(user_input, context)
            if cmd_result == "EXIT":
                print_info("再见！")
                break
            console.print(cmd_result or "")
            if user_input.strip() == "/setup":
                # After setup, ask to restart
                console.print("[bold green]配置完成！[/bold green] 请重新启动 [bold]openteacher[/bold]")
                break
        else:
            print_error("尚未配置 API Key。请先输入 [bold]/setup[/bold] 配置 API 连接。")


def _toolbar_text(loop: ConversationLoop) -> str:
    """Bottom toolbar showing phase, mode, model, turns."""
    phase_icons = {"diagnosis": "🔍 诊断", "learning": "📖 学习", "end": "🏁 结束"}
    modes = {"guided": "引导", "direct": "讲解", "mixed": "混合"}

    parts = [phase_icons.get(loop.phase, "💬")]
    if loop.subject:
        parts.append(f"| 📚 {loop.subject}")
    parts.append(f"| 🎯 {modes.get(loop.mode, loop.mode)}")
    parts.append(f"| 🤖 {loop.model}")
    parts.append(f"| 💬 {loop.turn_count}")
    return " ".join(parts)


# ── Helpers ───────────────────────────────────────────────────────────

def _maybe_track_progress_from_response(response: str) -> None:
    import re
    indicators = [
        (r"你已经\s*(?:完全\s*)?掌握了\s*(.+?)(?:[。，\n]|$)", "mastered"),
        (r"你对\s*(.+?)\s*的理解很", "in_progress"),
        (r"(.+?)\s*需要再复习一下", "needs_review"),
    ]
    for pattern, status in indicators:
        match = re.search(pattern, response)
        if match:
            concept = match.group(1).strip().rstrip("了")
            if concept:
                save_progress(concept, status)


def monkeypatch_track_progress():
    from openteacher.tools.registry import registry

    # Persist track_progress
    tp = registry.get_tool("track_progress")
    if tp is not None:
        def _persistent_tracker(concept: str, status: str, notes: str = "") -> str:
            save_progress(concept, status, notes)
            return tp.handler(concept=concept, status=status, notes=notes)
        tp.handler = _persistent_tracker

    # Persist assess_student
    ae = registry.get_tool("assess_student")
    if ae is not None:
        def _persistent_assess(dimension: str, value: str, concept: str = "", evidence: str = "") -> str:
            save_assessment(dimension, value, concept, evidence)
            return ae.handler(dimension=dimension, value=value, concept=concept, evidence=evidence)
        ae.handler = _persistent_assess
