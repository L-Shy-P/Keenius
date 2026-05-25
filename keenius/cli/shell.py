"""基于 prompt-toolkit 的交互式 REPL shell。

这是主要的用户界面 — 与 Keenius 的富终端聊天界面。
"""

from __future__ import annotations
from prompt_toolkit import PromptSession
from prompt_toolkit.input.defaults import create_input
from prompt_toolkit.styles import Style
from rich.markup import escape as _e
from prompt_toolkit.history import FileHistory
from prompt_toolkit.completion import Completer, Completion
import re
import unicodedata
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.document import Document

from keenius.agent.display import (
    console,
    print_error,
    print_info,
)
from keenius.agent.loop import ConversationLoop
from keenius.config import PROGRESS_FILE, HISTORY_FILE

# ── 工具栏辅助：去除 Rich 标记（prompt_toolkit 仅支持纯文本） ─

def _plain(text: str) -> str:
    """去除 Rich 标记标签，供 prompt_toolkit 底部工具栏使用。"""
    return re.sub(r"\[/?\w+\]|\[/?\w+ [^\]]*\]", "", text)


def _md_to_rich(text: str) -> str:
    """将 LLM 输出的 Markdown 内联格式 + LaTeX 数学转换为 Rich 标记。

    处理顺序：先转义已有 [、再着色数学公式、再转换 Markdown。
    """
    # 1. 转义原文本中的 [ 防止被误解析为 Rich 标签
    text = text.replace("[", "\\[")

    # 2. 块级数学 $$...$$（先匹配更长的）
    text = re.sub(r"\$\$(.+?)\$\$", r"[dim cyan]$$\1$$[/dim cyan]", text, flags=re.DOTALL)

    # 3. 行内数学 $...$
    text = re.sub(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", r"[dim cyan]$\1$[/dim cyan]", text)

    # 4. 粗体 **...**
    text = re.sub(r"\*\*(.+?)\*\*", r"[bold]\1[/bold]", text)

    # 5. 斜体 *...*（单星号，不匹配 **）
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"[italic]\1[/italic]", text)

    # 6. 行内代码 `...`
    text = re.sub(r"`(.+?)`", r"[dim cyan]\1[/dim cyan]", text)

    return text


def _visual_width(text: str) -> int:
    """计算去除 Rich 标记后的终端列宽。参照 Claude Code eastAsianWidth(ambiguousAsWide=false)。"""
    # 去除 Rich 标记 [...]，保留 [N] 数字选项
    plain = re.sub(r"\[(?!\d+\])[^\]]*\]", "", text)
    # 去除 _md_to_rich 产生的转义反斜杠
    plain = plain.replace("\\[", "[")
    w = 0
    for ch in plain:
        ea = unicodedata.east_asian_width(ch)
        if ea in ('W', 'F'):
            w += 2
        elif ea in ('Na', 'H', 'N', 'A'):
            w += 1
        else:
            w += 1
    return w


class _PickerDisplay:
    """原地刷新：首次清屏，后续计算行数上移覆盖。"""

    def __init__(self):
        self._active = False
        self._lines = 0
        self._first = True

    def start(self, renderable=None):
        self._active = True
        self._lines = 0
        self._first = True
        if renderable is not None:
            self.update(renderable)

    def stop(self):
        self._active = False

    def update(self, renderable, lines=0, cursor_up=0, cursor_right=0):
        """lines: renderable 行数（含 console.print 尾换行），0=回退清屏"""
        if not self._active:
            return
        if lines <= 0:
            # 回退模式：每次全清屏
            console.clear()
        elif self._first:
            console.clear()
            self._first = False
            self._lines = lines
        else:
            # 上移覆盖上次区域
            console.file.write(f"\033[{self._lines}A\033[J")
            self._lines = lines
        console.print(renderable)
        if cursor_up:
            console.file.write(f"\033[{cursor_up}A")
            if cursor_right:
                console.file.write(f"\033[{cursor_right}C")
        console.file.flush()


# ── 斜杠命令注册表 ────────────────────────────────────────────

SLASH_COMMANDS: dict[str, dict] = {
    "session": {
        "/new":     ("开始新对话（重置上下文）", lambda ctx: ctx.get("loop").reset() or "对话已重置。输入问题开始吧！"),
        "/save":    ("保存当前会话 /save [名称]", lambda ctx, a: _cmd_save(ctx, a), True),
        "/load":    ("加载历史会话 /load <名称>", lambda ctx, a: _cmd_load(ctx, a), True),
        "/rename":  ("重命名当前会话 /rename <新名称>", lambda ctx, a: _cmd_rename(ctx, a), True),
        "/sessions": ("列出所有已保存的会话", lambda ctx: _cmd_list_sessions()),
        "/picker":   ("重新打开会话选择界面", lambda ctx: _cmd_reopen_picker(ctx)),
        "/subject": ("切换学习主题 /subject <主题>", lambda ctx, a: setattr(ctx["loop"], "subject", a) or f"主题已切换为: {a}", True),
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
        "/quit": ("退出 Keenius", lambda _: "EXIT"),
        "/q":    ("退出（别名）", lambda _: "EXIT"),
    },
}

_all_flat: dict[str, dict] = {}
for _cmds in SLASH_COMMANDS.values():
    _all_flat.update(_cmds)


# ── 斜杠命令补全器 ──────────────────────────────────────

class SlashCompleter(Completer):
    def get_completions(self, document: Document, complete_event):
        text = document.text_before_cursor.lstrip()
        if not text.startswith("/"):
            return

        # 补全命令名称
        if " " not in text:
            partial = text
            for cmd, (desc, *_rest) in _all_flat.items():
                if cmd.startswith(partial):
                    yield Completion(cmd, start_position=-len(partial), display_meta=desc)
        # 补全子命令参数
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


# ── REPL 按键绑定 ─────────────────────────────────────────────

repl_bindings = KeyBindings()


@repl_bindings.add("c-d")
def _(event):
    event.app.exit(result="EXIT")


@repl_bindings.add("c-c")
def _(event):
    event.app.exit(result="INTERRUPT")


@repl_bindings.add("escape", "enter")
def _(event):
    """Alt+Enter / Ctrl+Enter 插入换行。"""
    event.app.current_buffer.insert_text("\n")


# ── 标准选择器按键绑定（Tab=循环, Up/Down=选择, Enter=确认） ─

def _picker_kb(idx_ref: list, count: int, on_select, on_cancel=None):
    """构建列表选择器的标准按键绑定。
    idx_ref: 可变列表 [current_index]
    count: 项目总数
    on_select: 回调函数，接收索引
    on_cancel: 回调函数或 None
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


# ── 错误处理 ────────────────────────────────────────────────────

def _handle_startup_error(err: Exception) -> None:
    msg = str(err)
    from keenius.config import get_api_key

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


# ── 配置向导 ──────────────────────────────────────────────────────

def run_setup_wizard() -> str:
    from keenius import config
    from keenius.agent.display import (
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

    # 键盘驱动的 provider 选择
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
    """键盘驱动的 provider 选择。"""
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
    ps = PS(key_bindings=kb, bottom_toolbar=_toolbar, style=CHAT_STYLE, input=create_input(), wrap_lines=False, enable_system_prompt=False)
    try:
        return ps.prompt("")
    except (EOFError, KeyboardInterrupt):
        return None


# ── 显示配置 ───────────────────────────────────────────────────────

def show_config() -> str:
    from keenius import config
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
    from keenius.config import PROFILES_DIR

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

    # 概念层级
    concept_levels = data.get("concept_levels", {})
    if concept_levels:
        lines.append("\n  [bold]📚 概念掌握度 (C 轴)[/bold]")
        for name, info in sorted(concept_levels.items()):
            ev = f" — {info.get('evidence', '')}" if info.get("evidence") else ""
            lines.append(f"    {info['level']}  {name}{ev}")

    # 技能层级
    skill_levels = data.get("skill_levels", {})
    if skill_levels:
        lines.append("\n  [bold]🛠️ 应用/执行能力 (S 轴)[/bold]")
        for name, info in sorted(skill_levels.items()):
            ev = f" — {info.get('evidence', '')}" if info.get("evidence") else ""
            lines.append(f"    {info['level']}  {name}{ev}")

    if not concept_levels and not skill_levels:
        lines.append("  [dim]尚未评估具体知识维度[/dim]")

    # 认知 / 性格特征
    cognitive_fields = {
        "memory_style": "🧠 记忆模式",
        "cognitive_strength": "💡 认知优势",
        "grasp_speed": "⚡ 理解速度",
        "discipline": "🎯 自律程度",
    }
    for field, label in cognitive_fields.items():
        if data.get(field):
            lines.append(f"  {label}: {data[field]}")

    # 备注
    notes = data.get("cognitive_notes", {})
    if notes:
        for field, info in notes.items():
            if info.get("evidence"):
                lines.append(f"    [dim]依据: {info['evidence']}[/dim]")

    lines.append(f"\n[dim]数据文件: {pf}[/dim]")
    return "\n".join(lines)


def show_plan() -> str:
    from keenius.tutor.planner import list_subjects, scan_tree
    subjects = list_subjects()
    if not subjects:
        return "暂无学习计划。开始学习后 Agent 会自动创建。"
    # 显示第一个学科（未来可让用户选择）
    subject = subjects[0]
    tree = scan_tree(subject)
    return _view_curriculum_hierarchy({"subject": subject, "sections": tree})


# ═══════════════════════════════════════════════════════════════════════════
# 层级式课程大纲查看器
# ═══════════════════════════════════════════════════════════════════════════

def _plan_to_tree(plan: dict) -> list[dict]:
    """将 plan 字典转换为层级树：科目→部分→单元→课程→课程内容。

    支持层级式（sections[].units[].lessons[]）和扁平式（lessons[]）计划。
    """
    tree = []
    if "sections" in plan:
        for sec in plan["sections"]:
            snode = {"title": sec.get("title", ""), "type": "section", "data": sec, "children": []}
            for unit in sec.get("units", []):
                unode = {"title": unit.get("title", ""), "type": "unit", "data": unit, "children": []}
                for les in unit.get("lessons", []):
                    unode["children"].append(_lesson_node(les))
                snode["children"].append(unode)
            tree.append(snode)
    elif "lessons" in plan and plan["lessons"]:
        children = [_lesson_node(l) for l in plan["lessons"]]
        tree.append({"title": "全部课程", "type": "section", "data": plan, "children": children})
    return tree


def _lesson_node(lesson: dict) -> dict:
    status = lesson.get("status", "pending")
    icon = {"completed": "✅", "in_progress": "🔄", "pending": "⏳", "skipped": "⏭️"}.get(status, "⏳")
    # 课程内容作为子节点
    content_children = []
    sections_data = lesson.get("sections", {})
    if sections_data:
        for key, label in [("definition", "定义原文"), ("intuitive", "直观解释"),
                           ("examples", "方法典例"), ("quiz", "当堂测试"), ("extension", "拓展内容")]:
            val = sections_data.get(key, "")
            if val:
                preview = (val if isinstance(val, str) else str(val))[:60]
                content_children.append({"title": f"{label}: {preview}", "type": "content",
                                         "data": val, "children": []})
    return {"title": lesson.get("title", ""), "type": "lesson", "data": lesson,
            "status": status, "icon": icon, "id": lesson.get("id", 0),
            "children": content_children}


def _view_curriculum_hierarchy(plan: dict) -> str:
    """交互式层级课程浏览器。

    ↑↓     当前层级导航
    →/Enter 进入选中项
    ←      返回父级
    Space   内联编辑选中项标题
    `       附加备注
    Esc     退出
    """
    import msvcrt
    import builtins
    from rich.panel import Panel
    from rich.box import ROUNDED

    tree = _plan_to_tree(plan)
    if not tree:
        return "暂无课程内容。"

    nav_stack: list[tuple[list[dict], str]] = [(tree, plan.get("subject", "教学大纲"))]
    idx = 0
    result_msg = ""
    editing = False
    edit_buf = ""
    delete_pending = -1  # index of item pending deletion (-1 = none)
    multi_select: set[int] = set()  # indices of +-selected items

    def _current_level() -> tuple[list[dict], str]:
        return nav_stack[-1]

    def _drill_into(node: dict) -> bool:
        children = node.get("children", [])
        if children:
            nav_stack.append((children, node.get("title", "")))
            return True
        return False

    def _drill_out() -> bool:
        if len(nav_stack) > 1:
            nav_stack.pop()
            return True
        return False

    def _render():
        nonlocal idx
        items, _ = _current_level()
        count = len(items)
        if count == 0:
            return Panel("[dim](空)[/dim]", box=ROUNDED, border_style="dim")

        idx = max(0, min(idx, count - 1)) if count else 0

        depth = len(nav_stack)
        lines = []
        crumbs = " → ".join(f"[dim]{t}[/dim]" for _, t in nav_stack)
        lines.append(f"[bold]📋 {crumbs}[/bold]")
        lines.append("[dim]" + "─" * 60 + "[/dim]")

        for i in range(count):
            node = items[i]
            icon = node.get("icon", "")
            title = node.get("title", "")[:70]
            node_type = node.get("type", "")
            has_kids = bool(node.get("children"))
            arrow = " ▶" if has_kids else "  "

            # 状态标签
            status_tag = ""
            if node_type == "lesson":
                st = node.get("status", "")
                color = {"completed": "dim green", "in_progress": "bold cyan",
                         "pending": "dim", "skipped": "dim yellow"}.get(st, "dim")
                status_tag = f"[{color}]({st})[/{color}]"
            elif node_type == "content":
                status_tag = "[dim]📄[/dim]"

            # 多选标记
            ms_mark = "[bold green]✓[/bold green] " if i in multi_select else "  "
            # 待删除高亮
            if delete_pending == i:
                lines.append(f"[bold white on red] ❌ 确认删除? {title:<45s} Enter=确认 Esc=取消[/bold white on red]")
            elif editing and i == idx:
                cursor = "[dim yellow]▌[/dim yellow]"
                lines.append(f"[bold yellow on blue] ✎ {edit_buf}{cursor}[/bold yellow on blue]")
            elif i == idx:
                lines.append(f"[bold white on cyan] {ms_mark}{icon} {title:<52s} {status_tag} {arrow}[/bold white on cyan]")
            else:
                ms_dim = "[dim green]✓[/dim green] " if i in multi_select else "  "
                lines.append(f"[dim] {ms_dim}{icon} {title:<52s} {status_tag} {arrow}[/dim]")

        done = sum(1 for n in items if n.get("status") == "completed")
        total = count
        depth_names = ["", "科目", "部分", "单元", "课程", "内容"]
        dname = depth_names[min(depth, len(depth_names) - 1)]
        lines.append("")
        lines.append(f"[dim]层级 {depth}（{dname}） | {done}/{total} 完成[/dim]")
        if multi_select:
            lines.append(f"[bold green]已选 {len(multi_select)} 项  [bold cyan]A[/bold cyan][dim]全选  [bold cyan]I[/bold cyan][dim]反选[/dim][/bold green]")
        if delete_pending >= 0:
            lines.append("[bold red]⚠ 确认删除  [bold]Enter[/bold][dim]=确认  [bold]Esc[/bold][dim]=取消[/dim][/bold red]")
        if result_msg:
            lines.append(f"[bold yellow]📝 附言: {result_msg[:60]}[/bold yellow]")
        lines.append(f"[dim][bold cyan]↑↓[/bold cyan][dim]移动  [bold cyan]→[/bold cyan][dim]进入  [bold cyan]←[/bold cyan][dim]返回  [bold cyan]Space[/bold cyan][dim]编辑  [bold cyan]+[/bold cyan][dim]多选  [bold cyan]⌫[/bold cyan][dim]删除  [bold cyan]Esc[/bold cyan][dim]退出[/dim][/dim]")
        return Panel("\n".join(lines), box=ROUNDED, border_style="cyan",
                     title=f"[bold cyan]教学大纲[/bold cyan]", title_align="center",
                     padding=(1, 2))

    # 定位到终端顶部附近
    console.print("\n\n")
    display = _PickerDisplay()
    console.file.write("\033[?25l")
    console.file.flush()
    display.start(_render())
    try:
        while True:
            if editing:
                # ── 内联编辑模式（使用 getwch 支持输入法） ──
                ch = msvcrt.getwch()
                if ch == '\r':
                    new_title = edit_buf.strip()
                    if new_title:
                        items, _ = _current_level()
                        node = items[idx]
                        node["title"] = new_title
                        if "data" in node and isinstance(node["data"], dict):
                            node["data"]["title"] = new_title
                    editing = False
                    edit_buf = ""
                elif ch == '\x1b':
                    editing = False
                    edit_buf = ""
                elif ch == '\x08':
                    edit_buf = edit_buf[:-1]
                elif ch == '\xe0':  # getwch 中箭头键的前缀
                    pass  # 编辑时忽略箭头键
                elif len(ch) == 1 and ch.isprintable():
                    edit_buf += ch
                # 多字节字符（中文等）通过 getwch 作为单个宽字符传入
                display.update(_render())
                continue

            # ── 正常导航模式 ──
            key = msvcrt.getch()
            items, _ = _current_level()
            count = len(items)

            if key == b"\xe0":
                key = msvcrt.getch()
                if key == b"H":  # 上箭头
                    idx = (idx - 1) % count if count else 0
                elif key == b"P":  # 下箭头
                    idx = (idx + 1) % count if count else 0
                elif key == b"K":  # 左箭头 — 返回上级
                    if _drill_out():
                        idx = 0
                elif key == b"M":  # 右箭头 — 进入
                    if count and idx < count and _drill_into(items[idx]):
                        idx = 0
            elif key == b"\t":
                idx = (idx + 1) % count if count else 0
            elif key == b"\r":  # 回车 — 确认删除 / 进入
                if delete_pending >= 0 and count:
                    # 确认删除
                    removed_idx = delete_pending
                    delete_pending = -1
                    node = items.pop(removed_idx)
                    # 如果可能，从底层数据中移除
                    _remove_node_from_plan(plan, node)
                    if idx >= len(items) and items:
                        idx = len(items) - 1
                    multi_select.discard(removed_idx)
                elif count and idx < count:
                    node = items[idx]
                    title = node.get("title", "").strip()
                    if not title:
                        # 空项目 — 删除
                        items.pop(idx)
                        _remove_node_from_plan(plan, node)
                        if idx >= len(items) and items:
                            idx = len(items) - 1
                    elif _drill_into(node):
                        idx = 0
            elif key == b"\x08":  # 退格 — 标记删除
                if count and idx < count:
                    delete_pending = idx
            elif key == b" ":  # 空格 — 内联编辑
                if delete_pending >= 0:
                    delete_pending = -1  # 取消删除
                elif count and idx < count:
                    editing = True
                    edit_buf = items[idx].get("title", "")
            elif key in (b"+", b"="):  # +（或 =，即 Shift+=）— 多选切换
                if count and idx < count:
                    if idx in multi_select:
                        multi_select.discard(idx)
                    else:
                        multi_select.add(idx)
            elif key in (b"a", b"A"):  # A 键 — 全选
                if multi_select:
                    multi_select.clear()
                else:
                    multi_select = set(range(count))
            elif key in (b"i", b"I"):  # I 键 — 反选
                current = set(range(count))
                multi_select = current - multi_select
            elif key == b"`":  # 反引号 — 消息框（包含已选项）
                display.stop()
                prompt = "📝 附言: "
                if multi_select:
                    selected_titles = [items[i].get("title", "")[:40] for i in sorted(multi_select) if i < count]
                    if selected_titles:
                        prompt = f"📝 附言（已选 {len(selected_titles)} 项）: "
                try:
                    note = builtins.input(prompt).strip()
                except (EOFError, KeyboardInterrupt):
                    note = ""
                if note:
                    if multi_select:
                        selected_titles = [items[i].get("title", "")[:40] for i in sorted(multi_select) if i < count]
                        ctx = "；".join(selected_titles)
                        note = f"[关于: {ctx}] {note}"
                    result_msg = (result_msg + "；" + note) if result_msg else note
                display.start(_render())
            elif key in (b"\x1b", b"\x03"):
                # Esc：先取消当前活动操作，只有无活动操作时才退出
                if delete_pending >= 0:
                    delete_pending = -1
                elif editing:
                    editing = False
                    edit_buf = ""
                elif multi_select:
                    multi_select.clear()
                else:
                    break
            elif key in (b"q", b"Q"):
                break
            else:
                continue
            display.update(_render())
    finally:
        console.file.write("\033[?25h")
        console.file.flush()
        console.clear()

    if result_msg:
        return f"📋 教学大纲已查看。（附言: {result_msg}）"
    return "📋 教学大纲已查看。"


def _remove_node_from_plan(plan: dict, node: dict) -> bool:
    """从底层 plan 数据中移除树节点。成功返回 True。"""
    data = node.get("data")
    if not data or not isinstance(data, dict):
        return False
    ntype = node.get("type", "")
    # 尝试从 sections[].units[].lessons[] 或 flat lessons[] 中移除
    if "sections" in plan:
        for sec in plan["sections"]:
            for unit in sec.get("units", []):
                if ntype == "lesson" and "lessons" in unit:
                    les_list = unit["lessons"]
                    for i, les in enumerate(les_list):
                        if les is data or les.get("id") == data.get("id"):
                            les_list.pop(i)
                            return True
            # 同时检查是否为 unit 本身
            if ntype == "unit" and "units" in sec:
                ulist = sec["units"]
                for i, u in enumerate(ulist):
                    if u is data or u.get("id") == data.get("id"):
                        ulist.pop(i)
                        return True
            # 检查是否为 section
            if ntype == "section":
                for i, s in enumerate(plan["sections"]):
                    if s is data or s.get("id") == data.get("id"):
                        plan["sections"].pop(i)
                        return True
    if "lessons" in plan:
        for i, les in enumerate(plan["lessons"]):
            if les is data or les.get("id") == data.get("id"):
                plan["lessons"].pop(i)
                return True
    return False


def show_progress() -> str:
    import json
    progress_file = PROGRESS_FILE
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


# ── 会话命令 ──────────────────────────────────────────────────

def _cmd_save(ctx: dict, args: str) -> str:
    loop = ctx["loop"]
    name = args.strip() if args.strip() else ""
    saved_name = loop.save(name if name else None)
    return f"✓ 会话已保存为 [cyan]{saved_name}[/cyan]"


def _cmd_rename(ctx: dict, args: str) -> str:
    """将当前会话文件从旧名称重命名为新名称。"""
    new_name = args.strip()
    if not new_name:
        return "用法: /rename <新名称>"
    loop = ctx["loop"]
    old_name = loop._session_name
    if not old_name:
        return "当前会话尚未保存，请先 /save。"

    # 查找并重命名文件
    from keenius.agent.sessions import project_sessions_dir, global_sessions_dir
    for base_dir in (project_sessions_dir(), global_sessions_dir()):
        old_path = base_dir / f"{old_name}.json"
        new_path = base_dir / f"{new_name}.json"
        if old_path.exists():
            if new_path.exists():
                return f"会话 [cyan]{new_name}[/cyan] 已存在。请换一个名称。"
            old_path.rename(new_path)
            loop._session_name = new_name
            return f"✓ 已重命名 [cyan]{old_name}[/cyan] → [cyan]{new_name}[/cyan]"
    return f"未找到会话文件: {old_name}.json"


def _cmd_load(ctx: dict, args: str) -> str:
    name = args.strip()
    if name:
        # 按名称直接加载
        loop = ctx["loop"]
        if loop.load(name):
            loop.subject = loop.subject or ""
            return f"✓ 已加载会话 [cyan]{name}[/cyan]\n  {loop.turn_count} 轮对话, {len(loop.messages)} 条消息\n\n输入内容继续对话。"
        return f"未找到会话: {name}\n输入 /sessions 查看可用的会话列表。"

    # 未提供名称 — 显示交互式选择器
    sessions = ConversationLoop.list_sessions()
    if not sessions:
        return "暂无保存的会话。"
    from keenius.agent.sessions import load_session_by_name
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


def _cmd_reopen_picker(ctx: dict) -> str:
    """在 REPL 内部重新打开会话选择器。返回 EXIT 以触发重启。"""
    from keenius.agent.sessions import scan_sessions, get_auto_load_session, load_session_by_name
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

    from keenius.agent.sessions import load_session_by_name

    # 构建键盘选择器的选项
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
    """通用键盘列表选择器。返回索引或 None。"""
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit import PromptSession as PS

    kb = KeyBindings()
    idx = [0]

    def _toolbar():
        lines = [f"{title}"] if title else []
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

    ps = PS(key_bindings=kb, bottom_toolbar=_toolbar, style=CHAT_STYLE, input=create_input(), wrap_lines=False, enable_system_prompt=False)
    try:
        return ps.prompt("")
    except (EOFError, KeyboardInterrupt):
        return None


# ── 帮助 ──────────────────────────────────────────────────────────────

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


# ── 斜杠命令分发 ─────────────────────────────────────────────

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


# ── 进度持久化 ──────────────────────────────────────────────

def save_progress(concept: str, status: str, notes: str = "") -> None:
    import json
    progress_file = PROGRESS_FILE
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
    """将学生评估持久化到 ~/.keenius/profiles/default.json。"""
    import json, datetime
    from keenius.config import PROFILES_DIR, ensure_dirs

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
            # 认知 / 性格（全局，跨学科）
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
        # 认知/性格特征：直接写入 profile 根层级
        profile[dimension] = value
        profile.setdefault("cognitive_notes", {})[dimension] = {"value": value, "evidence": evidence, "updated_at": now}

    profile["history"].append({
        "dimension": dimension, "value": value, "concept": concept,
        "evidence": evidence, "recorded_at": now,
    })

    profile_file.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 提示符样式（借鉴 Hermes） ──────────────────────────────────

CHAT_STYLE = Style.from_dict({
    "prompt": "bold cyan",
    "input-rule": "#00AFAF",
    "toolbar": "bg:#1a1a2e #C0C0C0",
    "toolbar.phase": "bg:#1a1a2e #00AFAF bold",
    "toolbar.info": "bg:#1a1a2e #888888",
})


# ── 会话选择器 UI ─────────────────────────────────────────────────

def _do_rename_session(s: dict, new_name: str) -> bool:
    """重命名磁盘上的会话文件。成功返回 True。"""
    from keenius.agent.sessions import sessions_dir
    old_name = s["name"]
    base_dir = sessions_dir()
    old_path = base_dir / f"{old_name}.json"
    new_path = base_dir / f"{new_name}.json"
    if old_path.exists() and not new_path.exists():
        old_path.rename(new_path)
        return True
    return False


def session_picker(sessions: list[dict]) -> dict | str | None:
    """键盘会话选择器：Rich 显示 + msvcrt 按键。不使用 prompt_toolkit。

    R  = 重命名选中的会话（使用 input() 以支持输入法）。
    其他按键见底部说明。
    """
    import msvcrt
    import builtins
    from keenius.agent.sessions import set_pinned_session, clear_pinned_session, get_pin_config
    from rich.panel import Panel
    from rich.box import HEAVY

    pin_config = get_pin_config()
    pinned_name = pin_config.get("auto_load", "")
    count = len(sessions) + 1
    idx = 0

    def _render():
        lines = []
        for i, s in enumerate(sessions):
            pin = "📌" if s["name"] == pinned_name else " "
            subj = s["subject"] or "(无主题)"
            src_label = "项目" if s["source"] == "project" else "全局"
            msg_count = f"{s['messages']}条"
            time_str = s["saved_at"]
            if renaming and i == idx:
                cursor = "[dim yellow]▌[/dim yellow]"
                lines.append(
                    f"[bold yellow on blue] ✎ {pin} {rename_buf}{cursor:<22s} [/bold yellow on blue]"
                    f"[bold yellow] {subj:<14s}  {msg_count:>5s}  {time_str}  {src_label}[/bold yellow]"
                )
            elif i == idx:
                lines.append(
                    f"[bold white on cyan] {pin} {s['name']:<22s} [/bold white on cyan]"
                    f"[bold cyan] {subj:<14s}  {msg_count:>5s}  {time_str}  {src_label}[/bold cyan]"
                )
            else:
                lines.append(
                    f"[dim]  {pin} {s['name']:<22s}  {subj:<14s}  {msg_count:>5s}  {time_str}  {src_label}[/dim]"
                )
        new_line = "＋ 新建会话"
        if idx == len(sessions):
            lines.append(f"[bold white on green] {new_line} [/bold white on green]")
        else:
            lines.append(f"[dim]  {new_line}[/dim]")

        lines.append("")
        if renaming:
            lines.append("[bold yellow]✎ 编辑中  [bold]Enter[/bold][dim]=确认  [bold]Esc[/bold][dim]=取消[/dim][/bold yellow]")
        else:
            lines.append(f"[dim][bold cyan]↑↓[/bold cyan][dim]选择  [bold cyan]Enter[/bold cyan][dim]打开  [bold cyan]Space[/bold cyan][dim]重命名  [bold cyan]P[/bold cyan][dim]固定  [bold cyan]N[/bold cyan][dim]新建  [bold cyan]Q[/bold cyan][dim]退出[/dim][/dim]")
        if pinned_name:
            lines.append(f"[yellow]📌 已固定: {pinned_name}（启动时自动加载）[/yellow]")
        else:
            lines.append("[dim]按 [bold cyan]P[/bold cyan] 可固定会话为启动自动加载[/dim]")
        return Panel(
            "\n".join(lines),
            box=HEAVY,
            border_style="yellow" if renaming else "cyan",
            title="[bold yellow]重命名[/bold yellow]" if renaming else "[bold cyan]会话列表[/bold cyan]",
            title_align="center",
            padding=(1, 2),
        )

    renaming = False
    rename_buf = ""

    display = _PickerDisplay()
    console.file.write("\033[?25l")
    console.file.flush()
    display.start(_render())
    try:
        while True:
            # ── 内联重命名模式 ──
            if renaming:
                ch = msvcrt.getwch()
                if ch == '\r':
                    new_name = rename_buf.strip()
                    if new_name and new_name != sessions[idx]["name"]:
                        _do_rename_session(sessions[idx], new_name)
                        sessions[idx]["name"] = new_name
                        if sessions[idx]["name"] == pinned_name:
                            set_pinned_session(new_name, sessions[idx].get("source", ""))
                            pinned_name = new_name
                    renaming = False
                    rename_buf = ""
                elif ch == '\x1b':
                    renaming = False
                    rename_buf = ""
                elif ch == '\x08':
                    rename_buf = rename_buf[:-1]
                elif ch == '\xe0':
                    msvcrt.getwch()
                elif ch == '\t':
                    pass
                elif len(ch) == 1 and ch.isprintable():
                    rename_buf += ch
                elif ord(ch) > 127:
                    rename_buf += ch
                display.update(_render())
                continue

            key = msvcrt.getch()
            if key == b"\xe0":
                key = msvcrt.getch()
                if key == b"H": idx = (idx - 1) % count
                elif key == b"P": idx = (idx + 1) % count
            elif key == b"\t": idx = (idx + 1) % count
            elif key == b"\r":
                if idx < len(sessions): return sessions[idx]
                return "NEW"
            elif key == b" ":  # 空格 = 内联重命名
                if idx < len(sessions):
                    renaming = True
                    rename_buf = sessions[idx]["name"]
            elif key in (b"p", b"P"):  # P = 固定/取消固定
                if idx < len(sessions):
                    s = sessions[idx]
                    if s["name"] == pinned_name:
                        clear_pinned_session(); pinned_name = ""
                    else:
                        set_pinned_session(s["name"], s["source"]); pinned_name = s["name"]
            elif key in (b"n", b"N"): return "NEW"
            elif key in (b"q", b"Q", b"\x1b"): return None
            else: continue
            display.update(_render())
    finally:
        console.file.write("\033[?25h")
        console.file.flush()
        console.clear()


def run_shell_with_session(data: dict) -> None:
    """使用预加载的会话启动 REPL。打印完整对话历史，
    包含完整格式——选项以样式面板展示、思考内容、
    工具调用、系统通知——完全还原原始对话的外观。"""
    from keenius.agent.display import (
        console, print_info, print_error,
        print_user_label, print_reasoning_box_open, print_reasoning_text,
        print_reasoning_box_close, print_tool_call, print_tool_result,
        print_response_box_open, print_response_box_close,
        print_response_panel,
        print_system_notice, print_phase_banner,
    )

    loop = ConversationLoop.from_dict(data)

    # 为当前阶段构建系统提示词
    from keenius.tutor.prompts import build_system_prompt
    sys_prompt = build_system_prompt(
        subject=loop.subject, language=loop.language,
        teaching_style=loop.teaching_style, phase=loop.phase,
    )
    if loop.messages and loop.messages[0]["role"] == "system":
        loop.messages[0]["content"] = sys_prompt

    print_info(f"已加载会话  |  {loop.turn_count} 轮对话  |  阶段: {loop.phase}")

    # ── 打印完整对话历史，使用 Hermes 风格事件标记 ──
    for m in loop.messages:
        role = m.get("role", "")
        content = m.get("content", "")

        # 系统消息 — 跳过
        if role == "system":
            continue

        # 用户消息
        if role == "user" and content:
            if content.startswith("[系统通知]"):
                print_system_notice(content.removeprefix("[系统通知]").strip())
            else:
                print_user_label(content)
            continue

        # 助手消息 — 统一的事件流
        if role == "assistant":
            reasoning = m.get("reasoning_content", "")
            tool_calls = m.get("tool_calls")

            # 先显示推理内容（dim 框）
            if reasoning:
                text = reasoning[:400] + ("..." if len(reasoning) > 400 else "")
                print_reasoning_box_open()
                print_reasoning_text(text)
                print_reasoning_box_close()

            # 工具调用
            if tool_calls:
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    name = fn.get("name", "?")
                    args_str = fn.get("arguments", "")[:80]
                    print_tool_call(name, args_str)

            # 主要回复 — 统一使用 ROUNDED Panel 展示
            if content:
                print_response_panel(content, loop.phase)
            continue

        # 工具结果
        if role == "tool":
            short = (content or "").replace("\n", " ")[:100]
            print_tool_result(short)

    # ── 如果最后一条消息有选项，重新激活待处理的选择器 ──
    display_msgs = [m for m in loop.messages if m.get("role") == "assistant" and m.get("content")]
    if display_msgs:
        last = display_msgs[-1]
        opt_result = _extract_options(last["content"])
        pick_chain = 0
        while opt_result and pick_chain < 3:
            pick_chain += 1
            options, question = opt_result
            selected = _pick_choice_interactive(options, question, loop)
            if not selected:
                break
            try:
                follow_up = loop.send_message(selected)
                _auto_save_silent(loop)
                _display_reasoning(loop)
                print_response_panel(follow_up, loop.phase)
                opt_result = _extract_options(follow_up)
            except Exception as e:
                print_error(f"请求失败: {e}")
                break

    _run_repl_loop(loop)


def _print_message_full(text: str) -> None:
    """渲染单条助手消息，包含完整格式。
    选项渲染为普通 dim 文本——交互式选择器在需要时
    处理样式 UI。历史记录永不显示假选择器。
    """
    from keenius.agent.display import console, prepare_markdown
    from rich.markdown import Markdown

    # 历史记录中的选项 → 纯文本，而非样式面板
    #（交互式选择器仅用于实时交互，不用于历史记录）
    console.print(Markdown(prepare_markdown(text)))


# ── 主 REPL ─────────────────────────────────────────────────────────


def _display_reasoning(loop) -> None:
    """如果存在 AI 推理内容，以 Hermes 风格 dim 框显示。"""
    if loop._last_reasoning:
        from keenius.agent.display import print_reasoning_box_open, print_reasoning_text, print_reasoning_box_close
        rtext = loop._last_reasoning[:400] + ("..." if len(loop._last_reasoning) > 400 else "")
        print_reasoning_box_open()
        print_reasoning_text(rtext)
        print_reasoning_box_close()
        loop._last_reasoning = ""

def run_shell(
    subject: str = "",
    language: str = "zh",
    teaching_style: str = "socratic",
    model: str | None = None,
) -> None:
    from keenius.config import PROGRESS_FILE, HISTORY_FILE

    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch_track_progress()

    # ── 初始化 agent ──────────────────────────────────────────────────
    loop = ConversationLoop(
        subject=subject, language=language,
        teaching_style=teaching_style, model=model,
    )

    import keenius
    splash_model = model or loop.model
    from keenius.agent.display import print_splash
    print_splash(version=keenius.__version__, model=splash_model)

    try:
        loop.start()
    except Exception as e:
        _handle_startup_error(e)
        _run_offline_repl(loop)
        return

    _run_repl_loop(loop)


def _run_repl_loop(loop: ConversationLoop) -> None:
    """主 REPL：在线模式，完整的 agent 交互。"""
    from keenius.config import PROGRESS_FILE, HISTORY_FILE
    from keenius import config as cfg

    history_file = HISTORY_FILE
    session = PromptSession(
        history=FileHistory(str(history_file)),
                completer=SlashCompleter(),
        complete_while_typing=True,
        key_bindings=repl_bindings,
        style=CHAT_STYLE,
        bottom_toolbar=lambda: _toolbar_text(loop),
        input=create_input(),
        wrap_lines=False,
        enable_system_prompt=False,
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

        # 斜杠命令？
        cmd_result = handle_slash_command(user_input, context)
        if cmd_result is not None:
            if cmd_result == "EXIT":
                _auto_save_on_exit(loop)
                print_info("再见！学习愉快 📚")
                break
            console.print(cmd_result)
            continue

        # Agent 交互
        try:
            response = loop.send_message(user_input)
        except Exception as e:
            msg = str(e)
            if "401" in msg or "Incorrect API key" in msg or "invalid_api_key" in msg:
                print_error("API Key 无效。")
                console.print("[bold yellow]请输入 [bold]/setup[/bold] 重新配置[/bold yellow]")
                loop.notify_llm("API Key 验证失败，导致上一轮对话中断。")
            else:
                print_error(f"请求失败: {msg}")
            continue

        # 显示推理内容（Hermes dim 框）然后显示回复
        _display_reasoning(loop)
        from keenius.agent.display import print_response_panel
        # 始终显示完整回复（带 MD 渲染），选择框负责交互
        print_response_panel(response, loop.phase)

        # 有意义的对话后自动保存
        _auto_save_silent(loop)

        # ── 多问题选择 ──
        multi_qs = _extract_multi_questions(response)
        if multi_qs:
            result = _pick_multi_question(multi_qs)
            if result:
                # 从所有问题构建组合答案字符串
                answers = []
                for qi, txt in sorted(result.items()):
                    q_num = multi_qs[qi]["num"]
                    answers.append(f"问题{q_num}：{txt}")
                combined = "；".join(answers)
                follow_up = loop.send_message(combined)
                _auto_save_silent(loop)
                _display_reasoning(loop)
                print_response_panel(follow_up, loop.phase)
            continue

        # ── 单问题选择 ──
        opt_result = _extract_options(response)
        pick_chain = 0
        while opt_result and pick_chain < 3:
            pick_chain += 1
            options, question = opt_result
            selected = _pick_choice_interactive(options, question, loop)
            if not selected:
                break
            follow_up = loop.send_message(selected)
            _auto_save_silent(loop)
            _display_reasoning(loop)
            print_response_panel(follow_up, loop.phase)
            opt_result = _extract_options(follow_up)
        if pick_chain > 0:
            continue

        # LLM 通过提示词选项处理课程审阅 — 此处不自动审阅
        console.print()


def _extract_options(text: str) -> tuple[list, str] | None:
    """从文本中提取 [N] 选项。返回 (options_list, question_text) 或 None。
    在 ## 标题处截断，避免跨问题合并。"""
    # 在第一个 ## 标题处截断，防止多问题块合并
    mq_split = re.split(r"^\s*##\s*问题\s*\d+", text, maxsplit=1, flags=re.MULTILINE)
    text = mq_split[0]

    options = []
    for m in re.finditer(r"\[(\d+)\]\s*(.+?)(?=\n(?:——|\[(?:\d+)\])|\n*$)", text, re.DOTALL):
        num = int(m.group(1))
        desc = m.group(2).strip().rstrip(".。,， ")
        if desc.startswith("——"):
            options.append({"num": num, "text": "", "separator": True})
        else:
            options.append({"num": num, "text": desc})

    # 在非连续的选项编号之间插入 —— 分隔符
    i = 0
    while i < len(options) - 1:
        if options[i].get("separator") or options[i+1].get("separator"):
            i += 1
            continue
        if options[i+1]["num"] != options[i]["num"] + 1:
            options.insert(i + 1, {"num": 0, "text": "——", "separator": True})
        i += 1

    real_opts = [o for o in options if not o.get("separator")]
    if len(real_opts) < 2:
        return None

    first_opt_match = re.search(r"^\[(\d+)\]", text, re.MULTILINE)
    if first_opt_match:
        question = text[:first_opt_match.start()].strip()
    else:
        question = ""

    return options, question


# ── 多问题解析 ──────────────────────────────────────────────



def _extract_multi_questions(text: str) -> list[dict] | None:
    """从 LLM 输出中解析 ## 问题 N 块。

    容错处理：
    - 流式截断（最后一个块可能不完整——优雅丢弃）
    - 标题周围的变长空白
    - 第一个标题前的文本（忽略）
    - 选项过少的块（跳过）

    格式：## 问题 1  \\n  问题文字  \\n  [1] 选项  [2] 选项 ...
    返回 {num, text, options} 列表或 None（少于 2 个有效块）。
    """
    # 按 "## 问题 N" 分割 — 宽松空白匹配
    HEADING_RE = re.compile(r"^\s*##\s*问题\s*(\d+)\s*", re.MULTILINE)
    blocks = HEADING_RE.split(text)

    # blocks 布局：[preface, num1, body1, num2, body2, ..., numN, bodyN]
    # 至少需要 2 个问题 → preface 之后需 4 个元素
    if len(blocks) < 5:
        return None

    questions = []
    # 步进配对：(num, body)
    i = 1
    while i + 1 < len(blocks):
        try:
            h_num = int(blocks[i])
        except (ValueError, TypeError):
            i += 2
            continue
        body = blocks[i + 1].strip()
        i += 2

        if not body:
            continue

        # 从此块中提取选项
        opt_result = _extract_options(body)
        if opt_result is None:
            # 可能被截断 — 跳过此块，保留前面有效的
            continue

        opts, q_text = opt_result
        if not q_text:
            # 如果 _extract_options 未找到文字，使用第一行作为问题
            lines = body.strip().split("\n")
            q_text = lines[0].strip() if lines else ""

        questions.append({"num": h_num, "text": q_text, "options": opts})

    return questions if len(questions) >= 2 else None


def _pick_choice_interactive(options: list, question: str = "", loop=None):
    """输入框选择器：选项位于带边框的用户输入区域内。

    ↑↓/Tab   导航选项
    ↓ 超过最后一项 → 聚焦输入栏（通过 prompt_toolkit 支持输入法）
    Space     编辑选中选项文本（内联）
    +         切换多选勾选标记
    Enter     确认：发送选中的选项 + 任何输入的文本
    Esc       跳过 / 取消
    """
    import msvcrt
    import builtins
    from rich.panel import Panel
    from rich.box import HEAVY

    n_opts = len(options)
    idx = 0
    # 起始时跳过分隔符
    while idx < n_opts and options[idx].get("separator"):
        idx += 1
    if idx >= n_opts:
        idx = 0
    checked: set[int] = set()
    input_buf = ""
    focus_input = False
    inputting = False       # 正在输入栏中原地打字
    is_multi = "可多选" in question
    warn_msg = ""
    editing = False
    edit_buf = ""
    blank_mode = False      # 在选中选项中填空
    blank_parts: list[str] = []  # 按 ___ 分割的文本段
    blank_fills: list[str] = []  # 用户对每个空的填写
    blank_idx = 0           # 当前聚焦的空位

    def _next_real(i: int, delta: int = 1) -> int:
        """移动到下一个非分隔符选项。"""
        for _ in range(n_opts):
            i = (i + delta) % n_opts
            if not options[i].get("separator"):
                return i
        return i

    _opt_content_lines = 0  # 由 _render() 更新

    def _update_display():
        """渲染面板，CU光标供 IME 定位。"""
        renderable = _render()
        # 面板行数：选项(opt_lines+4) + 输入(3) + console.print 尾换行(1) = opt_lines+8
        total_lines = _opt_content_lines + 8
        if inputting:
            up = 2
            right = 5 + _visual_width(input_buf) - 1
        elif editing:
            vi = 0
            if question:
                vi += 2
            for i, opt in enumerate(options):
                if i == idx:
                    break
                vi += 1
            N = _opt_content_lines
            up = N + 5 - vi
            num_str = f"[{options[idx]['num']}]"
            prefix = f" ✎  {num_str} "
            right = 3 + _visual_width(prefix) + _visual_width(_md_to_rich(edit_buf)) - 1
        else:
            up = 0
            right = 0
        display.update(renderable, lines=total_lines, cursor_up=up, cursor_right=right)

    console.print()

    def _render():
        # ── 选项面板 ──
        opt_lines = []
        if question:
            opt_lines.append(f"[bold white]{_md_to_rich(question)}[/bold white]")
            opt_lines.append("[dim]" + "─" * 50 + "[/dim]")
        for i, opt in enumerate(options):
            if opt.get("separator"):
                opt_lines.append(f"[dim italic]  ── {opt['text']} ──[/dim italic]")
                continue
            num = f"[{opt['num']}]"
            text = _md_to_rich(opt["text"][:100])
            mark = "[bold green]✓[/bold green] " if i in checked else "  "
            if blank_mode and i == idx:
                parts = options[i]["text"].split("___")
                rendered = ""
                for bi, p in enumerate(parts):
                    rendered += _md_to_rich(p)
                    if bi < len(parts) - 1:
                        fill = blank_fills[bi] if bi < len(blank_fills) else ""
                        if bi == blank_idx:
                            rendered += f"[bold white on green]{fill or '___'}▌[/bold white on green]"
                        else:
                            rendered += f"[dim green]{fill or '___'}[/dim green]"
                opt_lines.append(f"[bold yellow on blue] ✎ [{options[i]['num']}] {rendered}[/bold yellow on blue]")
            elif editing and i == idx:
                cursor = "[dim yellow]▌[/dim yellow]"
                opt_lines.append(f"[bold yellow on blue] ✎ {num} {_md_to_rich(edit_buf)}{cursor}[/bold yellow on blue]")
            elif i == idx and not focus_input:
                opt_lines.append(f"[bold white on cyan] {mark}{num} [/bold white on cyan][bold cyan] {text}[/bold cyan]")
            else:
                dm = "[dim green]✓[/dim green] " if i in checked else "  "
                opt_lines.append(f"[dim]{dm}{num}  {text}[/dim]")
        # 选项面板底栏（状态 + 按键提示）
        if warn_msg:
            opt_lines.append(f"[bold yellow]⚠ {warn_msg}[/bold yellow]")
        if checked:
            opt_lines.append(f"[bold green]已选 {len(checked)} 项[/bold green]")
        if blank_mode:
            n_blanks = len(blank_fills)
            opt_lines.append(f"[bold yellow]🔤 填空（{n_blanks}空） Tab/←→ 切换空  Enter 确认  Esc 取消[/bold yellow]")
        elif editing:
            opt_lines.append("[bold yellow]✎ 编辑中  Enter 确认  Esc 取消[/bold yellow]")
        else:
            opt_lines.append("[dim]↑↓ 选项  Space 编辑  + 多选  Enter 确认  Esc 跳过[/dim]")

        # 选项面板焦点状态
        if focus_input:
            opt_border = "dim"
        else:
            opt_border = "yellow" if editing else ("green" if blank_mode else ("blue" if is_multi else "bright_cyan"))
        opt_title_text = ("[bold green]🔤 填空[/bold green]" if blank_mode
                     else ("[bold yellow]编辑选项[/bold yellow]" if editing
                     else ("[bold blue]请选择（可多选）[/bold blue]" if is_multi
                     else "[bold cyan]请选择[/bold cyan]")))

        opt_panel = Panel(
            "\n".join(opt_lines),
            box=HEAVY,
            border_style=opt_border,
            title=opt_title_text,
            title_align="center",
            padding=(1, 2),
        )

        # ── 输入面板（仅输入栏，无提示） ──
        inp_lines = []
        if focus_input or inputting:
            cursor = "[dim yellow]▌[/dim yellow]"
            inp_lines.append(f"[bold cyan]▸[/bold cyan] [bold white]{input_buf}{cursor}[/bold white]")
        else:
            hint = input_buf if input_buf else "▸ 在此输入补充文字..."
            inp_lines.append(f"[dim]{hint}[/dim]")

        inp_border = "bright_cyan" if (focus_input or inputting) else "dim"
        inp_title = "[bold cyan]✏️ 输入[/bold cyan]" if (focus_input or inputting) else "[dim]✏️ 输入[/dim]"

        inp_panel = Panel(
            "\n".join(inp_lines),
            box=HEAVY,
            border_style=inp_border,
            title=inp_title,
            title_align="center",
            padding=(0, 2),
        )

        from rich.console import Group
        nonlocal _opt_content_lines
        _opt_content_lines = len(opt_lines)
        return Group(opt_panel, inp_panel)

    display = _PickerDisplay()
    console.file.write("\033[?25l")
    console.file.flush()
    display.start(_render())
    try:
        while True:
            # ── 填空模式 ──
            if blank_mode:
                # 使用 prompt_toolkit 进行输入法友好的填空
                display.stop()
                console.print(_render())
                # 构建显示上下文的提示符
                prompt_hint = blank_parts[0] if blank_parts else ""
                for bi in range(len(blank_fills)):
                    if blank_fills[bi]:
                        prompt_hint += f"[{blank_fills[bi]}]"
                    else:
                        prompt_hint += "[___]"
                    if bi + 1 < len(blank_parts):
                        prompt_hint += blank_parts[bi + 1]
                console.print(f"[dim]当前: {prompt_hint}[/dim]")
                from prompt_toolkit.shortcuts import prompt as pt_prompt
                try:
                    result = pt_prompt(
                        [("class:prompt", f"填空 {blank_idx + 1}/{len(blank_fills)} > ")],
                        default=blank_fills[blank_idx] if blank_idx < len(blank_fills) else "",
                        style=CHAT_STYLE,
                        wrap_lines=False,
                        enable_system_prompt=False,
                    )
                except (EOFError, KeyboardInterrupt):
                    blank_mode = False
                    warn_msg = ""
                    display.start(_render())
                    continue
                if result is not None:
                    if blank_idx < len(blank_fills):
                        blank_fills[blank_idx] = result.strip()
                    # 移动到下一个空或全部填完后确认
                    if all(blank_fills) and len(blank_fills) == len(blank_parts) - 1:
                        filled_text = ""
                        for bi, p in enumerate(blank_parts):
                            filled_text += p
                            if bi < len(blank_fills):
                                filled_text += blank_fills[bi]
                        console.print(f"  [dim]已发送: {filled_text[:80]}[/dim]")
                        console.print()
                        return filled_text
                    elif len(blank_fills) > 1:
                        blank_idx = (blank_idx + 1) % len(blank_fills)
                else:
                    blank_mode = False
                    warn_msg = ""
                display.start(_render())
                _update_display()
                continue

            # ── 输入栏原地输入模式 ──
            if inputting:
                ch = msvcrt.getwch()
                if ch == '\r':
                    result = input_buf
                    inputting = False
                    focus_input = False
                    warn_msg = ""
                    if checked:
                        selected = "；".join(options[i]["text"] for i in sorted(checked))
                    else:
                        selected = options[idx]["text"] if idx < n_opts else ""
                    if result.strip():
                        selected = f"{selected}\n[补充] {result.strip()}" if selected else result.strip()
                    if not selected.strip():
                        warn_msg = "请选择选项或输入内容后再确认"
                        _update_display()
                        continue
                    console.print(f"  [dim]已发送: {_e(selected[:80])}[/dim]")
                    console.print()
                    if loop and result.strip():
                        loop.notify_llm(f"用户补充说明：{result.strip()}")
                    return selected
                elif ch == '\x1b':
                    inputting = False
                    input_buf = ""
                elif ch == '\x08':
                    input_buf = input_buf[:-1]
                elif ch == '\xe0':
                    msvcrt.getwch()
                elif ch == '\t':
                    pass
                elif len(ch) == 1 and ch.isprintable():
                    input_buf += ch
                elif ord(ch) > 127:
                    input_buf += ch
                _update_display()
                continue

            # ── 内联编辑模式（原地 msvcrt 输入）──
            if editing:
                ch = msvcrt.getwch()
                if ch == '\r':
                    new_val = edit_buf.strip()
                    if new_val:
                        old = options[idx]["text"][:60]
                        options[idx]["text"] = new_val
                        if loop:
                            loop.notify_llm(f"用户将选项 [{options[idx]['num']}] 从「{old}」修改为「{new_val[:60]}」")
                    editing = False
                    edit_buf = ""
                elif ch == '\x1b':
                    editing = False
                    edit_buf = ""
                elif ch == '\x08':
                    edit_buf = edit_buf[:-1]
                elif ch == '\xe0':
                    msvcrt.getwch()  # 跳过箭头键前缀
                elif ch == '\t':
                    pass  # 忽略 Tab
                elif len(ch) == 1 and ch.isprintable():
                    edit_buf += ch
                elif ord(ch) > 127:
                    edit_buf += ch  # 多字节字符（中文等 IME 输出）
                _update_display()
                continue

            # ── 统一导航（选项 + 输入栏）──
            key = msvcrt.getch()
            if key == b"\xe0":
                key = msvcrt.getch()
                if key == b"H":  # 上箭头
                    if focus_input:
                        # 从输入栏回到最后一个选项
                        focus_input = False
                        idx = max(0, n_opts - 1) if n_opts else 0
                        while idx > 0 and options[idx].get("separator"):
                            idx -= 1
                    elif n_opts:
                        idx = _next_real(idx, -1)
                    warn_msg = ""
                elif key == b"P":  # 下箭头
                    if focus_input:
                        pass  # 已在最底部
                    elif idx >= n_opts - 1 or _next_real(idx, 1) == idx:
                        focus_input = True  # 进入输入栏
                    else:
                        idx = _next_real(idx, 1) if n_opts else 0
                    warn_msg = ""
            elif key == b"\t":
                if focus_input:
                    focus_input = False
                    idx = 0
                    while idx < n_opts and options[idx].get("separator"):
                        idx += 1
                elif n_opts:
                    idx = _next_real(idx, 1)
            elif key == b"\r":  # 回车
                # 输入栏聚焦时 → 进入原地输入模式
                if focus_input:
                    inputting = True
                    _update_display()
                    continue
                # 选项聚焦时
                if is_multi and not checked:
                    warn_msg = "这是多选题，请先按 + 勾选选项"
                elif checked:
                    selected = "；".join(options[i]["text"] for i in sorted(checked))
                    if input_buf.strip():
                        selected = f"{selected}\n[补充] {input_buf.strip()}"
                    console.print(f"  [dim]已发送: {_e(selected[:80])}[/dim]")
                    console.print()
                    if loop and input_buf.strip():
                        loop.notify_llm(f"用户补充说明：{input_buf.strip()}")
                    return selected
                elif idx < n_opts:
                    txt = options[idx].get("text", "")
                    if "___" in txt and not checked:
                        blank_mode = True
                        blank_parts = txt.split("___")
                        blank_fills = [""] * (len(blank_parts) - 1)
                        blank_idx = 0
                        warn_msg = ""
                        _update_display()
                        continue
                    selected = txt
                    if input_buf.strip():
                        selected = f"{selected}\n[补充] {input_buf.strip()}"
                    console.print(f"  [dim]已发送: {_e(selected[:80])}[/dim]")
                    console.print()
                    if loop and input_buf.strip():
                        loop.notify_llm(f"用户补充说明：{input_buf.strip()}")
                    return selected
            elif key == b" ":  # 空格 = 编辑
                if focus_input:
                    pass  # 输入栏不响应编辑键
                elif idx < n_opts and not options[idx].get("separator"):
                    editing = True
                    edit_buf = options[idx]["text"]
            elif key in (b"+", b"="):  # + 号 = 多选
                if focus_input:
                    pass
                elif idx < n_opts and not options[idx].get("separator"):
                    if idx in checked:
                        checked.discard(idx)
                    else:
                        checked.add(idx)
                        if loop:
                            loop.notify_llm(f"用户勾选了选项 [{options[idx]['num']}]：{options[idx]['text'][:60]}")
                    warn_msg = ""
            elif key in (b"a", b"A"):
                if not focus_input:
                    if checked:
                        checked.clear()
                    else:
                        checked = set(range(n_opts))
                    warn_msg = ""
            elif key in (b"i", b"I"):
                if not focus_input:
                    checked = set(range(n_opts)) - checked
                    warn_msg = ""
            elif key in (b"\x1b", b"\x03"):
                if focus_input:
                    focus_input = False  # 先从输入栏回到选项
                elif checked:
                    checked.clear()
                elif input_buf.strip():
                    input_buf = ""
                elif warn_msg:
                    warn_msg = ""
                else:
                    console.print()
                    return None
            else:
                continue
            _update_display()
    finally:
        console.file.write("\033[?25h")
        console.file.flush()
        console.clear()


def _pick_multi_question(questions: list[dict]) -> dict | None:
    """多问题选择器：并排问题，每个有各自的选项。

    questions = [
        {"text": "问题1", "options": [{"num":1, "text":"A"}, ...]},
        {"text": "问题2", "options": [{"num":1, "text":"X"}, ...]},
    ]

    ←/→  切换问题   ↑/↓/Tab  切换选项
    Space   切换选项   Enter    确认全部   Esc  取消

    返回 dict，映射问题索引 → 选中选项文本，或 None。
    """
    import msvcrt
    from rich.panel import Panel
    from rich.box import ROUNDED

    n_questions = len(questions)
    q_idx = 0  # 当前问题索引
    # 每个问题：选项索引和已选选项索引
    o_idx = [0] * n_questions
    selected: list[int | None] = [None] * n_questions  # None = 未回答

    def _all_answered() -> bool:
        return all(s is not None for s in selected)

    def _render():
        panels = []
        for qi, q in enumerate(questions):
            focused = (qi == q_idx)
            border = "cyan" if focused else "dim"
            title_style = "bold cyan" if focused else "dim"
            title = f"[{title_style}]问题 {qi + 1}/{n_questions}[/{title_style}]"
            lines = []
            q_text = _md_to_rich(q.get("text", ""))
            if q_text:
                lines.append(f"[bold white]{q_text}[/bold white]")
                lines.append("[dim]" + "─" * 40 + "[/dim]")
            for oi, opt in enumerate(q.get("options", [])):
                num = f"[{opt['num']}]"
                txt = _md_to_rich(opt["text"][:80])
                if focused and oi == o_idx[qi]:
                    lines.append(f"[bold white on cyan]   {num} [/bold white on cyan][bold cyan] {txt}[/bold cyan]")
                elif selected[qi] == oi:
                    lines.append(f"[bold green] ✓ {num} {txt}[/bold green]")
                else:
                    lines.append(f"[dim]   {num}  {txt}[/dim]")
            if not lines:
                lines.append("[dim](无选项)[/dim]")
            panels.append(Panel("\n".join(lines), box=ROUNDED, border_style=border,
                                title=title, title_align="left", padding=(0, 1)))
        footer_lines = []
        if _all_answered():
            footer_lines.append("[bold green]全部已答 ✓  Enter 确认[/bold green]")
        else:
            unanswered = [i + 1 for i, s in enumerate(selected) if s is None]
            footer_lines.append(f"[yellow]⚠ 问题 {', '.join(map(str, unanswered))} 未选，请选完后再确认[/yellow]")
        footer_lines.append("[dim]← → 切换问题  ↑ ↓ Tab 切换选项  Space 选择  Enter 确认  Esc 取消[/dim]")
        from rich.console import Group
        return Group(
            *panels,
            Panel("\n".join(footer_lines), box=ROUNDED, border_style="dim", padding=(0, 1)),
        )

    display = _PickerDisplay()
    console.file.write("\033[?25l")
    console.file.flush()
    display.start(_render())
    try:
        while True:
            key = msvcrt.getch()
            opts = questions[q_idx].get("options", [])
            n_opts = len(opts)
            if key == b"\xe0":
                key = msvcrt.getch()
                if key == b"H":  # 上箭头
                    if n_opts:
                        o_idx[q_idx] = (o_idx[q_idx] - 1) % n_opts
                elif key == b"P":  # 下箭头
                    if n_opts:
                        o_idx[q_idx] = (o_idx[q_idx] + 1) % n_opts
                elif key == b"K":  # 左箭头
                    q_idx = (q_idx - 1) % n_questions
                elif key == b"M":  # 右箭头
                    q_idx = (q_idx + 1) % n_questions
            elif key == b"\t":
                if n_opts:
                    o_idx[q_idx] = (o_idx[q_idx] + 1) % n_opts
            elif key == b" ":  # 空格 = 切换
                if n_opts:
                    selected[q_idx] = o_idx[q_idx]
            elif key == b"\r":  # 回车 = 确认
                if _all_answered():
                    display.stop()
                    result = {}
                    for qi, oi in enumerate(selected):
                        if oi is not None:
                            opts_q = questions[qi].get("options", [])
                            result[qi] = opts_q[oi]["text"] if oi < len(opts_q) else ""
                    for qi, txt in result.items():
                        console.print(f"  [dim]Q{qi + 1}: {_e(txt[:60])}[/dim]")
                    console.print()
                    return result
            elif key in (b"\x1b", b"\x03"):  # Esc 键
                return None
            else:
                continue
            display.update(_render())
    finally:
        console.file.write("\033[?25h")
        console.file.flush()
        console.clear()


def _review_curriculum(lessons: list) -> list[int]:
    """交互式课程审阅。Space=切换, A=全选, I=反选, Enter=确认。
    返回已跳过的课程 ID 列表（用户已掌握的课程）。"""
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit import PromptSession as PS

    skipped = set()  # 标记为"已会"的课程 ID
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
        lines = ["审核课程 — 勾掉已会的内容"]
        lines.append("")
        for i, lesson in enumerate(lesson_list):
            marker = "▶" if i == idx[0] else " "
            check = "[x]" if lesson["id"] in skipped else "[ ]"
            lines.append(f"{marker} {check} {lesson['title']}")
            if lesson.get("description"):
                lines.append(f"     {lesson['description']}")
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

    ps = PS(key_bindings=kb, bottom_toolbar=_toolbar, style=CHAT_STYLE, input=create_input(), wrap_lines=False, enable_system_prompt=False)
    try:
        return ps.prompt("")
    except (EOFError, KeyboardInterrupt):
        return None


def _auto_save_silent(loop: ConversationLoop) -> None:
    """每次有意义的交流后静默自动保存。"""
    if loop.turn_count > 0:
        try:
            loop.save()
        except Exception:
            pass


def _auto_save_on_exit(loop: ConversationLoop) -> None:
    """如果有有意义的对话，自动保存会话。"""
    if loop.turn_count > 0:
        try:
            name = loop.save()
            print_info(f"会话已自动保存为: {name}")
        except Exception:
            pass


def _run_offline_repl(loop: ConversationLoop) -> None:
    """离线 REPL：无 API Key，仅斜杠命令可用。"""
    from keenius.config import PROGRESS_FILE, HISTORY_FILE

    history_file = HISTORY_FILE
    session = PromptSession(
        history=FileHistory(str(history_file)),
        completer=SlashCompleter(),
        complete_while_typing=True,
        key_bindings=repl_bindings,
        style=CHAT_STYLE,
        bottom_toolbar=lambda: "⚙️  离线模式 — 请输入 /setup 配置 API 或 /help 查看帮助",
        input=create_input(),
        wrap_lines=False,
        enable_system_prompt=False,
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
                # 配置完成后，提示重启
                console.print("[bold green]配置完成！[/bold green] 请重新启动 [bold]Keenius[/bold]")
                break
        else:
            print_error("尚未配置 API Key。请先输入 [bold]/setup[/bold] 配置 API 连接。")


def _toolbar_text(loop: ConversationLoop) -> str:
    """底部工具栏：阶段 · 模型 · 轮次。借鉴 Hermes 的紧凑风格。"""
    phase_icons = {"diagnosis": "🔍 诊断", "planning": "📋 计划", "learning": "📖 学习", "end": "🏁 结束"}

    parts = [f"[bold cyan]{phase_icons.get(loop.phase, '💬')}[/bold cyan]"]
    parts.append(f"[dim]│[/dim] 🤖 [bright_black]{loop.model}[/bright_black]")
    parts.append(f"[dim]│[/dim] [bright_black]{loop.turn_count} 轮[/bright_black]")
    if loop.subject:
        parts.append(f"[dim]│[/dim] 📚 [bright_black]{loop.subject}[/bright_black]")
    return "  ".join(parts)


# ── 辅助函数 ───────────────────────────────────────────────────────────

def _maybe_track_progress_from_response(response: str) -> None:
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
    from keenius.tools.registry import registry

    # 持久化 track_progress
    tp = registry.get_tool("track_progress")
    if tp is not None:
        def _persistent_tracker(concept: str, status: str, notes: str = "") -> str:
            save_progress(concept, status, notes)
            return tp.handler(concept=concept, status=status, notes=notes)
        tp.handler = _persistent_tracker

    # 持久化 assess_student
    ae = registry.get_tool("assess_student")
    if ae is not None:
        def _persistent_assess(dimension: str, value: str, concept: str = "", evidence: str = "") -> str:
            save_assessment(dimension, value, concept, evidence)
            return ae.handler(dimension=dimension, value=value, concept=concept, evidence=evidence)
        ae.handler = _persistent_assess
