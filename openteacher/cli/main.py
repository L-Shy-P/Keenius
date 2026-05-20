"""CLI entry point for OpenTeacher.

Just launches the REPL.  Everything else is slash commands inside.
"""

from __future__ import annotations
import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openteacher",
        description="OpenTeacher — CLI AI 智能老师",
    )
    parser.add_argument("--subject", "-s", default="", help="学习主题")
    parser.add_argument("--language", "-l", default="zh", choices=["zh", "en"], help="教学语言")
    parser.add_argument(
        "--style", choices=["socratic", "direct", "coaching"],
        default="socratic", help="教学风格"
    )
    parser.add_argument("--model", "-m", default=None, help="模型名称")
    return parser


def main() -> None:
    from openteacher.config import load_env

    load_env()

    parser = build_parser()
    args = parser.parse_args()

    from openteacher.cli.shell import run_shell

    run_shell(
        subject=args.subject,
        language=args.language,
        teaching_style=args.style,
        model=args.model,
    )


if __name__ == "__main__":
    main()
