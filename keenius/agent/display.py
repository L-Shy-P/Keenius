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


# ═══════════════════════════════════════════════════════
# ANSI 颜色常量（用于 _cprint 安全输出路径）
# ═══════════════════════════════════════════════════════

A_RESET = "\033[0m"
A_BOLD = "\033[1m"
A_DIM = "\033[2m"
A_ITALIC = "\033[3m"
A_CYAN = "\033[36m"
A_GREEN = "\033[32m"
A_YELLOW = "\033[33m"
A_RED = "\033[31m"
A_GRAY = "\033[90m"
A_CYAN_BOLD = "\033[1;36m"
A_GREEN_BOLD = "\033[1;32m"
A_DIM_ITALIC = "\033[2;3m"


def _display_width(text: str) -> int:
    return cell_len(text)


def _clip(text: str, width: int) -> str:
    """按显示宽度截断文本。"""
    if not text:
        return ""
    text = text.replace("\n", " ")
    if _display_width(text) <= width:
        return text
    result = []
    cur = 0
    for ch in text:
        cw = cell_len(ch)
        if cur + cw > width:
            break
        result.append(ch)
        cur += cw
    return "".join(result)


def _pad(text: str, width: int) -> str:
    """填充文本到指定显示宽度。"""
    dw = _display_width(text)
    if dw >= width:
        return _clip(text, width)
    return text + " " * (width - dw)


# ── fmt_* 函数：返回 ANSI 格式化字符串（供 _cprint 使用）──

def fmt_user_msg(text: str) -> list[str]:
    """用户消息行。"""
    lines = text.split("\n")
    result = [f"\n{A_CYAN_BOLD}● 你：{A_RESET}{A_GRAY}{lines[0]}{A_RESET}"]
    for line in lines[1:]:
        result.append(f"      {A_GRAY}{line}{A_RESET}")
    return result


def fmt_box_open() -> str:
    """回复框头 ╭─ Keenius ──╮。"""
    import shutil
    w = max(shutil.get_terminal_size().columns - 4, 40)
    fill = w - 12  # ╭(1) + ─(1) + space(1) + Keenius(7) + space(1) + fill + ─... + ┐(1) = w
    return f"{A_CYAN}╭─ Keenius {'─' * max(fill, 4)}╮{A_RESET}"


def fmt_box_line(line: str) -> str:
    """回复框内容行（带右边框）。"""
    import shutil
    w = max(shutil.get_terminal_size().columns - 4, 40)
    inner_w = w - 4  # │(1) + 2空格 + 内容 + 1空格 + │(1) 不对，应该是 w-4
    # │ + space + content(padded to w-4) + space + │ = w
    return f"{A_CYAN}│{A_RESET} {_pad(line, w - 4)} {A_CYAN}│{A_RESET}"


def fmt_box_close() -> list[str]:
    """回复框尾 ╰──────╯ + 空行。"""
    import shutil
    w = max(shutil.get_terminal_size().columns - 4, 40)
    return [f"{A_CYAN}╰{'─' * (w - 2)}╯{A_RESET}", ""]


def fmt_error(msg: str) -> list[str]:
    """错误消息。"""
    return [f"\n{A_RED}✗ {msg}{A_RESET}"]


def fmt_static_picker(options: list, question: str = "",
                      cursor: int = 0, checked: set | None = None) -> list[str]:
    """静态选择器（灰色文本）。返回行列表。"""
    import shutil
    checked = checked or set()
    w = max(shutil.get_terminal_size().columns - 8, 40)

    lines: list[str] = []
    lines.append(f"{A_GRAY}┏━━ 请选择 {'━' * max(w - 8, 10)}┓{A_RESET}")
    if question:
        lines.append(f"{A_GRAY}┃{A_RESET} {A_DIM}{_pad(question, w)}{A_RESET} {A_GRAY}┃{A_RESET}")
        lines.append(f"{A_GRAY}┃{A_RESET} {A_DIM}{'─' * w}{A_RESET} {A_GRAY}┃{A_RESET}")
    for i, opt in enumerate(options):
        if opt.get("separator"):
            line = _clip(f"  ── {opt['text']}", w)
            lines.append(f"{A_GRAY}┃{A_RESET} {A_DIM_ITALIC}{_pad(line, w)}{A_RESET} {A_GRAY}┃{A_RESET}")
            continue
        selected = i in checked or i == cursor
        chk = "✓" if selected else " "
        txt = _clip(opt["text"], w - 8)
        content = f"  [{chk}] [{opt['num']}] {txt}"
        if selected:
            lines.append(f"{A_GRAY}┃{A_RESET} {A_GREEN_BOLD}{_pad(content, w)}{A_RESET} {A_GRAY}┃{A_RESET}")
        else:
            lines.append(f"{A_GRAY}┃{A_RESET} {A_DIM}{_pad(content, w)}{A_RESET} {A_GRAY}┃{A_RESET}")
    lines.append(f"{A_GRAY}┗{'━' * (w + 2)}┛{A_RESET}")
    lines.append("")
    return lines


# ═══════════════════════════════════════════════════════
# PickerRenderer — 统一选择器渲染器
# ═══════════════════════════════════════════════════════

class PickerRenderer:
    """统一的选择器渲染器。

    所有 picker 场景（单选、多选、多问题、输入框）共用此类，
    通过调整参数适配不同需求。样式集中管理，修改一处即全局生效。
    """

    # ── 样式常量（prompt_toolkit 格式）──
    S_NORMAL = "fg:ansicyan bold"
    S_MULTI = "fg:ansiblue bold"
    S_EDIT = "fg:ansiyellow"
    S_DIM = "fg:gray"
    S_GREEN = "bold fg:ansigreen"
    S_REVERSE = "reverse"

    # ── 中文提示 ──
    HINT_SINGLE = "↑↓选择  Enter确认  Esc取消"
    HINT_MULTI = "↑↓选择  Space切换多选  Enter确认  Esc取消"
    HINT_EDIT = "编辑中  Enter确认  Esc取消"
    HINT_MULTI_Q = "← →切换问题  ↑↓选择  Space确认  Enter提交  Esc取消"
    HINT_PLACEHOLDER = "▸ 在此输入补充文字..."

    @staticmethod
    def _box_width() -> int:
        """框宽度（显示列数）。"""
        import shutil
        return max(shutil.get_terminal_size().columns - 6, 50)

    @classmethod
    def _border_color(cls, editing: bool, is_multi: bool) -> str:
        if editing:
            return cls.S_EDIT
        if is_multi:
            return cls.S_MULTI
        return cls.S_NORMAL

    @classmethod
    def _header(cls, bc: str, title: str, w: int,
                out: list[tuple[str, str]]):
        """绘制框头 ┏━━ title ━━━┓。"""
        out.append((bc, "┏━━ "))
        out.append((bc, f"{title} "))
        out.append((bc, "━" * max(w - 2 - _display_width(title), 2)))
        out.append((bc, "┓\n"))

    @classmethod
    def _footer(cls, bc: str, w: int, out: list[tuple[str, str]]):
        """绘制框尾 ┗━━━━┛。"""
        out.append((bc, "┗"))
        out.append((bc, "━" * (w + 2)))
        out.append((bc, "┛\n"))

    @classmethod
    def _row(cls, bc: str, inner: str, w: int, style: str,
             out: list[tuple[str, str]]):
        """绘制一行：┃ <content padded to w> ┃。"""
        out.append((bc, "┃ "))
        out.append((style, _pad(inner, w)))
        out.append((bc, " ┃"))
        out.append(("", "\n"))

    @classmethod
    def _separator_row(cls, bc: str, text: str, w: int,
                       out: list[tuple[str, str]]):
        """绘制分隔线行。"""
        cls._row(bc, _clip(f"── {text}", w), w, "fg:gray italic", out)

    @classmethod
    def _option_row(cls, bc: str, num: str, text: str, w: int,
                    is_cursor: bool, is_checked: bool, is_editing: bool,
                    edit_text: str, out: list[tuple[str, str]]):
        """绘制一个选项行。"""
        chk = "✓" if is_checked else " "
        if is_editing and is_cursor:
            et = _clip(edit_text, w - 10)
            content = _clip(f" ✎ [{num}] {et}", w)
            cls._row(bc, content, w, cls.S_REVERSE, out)
        elif is_cursor:
            content = _clip(f" [{chk}] [{num}] {text}", w)
            cls._row(bc, content, w, cls.S_REVERSE, out)
        else:
            dm = "✓" if is_checked else " "
            content = _clip(f"  [{dm}] [{num}] {text}", w)
            cls._row(bc, content, w, cls.S_DIM, out)

    # ── 公共渲染方法 ──

    @classmethod
    def render_single(cls, options: list[dict], cursor: int = 0,
                      checked: set | None = None,
                      editing: bool = False, is_multi: bool = False,
                      edit_text: str = "") -> list[tuple[str, str]]:
        """渲染单问题选择器（prompt_toolkit FormattedText）。"""
        checked = checked or set()
        w = cls._box_width()
        bc = cls._border_color(editing, is_multi)
        title = "编辑选项" if editing else ("请选择（可多选）" if is_multi else "请选择")
        f: list[tuple[str, str]] = []
        cls._header(bc, title, w, f)
        for i, opt in enumerate(options):
            if opt.get("separator"):
                cls._separator_row(bc, opt["text"], w, f)
                continue
            cls._option_row(bc, opt["num"], opt["text"], w,
                            i == cursor, i in checked,
                            editing and i == cursor, edit_text, f)
        if checked:
            cls._row(bc, _clip(f" 已选 {len(checked)} 项", w), w, cls.S_GREEN, f)
        hint = cls.HINT_EDIT if editing else (cls.HINT_MULTI if is_multi else cls.HINT_SINGLE)
        cls._row(bc, hint, w, cls.S_DIM, f)
        cls._footer(bc, w, f)
        f.append(("", "\n"))
        return f

    @classmethod
    def render_multi_q(cls, questions: list[dict], q_idx: int = 0,
                       o_idx: list[int] | None = None,
                       selected: list[int | None] | None = None) -> list[tuple[str, str]]:
        """渲染多问题选择器（带统一框）。"""
        w = cls._box_width()
        bc = cls.S_NORMAL
        f: list[tuple[str, str]] = []

        cls._header(bc, "请选择", w, f)
        for qi, q in enumerate(questions):
            focus = qi == q_idx
            prefix = f"Q{qi+1}/{len(questions)}: "
            title_max = w - _display_width(prefix) - 2
            q_style = "bold fg:ansicyan" if focus else "fg:gray"
            cls._row(bc, f"{prefix}{_clip(q.get('text', ''), title_max)}",
                     w, q_style, f)
            for oi, opt in enumerate(q.get("options", [])):
                cur = (o_idx and oi == o_idx[qi])
                sel = (selected and selected[qi] == oi)
                txt = _clip(opt["text"], w - 8)
                if focus and cur:
                    cls._row(bc, f" ▶ [{opt['num']}] {txt}", w, cls.S_REVERSE, f)
                elif sel:
                    cls._row(bc, f"   ✓ [{opt['num']}] {txt}", w, cls.S_GREEN, f)
                else:
                    cls._row(bc, f"     [{opt['num']}] {txt}", w, cls.S_DIM, f)
            if qi < len(questions) - 1:
                cls._row(bc, "─" * w, w, "fg:gray italic", f)
        # 状态行
        if selected:
            unanswered = [i + 1 for i, s in enumerate(selected) if s is None]
            if unanswered:
                cls._row(bc, _clip(f"⚠ 第 {unanswered} 题未选", w), w, "fg:ansiyellow", f)
            else:
                cls._row(bc, "全部已答 — Enter 确认", w, cls.S_GREEN, f)
        cls._row(bc, cls.HINT_MULTI_Q, w, cls.S_DIM, f)
        cls._footer(bc, w, f)
        f.append(("", "\n"))
        return f

    @classmethod
    def render_input(cls, edit_text: str = "", editing: bool = False) -> list[tuple[str, str]]:
        """渲染输入框。"""
        w = cls._box_width()
        bc = "fg:ansicyan bold" if editing else "fg:gray"
        f: list[tuple[str, str]] = []
        cls._header(bc, "输入", w, f)
        if editing:
            cls._row(bc, _clip(f" ▸ {edit_text} ▌", w), w, "fg:white bold", f)
        else:
            cls._row(bc, cls.HINT_PLACEHOLDER, w, "fg:gray", f)
        cls._footer(bc, w, f)
        f.append(("", "\n"))
        return f


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


class ReasoningRenderer:
    """统一的思考/推理渲染器。

    提供 Rich 终端输出和 prompt_toolkit FormattedText 两种格式，
    确保所有地方的思考样式完全一致。
    """

    # Rich 样式
    _R_CLR = "bright_black"
    _R_TXT = "bright_black italic"
    # prompt_toolkit 样式（不支持 bright_black，用 ansibrightblack）
    _P_CLR = "ansibrightblack"
    _P_TXT = "gray italic"

    @classmethod
    def _prefix_rich(cls, symbol: str) -> str:
        return f"[{cls._R_CLR}]{symbol}[/{cls._R_CLR}]"

    @classmethod
    def _line_rich(cls, prefix: str, text: str) -> str:
        return f"[{cls._R_CLR}]{prefix}[/{cls._R_CLR}]  [{cls._R_TXT}]{_escape(text)}[/{cls._R_TXT}]"

    # ── Rich 终端输出 ──

    @classmethod
    def rich_open(cls) -> None:
        console.print()
        console.print(f"[bold {cls._R_CLR}]● 思考过程[/bold {cls._R_CLR}]")
        console.print(cls._prefix_rich("  ╭"))

    @classmethod
    def rich_text(cls, text: str) -> None:
        max_w = console.width - 6
        for line in text.split("\n"):
            if not line.strip():
                console.print(cls._prefix_rich("  │"))
                continue
            for chunk in _wrap_by_width(line, max_w):
                console.print(cls._line_rich("  │", chunk))

    @classmethod
    def rich_close(cls) -> None:
        console.print(cls._prefix_rich("  ╰"))

    @classmethod
    def rich_thinking(cls) -> None:
        """Rich 格式的思考中指示器。"""
        console.print()
        console.print(f"[bold {cls._R_CLR}]●[/bold {cls._R_CLR}] [{cls._R_TXT}]思考中...[/{cls._R_TXT}]")

    # ── prompt_toolkit FormattedText 输出 ──

    @classmethod
    def pt_open(cls) -> list[tuple[str, str]]:
        r: list[tuple[str, str]] = [("", "\n")]
        r.append((f"fg:{cls._P_CLR} bold", "  ● 思考过程\n"))
        r.append((f"fg:{cls._P_CLR}", "  ╭\n"))
        return r

    @classmethod
    def pt_text(cls, text: str, max_w: int) -> list[tuple[str, str]]:
        r: list[tuple[str, str]] = []
        for line in text.split("\n"):
            if not line.strip():
                r.append((f"fg:{cls._P_CLR}", "  │\n"))
                continue
            for chunk in _wrap_by_width(line, max_w):
                r.append((f"fg:{cls._P_CLR}", "  │  "))
                r.append((f"fg:{cls._P_TXT}", chunk))
                r.append(("", "\n"))
        return r

    @classmethod
    def pt_close(cls) -> list[tuple[str, str]]:
        return [(f"fg:{cls._P_CLR}", "  ╰\n")]

    @classmethod
    def pt_thinking(cls) -> list[tuple[str, str]]:
        """prompt_toolkit 格式的思考中指示器。"""
        from prompt_toolkit.formatted_text import FormattedText
        return FormattedText([
            ("", "\n"),
            (f"fg:{cls._P_CLR} bold", "  ● "),
            (f"fg:{cls._P_TXT}", "思考中...\n"),
        ])

    @classmethod
    def pt_full(cls, text: str, max_w: int) -> list[tuple[str, str]]:
        """完整的推理块（open + text + close）。"""
        r = cls.pt_open()
        r.extend(cls.pt_text(text, max_w))
        r.extend(cls.pt_close())
        return r

    # ── ANSI 字符串输出（供 _cprint 安全输出路径）──

    @classmethod
    def ansi_title(cls) -> str:
        """推理标题。"""
        return f"\n{A_GRAY}{A_BOLD}● 思考过程{A_RESET}"

    @classmethod
    def ansi_open(cls) -> str:
        """推理框开头 ╭。"""
        return f"{A_GRAY}  ╭{A_RESET}"

    @classmethod
    def ansi_line(cls, line: str) -> list[str]:
        """推理内容行（自动换行）。"""
        import shutil
        term_w = max(shutil.get_terminal_size().columns - 6, 40)
        prefix = "  │  "
        prefix_w = _display_width(prefix)
        max_content_w = term_w - prefix_w
        lines = _wrap_by_width(line, max_content_w) if _display_width(line) > max_content_w else [line]
        return [f"{A_GRAY}{A_ITALIC}{prefix}{l}{A_RESET}" for l in lines]

    @classmethod
    def ansi_close(cls) -> str:
        """推理框结尾 ╰。"""
        return f"{A_GRAY}  ╰{A_RESET}"


# 兼容别名（逐步迁移）
fmt_reasoning_title = ReasoningRenderer.ansi_title
fmt_reasoning_open = ReasoningRenderer.ansi_open
fmt_reasoning_line = ReasoningRenderer.ansi_line
fmt_reasoning_close = ReasoningRenderer.ansi_close


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
    """打开推理/思考标记。"""
    ReasoningRenderer.rich_open()

def print_reasoning_text(text: str) -> None:
    """打印推理内容。"""
    ReasoningRenderer.rich_text(text)

def print_reasoning_box_close() -> None:
    """关闭推理标记。"""
    ReasoningRenderer.rich_close()


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


def print_stream_line(line: str) -> None:
    """打印流式回复的一行（带 2 空格缩进）。"""
    console.print(f"  {line}")


def print_static_picker(options: list[dict], question: str = "",
                        cursor: int = 0, checked: set | None = None) -> None:
    """将旧 picker 打印为灰色静态文本到终端 scrollback。"""
    import shutil
    checked = checked or set()
    w = max(shutil.get_terminal_size().columns - 8, 40)
    console.print()
    console.print(f"[dim]┏━━ 请选择 {'━' * (w - 2)}┓[/]")
    if question:
        console.print(f"[dim]┃[/] [dim]{question[:w]}[/]")
        console.print(f"[dim]┃[/] [dim]{'─' * w}[/]")
    for i, opt in enumerate(options):
        if opt.get("separator"):
            console.print(f"[dim]┃[/] [dim italic]  ── {opt['text'][:w-4]}[/]")
            continue
        selected = i in checked or i == cursor
        chk = "✓" if selected else " "
        txt = opt["text"][:w-6]
        if selected:
            console.print(f"[dim]┃[/] [dim green bold]  [{chk}] [{opt['num']}] {txt}[/]")
        else:
            console.print(f"[dim]┃[/] [dim]  [{chk}] [{opt['num']}] {txt}[/]")
    console.print(f"[dim]┗{'━' * (w + 2)}┛[/]")
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
