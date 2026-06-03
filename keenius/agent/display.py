"""使用 Rich 进行终端输出的显示辅助模块。

事件流设计（借鉴 Hermes）：
  ● 你：<消息>              — 用户消息标记
  ┌─ 思考过程 ──┐          — 推理框（dim 样式）
  ┊ 🔧 tool: args          — 工具调用（dim cyan）
  ┊ ✓ result               — 工具结果（dim green）
  ╭─📖 Keenius ──╮         — 回复框（阶段颜色）
  ╰──────────────╯
"""

from __future__ import annotations
from rich.console import Console
from rich.markdown import Markdown
from rich.cells import cell_len
from rich.markup import escape as _escape
from rich.panel import Panel
from rich.table import Table

console = Console(force_terminal=True)  # 强制 ANSI，兼容 Windows GBK


def _wrap_by_width(text: str, max_w: int) -> list[str]:
    """按显示宽度将文本拆成多行（CJK/emoji 算 2 列）。"""
    if not text:
        return [""]
    lines, current, cw = [], "", 0
    for ch in text:
        chw = cell_len(ch)
        if cw + chw > max_w:
            lines.append(current)
            current = ch
            cw = chw
        else:
            current += ch
            cw += chw
    if current:
        lines.append(current)
    return lines or [""]


# ═══════════════════════════════════════════════════════════════════════
# 品牌与阶段颜色
# ═══════════════════════════════════════════════════════════════════════

BRAND = "cyan"
BRAND_HEX = "#00AFAF"

_PHASE_STYLES = {
    "diagnosis": "cyan",
    "planning": "gold1",
    "learning": "green",
    "end": "dim cyan",
}

_PHASE_LABELS = {
    "diagnosis": "🔍 诊断中",
    "planning": "📋 制定计划",
    "learning": "📖 教学中",
    "end": "🏁 总结",
}

# ═══════════════════════════════════════════════════════════════════════
# 启动画面
# ═══════════════════════════════════════════════════════════════════════

_LOGO = r"""
[bold cyan]
  ██╗  ██╗███████╗███████╗███╗   ██╗██╗██╗   ██╗███████╗
  ██║ ██╔╝██╔════╝██╔════╝████╗  ██║██║██║   ██║██╔════╝
  █████╔╝ █████╗  █████╗  ██╔██╗ ██║██║██║   ██║███████╗
  ██╔═██╗ ██╔══╝  ██╔══╝  ██║╚██╗██║██║██║   ██║╚════██║
  ██║  ██╗███████╗███████╗██║ ╚████║██║╚██████╔╝███████║
  ╚═╝  ╚═╝╚══════╝╚══════╝╚═╝  ╚═══╝╚═╝ ╚═════╝ ╚══════╝
[/bold cyan]
[bold]Keen · Genius[/bold]
[dim]敏锐 · 天才[/dim]
"""


def print_splash(version: str = "", model: str = "") -> None:
    """Hermes 风格双面板欢迎界面。"""
    import shutil
    term_w = shutil.get_terminal_size().columns

    console.print(_LOGO)
    console.print()

    if term_w >= 80:
        # 宽屏：并排信息面板
        left = f"[bold {BRAND}]Keenius[/bold {BRAND}]\n"
        left += f"[dim]版本 {version}[/dim]\n"
        left += "[dim]Keen · Genius[/dim]\n\n"
        left += f"模型  [bold]{model}[/bold]\n"
        left += "输入问题开始对话"

        right = f"[dim]斜杠命令[/dim]\n"
        right += f"[{BRAND}]/help[/{BRAND}]   查看帮助\n"
        right += f"[{BRAND}]/setup[/{BRAND}]  配置 API\n"
        right += f"[{BRAND}]/new[/{BRAND}]    新对话\n"
        right += f"[{BRAND}]/plan[/{BRAND}]   学习计划\n"
        right += f"[{BRAND}]/quit[/{BRAND}]   退出\n\n"
        right += "[dim]Tab 补全 · Ctrl+Enter 换行 · Ctrl+D 退出[/dim]"

        from rich.columns import Columns
        console.print(Columns([
            Panel(left, border_style=BRAND, padding=(1, 2)),
            Panel(right, border_style=f"dim {BRAND}", padding=(1, 2)),
        ]))
    else:
        # 窄屏：堆叠
        console.print(Panel.fit(
            f"[bold {BRAND}]Keenius[/bold {BRAND}]  [dim]v{version}[/dim]\n"
            f"模型 [bold]{model}[/bold]  |  /help 查看命令  |  /setup 配置 API",
            border_style=BRAND,
        ))
    console.print()


# ═══════════════════════════════════════════════════════════════════════
# 事件标记 — 核心视觉语言
# ═══════════════════════════════════════════════════════════════════════

def print_user_label(text: str) -> None:
    """Hermes 风格用户消息标记：● 你：<第一行>，其余缩进。"""
    console.print()
    lines = text.split("\n")
    first = _escape(lines[0])
    console.print(f"[bold]● 你：[/bold][dim]{first}[/dim]")
    for line in lines[1:]:
        console.print(f"      [dim]{_escape(line)}[/dim]")


def print_reasoning_box_open() -> None:
    """打开推理/思考标记 — 左侧竖线样式。"""
    console.print()
    console.print("[bold bright_black]● 思考过程[/bold bright_black]")
    console.print("[bright_black]  ╭[/bright_black]")


def print_reasoning_text(text: str) -> None:
    """在推理标记中打印推理内容，手动换行避免终端截断。"""
    max_w = console.width - 6
    for line in text.split("\n"):
        if not line.strip():
            console.print("[bright_black]  │[/bright_black]")
            continue
        for chunk in _wrap_by_width(line, max_w):
            console.print(f"[bright_black]  │[/bright_black]  [dim italic]{_escape(chunk)}[/dim italic]")


def print_reasoning_box_close() -> None:
    """关闭推理标记。"""
    console.print("[bright_black]  ╰[/bright_black]")


def print_tool_call(name: str, preview: str = "") -> None:
    """工具调用标记：┊ ● name: preview。"""
    if preview:
        console.print(f"  [dim cyan]┊[/dim cyan] [dim]● {_escape(name)}:[/dim] [dim cyan]{_escape(preview[:80])}[/dim cyan]")
    else:
        console.print(f"  [dim cyan]┊[/dim cyan] [dim]● {_escape(name)}[/dim]")


def print_tool_result(preview: str = "", success: bool = True) -> None:
    """工具结果标记：┊ ✓ result（绿色）或 ┊ ✗ error（红色）。"""
    short = _escape(preview.replace("\n", " ")[:100])
    if success:
        console.print(f"  [dim green]┊ ✓[/dim green] [dim]{short}[/dim]")
    else:
        console.print(f"  [dim red]┊ ✗[/dim red] [dim]{short}[/dim]")


# 统一的回复标签 — 类似于 Hermes 的 "⚕ Hermes"
_RESPONSE_LABEL = "Keenius"


def prepare_markdown(text: str) -> str:
    """预处理 LLM 输出，使 Rich Markdown 能够正确渲染。

    Rich Markdown 不原生支持 LaTeX 数学公式。将 $...$ 和
    $$...$$ 块着色，使其作为数学公式高亮显示。
    """
    import re as _re

    # 先着色块级公式 $$...$$（更长的匹配）
    text = _re.sub(
        r'\$\$(.+?)\$\$',
        r'[dim cyan]$$\1$$[/dim cyan]',
        text, flags=_re.DOTALL,
    )
    # 再着色行内公式 $...$
    text = _re.sub(
        r'(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)',
        r'[dim cyan]$\1$[/dim cyan]',
        text,
    )
    return text


def print_response_box_open(phase: str = "") -> None:
    """打开流式回复框 — Hermes 风格 ╭─ Keenius ──╮。"""
    style = _PHASE_STYLES.get(phase, "dim")
    import shutil
    w = max(shutil.get_terminal_size().columns - 4, 40)
    fill = w - 5 - cell_len(_RESPONSE_LABEL)  # ╭─, ` `, ─╮ = 5 overhead chars; cell_len for CJK
    console.print()
    console.print(
        f"[{style}]╭─ {_RESPONSE_LABEL} [/][{style}]" + "─" * max(fill, 10) + f"╮[/{style}]"
    )


def print_response_box_close(phase: str = "") -> None:
    """关闭流式回复框 — Hermes 风格 ╰──────────╯。"""
    style = _PHASE_STYLES.get(phase, "dim")
    import shutil
    w = max(shutil.get_terminal_size().columns - 4, 40)
    console.print(f"[{style}]╰[/{style}]" + f"[{style}]─[/{style}]" * (w - 2) + f"[{style}]╯[/{style}]")
    console.print()


def print_response_panel(content: str, phase: str = "") -> None:
    """使用 Hermes ROUNDED Panel + Rich Markdown 渲染 AI 回复。

    使用 box=ROUNDED（╭╮╰╯ 角）和阶段颜色的 dim 边框。
    与选择器区分：选择器使用 HEAVY（┏┓┗┛）+ bright cyan。
    """
    from rich.panel import Panel
    from rich.markdown import Markdown
    from rich.box import ROUNDED
    import shutil

    style = _PHASE_STYLES.get(phase, "dim")
    w = max(shutil.get_terminal_size().columns - 4, 40)

    processed = prepare_markdown(content)
    try:
        body = Markdown(processed)
    except Exception:
        body = processed

    console.print()
    console.print(Panel(
        body,
        box=ROUNDED,
        border_style=style,
        title=f"[{style}]{_RESPONSE_LABEL}[/{style}]",
        title_align="left",
        padding=(1, 4),
        width=w,
    ))
    console.print()


# ═══════════════════════════════════════════════════════════════════════
# 内容显示
# ═══════════════════════════════════════════════════════════════════════

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


def print_system_notice(text: str) -> None:
    console.print()
    console.print(Panel.fit(
        f"[dim yellow]⚡ {text}[/dim yellow]",
        border_style="dim yellow",
        padding=(0, 1),
    ))


def print_phase_banner(phase: str) -> None:
    label = _PHASE_LABELS.get(phase, "💬")
    color = _PHASE_STYLES.get(phase, "dim")
    console.print(f"[{color}]  {label}[/{color}]")


# ═══════════════════════════════════════════════════════════════════════
# 向后兼容的别名（供尚未迁移的代码使用）
# ═══════════════════════════════════════════════════════════════════════

print_assistant_header = print_response_box_open
print_assistant_separator = print_response_box_open
print_thinking_separator = print_reasoning_box_open
print_tool_separator = lambda: None  # 工具事件现在使用独立标记
print_user_separator = lambda: console.print()
print_logo = lambda **kw: print_splash(**kw)
print_welcome = lambda: None  # 现在是 splash 的一部分


def print_tool_call_legacy(tool_name: str, tool_args: dict) -> None:
    """旧版工具调用显示 — 在流式传输期间尚未完全迁移时使用。"""
    preview = ""
    for v in tool_args.values():
        s = str(v)
        if len(s) > 50:
            s = s[:50] + "..."
        preview = s
        break
    print_tool_call(tool_name, preview)


def print_tool_result_legacy(result: str) -> None:
    short = result.replace("\n", " ")[:80]
    print_tool_result(short)


# ═══════════════════════════════════════════════════════════════════════
# 面板与其他显示
# ═══════════════════════════════════════════════════════════════════════

def show_progress_table(progress: dict[str, str]) -> None:
    table = Table(title="📊 学习进度")
    table.add_column("概念", style="cyan")
    table.add_column("状态", style="green")
    for concept, status in progress.items():
        table.add_row(concept, status)
    console.print(table)


def print_setup_banner() -> None:
    console.print()
    console.print(Panel.fit(
        "配置 LLM API 连接。数据安全保存在本地。",
        border_style=BRAND,
        title="[bold]⚙️ 配置向导[/bold]",
    ))
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
