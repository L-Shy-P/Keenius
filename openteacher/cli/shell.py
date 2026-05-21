"""Interactive REPL shell using prompt-toolkit.

This is the main user interface — a rich terminal chat with the AI teacher.
"""

from __future__ import annotations
from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.document import Document

from openteacher.agent.display import (
    console,
    print_welcome,
    print_assistant_header,
    print_markdown,
    print_error,
    print_info,
    print_success,
)
from openteacher.agent.loop import ConversationLoop
from openteacher.config import DATA_DIR

# ── Slash command registry ────────────────────────────────────────────

SLASH_COMMANDS: dict[str, dict] = {
    "session": {
        "/new":     ("开始新对话（重置上下文）", lambda ctx: ctx.get("loop").reset() or "对话已重置。输入问题开始吧！"),
        "/save":    ("保存当前会话 /save [名称]", lambda ctx, a: _cmd_save(ctx, a), True),
        "/load":    ("加载历史会话 /load <名称>", lambda ctx, a: _cmd_load(ctx, a), True),
        "/sessions": ("列出所有已保存的会话", lambda ctx: _cmd_list_sessions()),
        "/subject": ("切换学习主题 /subject <主题>", lambda ctx, a: setattr(ctx["loop"], "subject", a) or f"主题已切换为: {a}", True),
        "/style":   ("切换教学风格 /style <socratic|direct|coaching>", lambda ctx, a: setattr(ctx["loop"], "teaching_style", a) or f"教学风格已切换为: {a}", True),
    },
    "config": {
        "/setup":    ("配置 API Key 和模型", lambda _: run_setup_wizard()),
        "/config":   ("查看当前配置", lambda _: show_config()),
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


# ── Key bindings ──────────────────────────────────────────────────────

bindings = KeyBindings()


@bindings.add("c-d")
def _(event):
    """Ctrl+D to exit."""
    event.app.exit(result="EXIT")


@bindings.add("escape", "enter")
def _(event):
    """Alt+Enter for newline."""
    event.app.current_buffer.insert_text("\n")


@bindings.add("c-c")
def _(event):
    """Ctrl+C to interrupt."""
    event.app.exit(result="INTERRUPT")


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

    choice = prompt("选择 Provider [1-4] (默认: 1) ").strip() or "1"
    provider_config = {
        "1": ("OPENAI_API_KEY", "https://api.openai.com/v1", "gpt-4o"),
        "2": ("DEEPSEEK_API_KEY", "https://api.deepseek.com/v1", "deepseek-chat"),
        "3": ("ANTHROPIC_API_KEY", "https://api.anthropic.com/v1", "claude-sonnet-4-6"),
        "4": ("API_KEY", "", ""),
    }
    env_key, default_base, default_model = provider_config.get(choice, provider_config["1"])

    console.print()
    api_key = prompt("API Key (输入会隐藏): ", is_password=True).strip()
    if not api_key:
        display_error("API Key 不能为空，配置取消。")
        return "配置取消。"

    console.print()
    if choice == "4":
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
    console.print("[dim]输入 [bold]/new[/bold] 开始新对话，或直接输入问题。[/dim]")
    return ""


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

    lines.append(f"\n[dim]数据文件: {pf}[/dim]")
    return "\n".join(lines)


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
    if not name:
        return "请指定会话名称。用法: /load <名称>\n输入 /sessions 查看可用的会话列表。"
    loop = ctx["loop"]
    if loop.load(name):
        loop.subject = loop.subject or ""
        return f"✓ 已加载会话 [cyan]{name}[/cyan]\n  {loop.turn_count} 轮对话, {len(loop.messages)} 条消息\n\n输入内容继续对话。"
    return f"未找到会话: {name}\n输入 /sessions 查看可用的会话列表。"


def _cmd_list_sessions() -> str:
    sessions = ConversationLoop.list_sessions()
    if not sessions:
        return "暂无保存的会话。输入 /save 保存当前会话。"
    lines = ["\n📂 [bold]已保存的会话[/bold]\n"]
    for s in sessions:
        lines.append(
            f"  [cyan]{s['name']:20s}[/cyan] "
            f"📚 {s['subject'] or '(无主题)':16s} "
            f"[dim]{s['model']}[/dim]  "
            f"💬 {s['messages']}条  "
            f"{s['saved_at']}"
        )
    lines.append("\n[dim]使用 /load <名称> 加载会话[/dim]")
    return "\n".join(lines)


# ── Help ──────────────────────────────────────────────────────────────

def show_help() -> str:
    lines = ["\n📖 [bold]可用命令[/bold]\n"]
    category_names = {"session": "💬 会话", "config": "⚙️ 配置", "help": "❓ 其他"}
    for cat_key, cmds in SLASH_COMMANDS.items():
        lines.append(f"  [bold]{category_names.get(cat_key, cat_key)}[/bold]")
        for cmd, (desc, *_rest) in cmds.items():
            lines.append(f"    [cyan]{cmd:12s}[/cyan] {desc}")
    lines.append("")
    lines.append("[dim]Tip: Tab 键自动补全  |  Alt+Enter 换行  |  Ctrl+D 退出[/dim]")
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
            "concept_levels": {},   # { "concept_name": {"level": "C2", "evidence": "...", "updated_at": "..."} }
            "skill_levels": {},     # { "concept_name": {"level": "S3", "evidence": "...", "updated_at": "..."} }
            "history": [],
        }

    now = datetime.datetime.now().isoformat()

    if dimension == "learning_orientation":
        profile["learning_orientation"] = value
    elif dimension == "overall_summary":
        profile["overall_summary"] = value
    elif dimension == "concept_level":
        profile["concept_levels"][concept] = {"level": value, "evidence": evidence, "updated_at": now}
    elif dimension == "skill_level":
        profile["skill_levels"][concept] = {"level": value, "evidence": evidence, "updated_at": now}
    elif dimension == "understanding_depth":
        profile.setdefault("understanding_depth", {})[concept or "overall"] = {"level": value, "evidence": evidence, "updated_at": now}
    elif dimension == "application_ability":
        profile.setdefault("application_ability", {})[concept or "overall"] = {"level": value, "evidence": evidence, "updated_at": now}

    profile["history"].append({
        "dimension": dimension, "value": value, "concept": concept,
        "evidence": evidence, "recorded_at": now,
    })

    profile_file.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Prompt styling ────────────────────────────────────────────────────

CHAT_STYLE = Style.from_dict({
    "prompt": "bold cyan",
    "toolbar": "bg:#1a1a2e #888888",
    "bottom-toolbar": "bg:#1a1a2e #aaaaaa",
})


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
        auto_suggest=AutoSuggestFromHistory(),
        completer=SlashCompleter(),
        complete_while_typing=True,
        key_bindings=bindings,
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

        # Streaming already displayed the response live — just add spacing
        _maybe_track_progress_from_response(response)
        print_assistant_header()
        print_assistant_header()


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
        key_bindings=bindings,
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
    """Bottom toolbar showing model, turns, subject."""
    parts = []
    parts.append(f" 🤖 {loop.model}")
    if loop.subject:
        parts.append(f"| 📚 {loop.subject}")
    parts.append(f"| 💬 轮次: {loop.turn_count}")
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
