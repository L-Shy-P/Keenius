"""Display helpers using Rich for beautiful terminal output."""

from __future__ import annotations
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.rule import Rule
from rich.live import Live
from rich.spinner import Spinner

console = Console()


def print_welcome() -> None:
    """Print the welcome banner."""
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]OpenTeacher[/bold cyan] — CLI AI 智能老师\n"
            "用苏格拉底式提问 + 自适应学习路径帮你高效掌握任何知识领域。\n\n"
            "[dim]输入问题开始  |  /save 保存会话  |  /load 恢复会话[/dim]\n"
            "[dim]Tab 自动补全  |  Alt+Enter 换行  |  Ctrl+D 退出[/dim]",
            border_style="cyan",
            title="🎓 欢迎",
        )
    )
    console.print()


def print_assistant_header() -> None:
    console.print()
    console.print(Rule(style="cyan"))


_TOOL_EMOJI = {
    "create_quiz": "📝",
    "check_answer": "🔍",
    "give_examples": "💡",
    "explain_deeper": "🔬",
    "summarize_lesson": "📋",
    "spaced_review_reminder": "⏰",
    "track_progress": "📌",
    "save_note": "📓",
}


def print_tool_call(tool_name: str, tool_args: dict) -> None:
    """Display a tool call being made — clean one-line preview."""
    emoji = _TOOL_EMOJI.get(tool_name, "🔧")
    # Show first arg concisely
    preview = ""
    for k, v in tool_args.items():
        s = str(v)
        if len(s) > 40:
            s = s[:40] + "..."
        preview = s
        break
    label = f"{emoji} {tool_name}"
    if preview:
        label += f": {preview}"
    console.print(f"  [dim]{label}[/dim]")


def print_tool_result(result: str) -> None:
    console.print(f"  [dim green]{result}[/dim green]")


def print_markdown(text: str) -> None:
    """Render text as markdown."""
    try:
        md = Markdown(text)
        console.print(md)
    except Exception:
        console.print(text)


def print_error(msg: str) -> None:
    console.print(f"[red]❌ {msg}[/red]")


def print_info(msg: str) -> None:
    console.print(f"[dim]ℹ {msg}[/dim]")


def print_success(msg: str) -> None:
    console.print(f"[green]✓ {msg}[/green]")


def spinner(text: str = "思考中..."):
    """Return a Rich spinner context manager."""
    return console.status(f"[dim]{text}[/dim]", spinner="dots")


def print_thinking() -> None:
    """Print a thinking indicator to show before streaming starts."""
    console.print("[dim]⏳ 思考中...[/dim]", end="\r")


def show_progress_table(progress: dict[str, str]) -> None:
    """Display learning progress as a table."""
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
            "[bold cyan]OpenTeacher 配置向导[/bold cyan]\n\n"
            "我们将配置 LLM API 连接。配置会安全保存在本地。",
            border_style="cyan",
            title="⚙️ Setup",
        )
    )
    console.print()


def provider_selector() -> str:
    """Show provider selection table and return choice."""
    table = Table(title="选择 API Provider")
    table.add_column("#", style="dim", width=4)
    table.add_column("Provider", style="cyan")
    table.add_column("Base URL", style="dim")
    table.add_column("推荐模型", style="green")

    providers = [
        ("1", "OpenAI", "https://api.openai.com/v1", "gpt-4o"),
        ("2", "DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat"),
        ("3", "Anthropic", "https://api.anthropic.com/v1", "claude-sonnet-4-6"),
        ("4", "自定义", "（你自己输入）", "（你自己输入）"),
    ]
    for num, name, url, model in providers:
        table.add_row(num, name, url, model)
    console.print(table)
    return ""
