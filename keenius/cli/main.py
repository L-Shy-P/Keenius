"""Keenius CLI 入口点。

启动时扫描项目目录中已有的会话。
如果存在会话，显示选择器。支持自动加载固定会话。
"""

from __future__ import annotations
import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="Keenius",
        description="Keenius — CLI AI 智能老师",
    )
    parser.add_argument("--subject", "-s", default="", help="学习主题")
    parser.add_argument("--language", "-l", default="zh", choices=["zh", "en"], help="教学语言")
    parser.add_argument("--style", choices=["socratic", "direct", "coaching"], default="socratic", help="教学风格")
    parser.add_argument("--model", "-m", default=None, help="模型名称")
    parser.add_argument("--no-picker", action="store_true", help="跳过会话选择界面，直接新建")
    return parser


def main() -> None:
    from keenius.config import load_env

    load_env()

    parser = build_parser()
    args = parser.parse_args()

    # ── 启动时选择会话 ──────────────────────────────────
    if not args.no_picker:
        from keenius.agent.sessions import scan_sessions, get_auto_load_session, load_session_by_name

        sessions = scan_sessions()
        auto_name, auto_source = get_auto_load_session()

        if auto_name and auto_source:
            # 自动加载已固定的会话
            data = load_session_by_name(auto_name, auto_source)
            if data:
                _start_with_session(data)
                return
            # 如果固定的会话已不存在，静默清除

        if sessions:
            choice = _show_session_picker(sessions)
            if choice == "NEW":
                _warn_multiple_sessions(sessions)
                _start_fresh(args)
            elif choice is not None:
                from keenius.agent.sessions import load_session_by_name
                data = load_session_by_name(choice["name"], choice["source"])
                if data:
                    _start_with_session(data)
                    return
    # 回退到新会话
    _start_fresh(args)


def _start_fresh(args) -> None:
    from keenius.cli.shell import run_shell
    run_shell(
        subject=args.subject,
        language=args.language,
        teaching_style=args.style,
        model=args.model,
    )


def _start_with_session(data: dict) -> None:
    from keenius.cli.shell import run_shell_with_session
    run_shell_with_session(data)


def _warn_multiple_sessions(sessions: list[dict]) -> None:
    """如果当前目录存在多个会话，发出警告。"""
    project_sessions = [s for s in sessions if s["source"] == "project"]
    if len(project_sessions) >= 2:
        from keenius.agent.display import console
        console.print()
        console.print("[yellow]⚠  不建议在同一文件夹下建立多个聊天记录[/yellow]")
        console.print("[dim]考虑使用 /save <名称> 来区分不同主题，而非多开新会话[/dim]")
        console.print()


def _show_session_picker(sessions: list[dict]) -> dict | str | None:
    """显示交互式会话选择器，包含 logo 和欢迎信息。"""
    from keenius.agent.display import print_logo, print_welcome
    from keenius.cli.shell import session_picker
    print_logo()
    print_welcome()
    return session_picker(sessions)


if __name__ == "__main__":
    main()
