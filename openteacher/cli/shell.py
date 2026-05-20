"""Interactive REPL shell using prompt-toolkit.

This is the main user interface — a rich terminal chat with the AI teacher.
"""

from __future__ import annotations
from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory

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


def _handle_startup_error(err: Exception) -> None:
    """Display a user-friendly error and guide to setup, for any startup failure."""
    msg = str(err)
    from openteacher.config import get_api_key

    if not get_api_key():
        print_error("未配置 API Key，无法连接 AI 导师。")
        console.print()
        console.print("[bold yellow]请输入 [bold]/setup[/bold] 配置 API 连接[/bold yellow]")
        console.print()
        return

    if "401" in msg or "Incorrect API key" in msg or "invalid_api_key" in msg:
        print_error("API Key 无效。")
        console.print()
        console.print("[bold yellow]请输入 [bold]/setup[/bold] 重新配置[/bold yellow]")
        console.print()
        return

    if "Connection" in msg or "connect" in msg.lower() or "timed out" in msg.lower():
        print_error(f"网络连接失败。请检查网络和 API Base URL 配置。\n详情: {msg}")
        return

    print_error(f"启动失败: {msg}")


def run_setup_wizard() -> str:
    """Run the setup wizard from within the REPL. Returns result message."""
    from openteacher import config
    from openteacher.agent.display import (
        print_setup_banner,
        provider_selector,
        print_success,
        print_error as display_error,
    )
    from prompt_toolkit import prompt

    existing_key = config.get_api_key()
    if existing_key:
        console.print(f"[dim]检测到已配置 API Key[/dim]")
        reconfigure = prompt("是否重新配置？[y/N] ").strip().lower()
        if reconfigure not in ("y", "yes"):
            return "保持现有配置。"

    print_setup_banner()
    provider_selector()

    provider_choice = prompt("选择 Provider [1-4] (默认: 1) ").strip() or "1"

    provider_config = {
        "1": ("OPENAI_API_KEY", "https://api.openai.com/v1", "gpt-4o"),
        "2": ("DEEPSEEK_API_KEY", "https://api.deepseek.com/v1", "deepseek-chat"),
        "3": ("ANTHROPIC_API_KEY", "https://api.anthropic.com/v1", "claude-sonnet-4-6"),
        "4": ("API_KEY", "", ""),
    }
    env_key, default_base, default_model = provider_config.get(
        provider_choice, provider_config["1"]
    )

    console.print()
    api_key = prompt("API Key (输入会隐藏): ", is_password=True).strip()
    if not api_key:
        display_error("API Key 不能为空，配置取消。")
        return "配置取消。"

    console.print()
    if provider_choice == "4":
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

    result = (
        f"✓ 配置完成！\n"
        f"  Provider: {env_key}\n"
        f"  Base URL: {base_url}\n"
        f"  Model:    {model}\n"
        f"\n[dim]配置将在下次启动时生效。输入 /new 开始对话。[/dim]"
    )
    print_success("API Key 已保存至 ~/.openteacher/.env")
    return result


def show_config() -> str:
    from openteacher import config

    cfg = config.load_config()
    api_key = config.get_api_key()
    lines = ["\n📋 当前配置:\n"]
    lines.append(f"  API Key:     {'已设置' if api_key else '未设置'}")
    lines.append(f"  Model:       {cfg.get('model', '未设置')}")
    lines.append(f"  API Base:    {cfg.get('api_base', '未设置')}")
    lines.append(f"  教学语言:    {cfg.get('language', 'zh')}")
    lines.append(f"  教学风格:    {cfg.get('teaching_style', 'socratic')}")
    return "\n".join(lines)


CHAT_STYLE = Style.from_dict(
    {
        "prompt": "bold cyan",
        "separator": "#666666",
    }
)

SLASH_COMMANDS: dict[str, dict] = {
    "/help": {
        "desc": "显示帮助信息",
        "action": lambda _: show_help(),
    },
    "/setup": {
        "desc": "配置 API Key 和模型",
        "action": lambda ctx: run_setup_wizard(),
    },
    "/new": {
        "desc": "开始新对话（重置上下文）",
        "action": lambda ctx: ctx.get("loop").reset() or "对话已重置。你想学什么？",
    },
    "/subject": {
        "desc": "切换学习主题。用法: /subject <主题>",
        "action": lambda ctx, args: (
            setattr(ctx["loop"], "subject", args) or f"主题已切换为: {args}"
        ),
        "has_args": True,
    },
    "/style": {
        "desc": "切换教学风格。用法: /style <socratic|direct|coaching>",
        "action": lambda ctx, args: (
            setattr(ctx["loop"], "teaching_style", args)
            or f"教学风格已切换为: {args}"
        ),
        "has_args": True,
    },
    "/config": {
        "desc": "查看当前配置",
        "action": lambda _: show_config(),
    },
    "/progress": {
        "desc": "查看学习进度",
        "action": lambda _: show_progress(),
    },
    "/quit": {
        "desc": "退出 OpenTeacher",
        "action": lambda _: "EXIT",
    },
    "/q": {
        "desc": "退出 OpenTeacher（别名）",
        "action": lambda _: "EXIT",
    },
}


def show_help() -> str:
    return "\n".join(
        [f"  {cmd:12s} - {info['desc']}" for cmd, info in SLASH_COMMANDS.items()]
    )


def show_progress() -> str:
    import json

    progress_file = DATA_DIR / "progress.json"
    if progress_file.exists():
        data = json.loads(progress_file.read_text(encoding="utf-8"))
        if not data:
            return "暂无学习进度记录。"
        lines = ["\n📊 学习进度:\n"]
        for item in data:
            emoji = {"mastered": "✅", "in_progress": "🔄", "needs_review": "📌"}.get(
                item.get("status", ""), "📎"
            )
            lines.append(f"  {emoji} {item['concept']}: {item['status']}")
    else:
        lines = ["暂无学习进度记录。"]
    return "\n".join(lines)


def handle_slash_command(text: str, context: dict) -> str | None:
    """Handle a slash command. Returns the output text, or None if not a command."""
    if not text.startswith("/"):
        return None

    parts = text.strip().split(None, 1)
    cmd = parts[0]
    args = parts[1] if len(parts) > 1 else ""

    if cmd == "/quit" or cmd == "/q":
        return "EXIT"

    cmd_info = SLASH_COMMANDS.get(cmd)
    if cmd_info is None:
        return f"未知命令: {cmd}\n输入 /help 查看可用命令。"

    if cmd_info.get("has_args"):
        if not args:
            return f"需要参数: {cmd_info['desc']}"
        return cmd_info["action"](context, args)
    return cmd_info["action"](context)


def save_progress(concept: str, status: str, notes: str = "") -> None:
    """Persist learning progress to disk."""
    import json

    progress_file = DATA_DIR / "progress.json"
    if progress_file.exists():
        data = json.loads(progress_file.read_text(encoding="utf-8"))
    else:
        data = []

    # Update or append
    for item in data:
        if item.get("concept") == concept:
            item["status"] = status
            item["notes"] = notes or item.get("notes", "")
            break
    else:
        data.append({"concept": concept, "status": status, "notes": notes})

    progress_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run_shell(
    subject: str = "",
    language: str = "zh",
    teaching_style: str = "socratic",
    model: str | None = None,
) -> None:
    """Run the interactive teaching REPL."""
    from openteacher.config import DATA_DIR

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Hook track_progress to persist to disk
    monkeypatch_track_progress()

    print_welcome()

    # Initialize agent
    loop = ConversationLoop(
        subject=subject,
        language=language,
        teaching_style=teaching_style,
        model=model,
    )

    context = {"loop": loop}

    # First message from the teacher
    try:
        opening = loop.start()
    except Exception as e:
        _handle_startup_error(e)
        return

    print_assistant_header()
    print_markdown(opening)
    print_assistant_header()

    # Setup prompt_toolkit session
    history_file = DATA_DIR / "chat_history.txt"
    session = PromptSession(
        history=FileHistory(str(history_file)),
        auto_suggest=AutoSuggestFromHistory(),
        style=CHAT_STYLE,
    )

    # ── Main REPL loop ─────────────────────────────────────────────
    while loop.running:
        try:
            user_input = session.prompt(
                [("class:prompt", "\n🧑 你: ")],
                multiline=False,
            ).strip()
        except (EOFError, KeyboardInterrupt):
            print_info("\n再见！学习愉快 📚")
            break

        if not user_input:
            continue

        # Check for slash commands
        cmd_result = handle_slash_command(user_input, context)
        if cmd_result is not None:
            if cmd_result == "EXIT":
                print_info("再见！学习愉快 📚")
                break
            console.print(cmd_result)
            continue

        # Send to agent and display response
        try:
            response = loop.send_message(user_input)
        except Exception as e:
            msg = str(e)
            if "401" in msg or "Incorrect API key" in msg or "invalid_api_key" in msg:
                print_error("API Key 无效。")
                console.print("[bold yellow]请输入 [bold]/setup[/bold] 重新配置 API Key[/bold yellow]")
            else:
                print_error(f"请求失败: {msg}")
            continue

        # Check for progress tracking in the conversation
        _maybe_track_progress_from_response(response)

        print_assistant_header()
        print_markdown(response)
        print_assistant_header()


def _maybe_track_progress_from_response(response: str) -> None:
    """Very simple heuristic: if the response mentions a tracked concept, record it."""
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
    """Hook into the track_progress tool to persist data.

    This is called at startup to ensure the tool results also get saved to disk.
    """
    from openteacher.tools.registry import registry

    original = registry.get_tool("track_progress")
    if original is None:
        return

    def _persistent_tracker(concept: str, status: str, notes: str = "") -> str:
        save_progress(concept, status, notes)
        return original.handler(concept=concept, status=status, notes=notes)

    original.handler = _persistent_tracker
