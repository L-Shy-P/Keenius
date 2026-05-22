"""Display helpers using Rich for beautiful terminal output."""

from __future__ import annotations
import time
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.rule import Rule
from rich.text import Text

console = Console()

# ── Logo ────────────────────────────────────────────────────────────

LOGO = """\
[bold cyan]   ____              _____[/bold cyan][bold green]__[/bold green][bold cyan]              __[/bold cyan]
[bold cyan]  / __ \\[/bold cyan][bold green]___  ___  [/bold cyan][bold green]/_  __/ /_  ___  ____ _/ /_  ___  _____[/bold cyan]
[bold cyan] / / / / _ \\/ _ \\  / / / __ \\/ _ \\/ __ `/ __ \\/ _ \\/ ___/[/bold cyan]
[bold cyan]/ /_/ /  __/  __/ / / / / / /  __/ /_/ / /_/ /  __/ /[/bold cyan]
[bold cyan]\\____/\\___/\\___/ /_/ /_/ /_/\\___/\\__,_/_.___/\\___/_/[/bold cyan]
"""

LOGO_SMALL = """\
[bold cyan]OpenTeacher[/bold cyan] [dim]— CLI AI 智能老师[/dim]
"""


def print_logo() -> None:
    """Print the ASCII art logo with a brief animation."""
    import sys
    console.print()
    try:
        w = console.width
    except Exception:
        w = 80
    if w >= 60:
        console.print(LOGO)
    else:
        console.print(LOGO_SMALL)
    console.print()


def print_welcome() -> None:
    """Print welcome panel after logo."""
    console.print(
        Panel.fit(
            "[dim]输入问题开始对话  |  /help 查看命令  |  /setup 配置 API[/dim]\n"
            "[dim]Tab 补全  |  Alt+Enter 换行  |  Ctrl+D 退出  |  ↑↓ 选择历史[/dim]",
            border_style="cyan",
            title="🎓 欢迎使用 OpenTeacher",
        )
    )
    console.print()


# ── Separators ──────────────────────────────────────────────────────

def print_assistant_header() -> None:
    console.print()
    console.print(Rule(style="dim cyan"))


# ── Tool display ────────────────────────────────────────────────────

_TOOL_EMOJI = {
    "create_quiz": "📝", "check_answer": "🔍",
    "give_examples": "💡", "explain_deeper": "🔬",
    "summarize_lesson": "📋", "spaced_review_reminder": "⏰",
    "track_progress": "📌", "save_note": "📓",
    "assess_student": "🧠", "manage_plan": "📋",
    "write_lesson_content": "✍️", "generate_curriculum": "📚",
    "plan_summary": "📋", "read_file": "📖", "write_file": "✍️",
}


def print_tool_call(tool_name: str, tool_args: dict) -> None:
    emoji = _TOOL_EMOJI.get(tool_name, "🔧")
    preview = ""
    for v in tool_args.values():
        s = str(v)
        if len(s) > 50:
            s = s[:50] + "..."
        preview = s
        break
    console.print(f"  [dim]┊ {emoji} {tool_name}: {preview}[/dim]")


def print_tool_result(result: str) -> None:
    short = result.replace("\n", " ")[:80]
    console.print(f"  [dim green]┊ ✓ {short}[/dim green]")


# ── Content display ─────────────────────────────────────────────────

def print_markdown(text: str) -> None:
    try:
        console.print(Markdown(text))
    except Exception:
        console.print(text)


def print_error(msg: str) -> None:
    console.print(f"[red]✗ {msg}[/red]")


def print_info(msg: str) -> None:
    console.print(f"[dim]  {msg}[/dim]")


def print_success(msg: str) -> None:
    console.print(f"[green]✓ {msg}[/green]")


def print_thinking() -> None:
    console.print("[dim]  ⏳ ...[/dim]", end="\r")


# ── Other panels ────────────────────────────────────────────────────

def show_progress_table(progress: dict[str, str]) -> None:
    table = Table(title="📊 学习进度")
    table.add_column("概念", style="cyan")
    table.add_column("状态", style="green")
    for concept, status in progress.items():
        table.add_row(concept, status)
    console.print(table)


def print_setup_banner() -> None:
    console.print()
    console.print(
        Panel.fit(
            "配置 LLM API 连接。数据安全保存在本地。",
            border_style="cyan",
            title="⚙️ 配置向导",
        )
    )
    console.print()


def provider_selector() -> str:
    table = Table(title="选择 API Provider")
    table.add_column("#", style="dim", width=4)
    table.add_column("Provider", style="cyan")
    table.add_column("Base URL", style="dim")
    table.add_column("推荐模型", style="green")
    for num, name, url, model in [
        ("1", "OpenAI", "https://api.openai.com/v1", "gpt-4o"),
        ("2", "DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat"),
        ("3", "Anthropic", "https://api.anthropic.com/v1", "claude-sonnet-4-6"),
        ("4", "自定义", "你自己输入", "你自己输入"),
    ]:
        table.add_row(num, name, url, model)
    console.print(table)
    return ""
