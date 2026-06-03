"""单一 prompt_toolkit Application — Keenius 完整 UI。

原则：
- state → render(): 纯函数
- 唯一 Application，事件驱动
- 禁止 console.print, msvcrt, ANSI, Rich Live
"""

from __future__ import annotations
from dataclasses import dataclass, field
import re, time as _time, unicodedata

def _log(msg: str):
    try:
        with open("c:/temp/keenius_debug.log", "a", encoding="utf-8") as _f:
            _f.write(f"[{_time.time():.3f}] {msg}\n")
    except Exception:
        pass

from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout, HSplit, Window, ConditionalContainer
from prompt_toolkit.layout.controls import FormattedTextControl, BufferControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.filters import Condition
from prompt_toolkit.output.defaults import create_output
from prompt_toolkit.input.defaults import create_input


# ═══════════════════════════════════════════════════════
# 状态
# ═══════════════════════════════════════════════════════

@dataclass
class AppState:
    mode: str = "repl"
    phase: str = "diagnosis"
    messages: list[list[tuple[str, str]]] = field(default_factory=list)
    thinking: bool = False

    # QuestionPicker
    qp_options: list[dict] = field(default_factory=list)
    qp_question: str = ""
    qp_cursor: int = 0
    qp_checked: set[int] = field(default_factory=set)
    qp_editing: bool = False
    qp_is_multi: bool = False

    # MultiQuestion
    mq_questions: list[dict] = field(default_factory=list)
    mq_q_idx: int = 0
    mq_o_idx: list[int] = field(default_factory=list)
    mq_selected: list[int | None] = field(default_factory=list)

    # SessionPicker
    sp_sessions: list[dict] = field(default_factory=list)
    sp_cursor: int = 0
    sp_renaming: bool = False
    sp_pinned_name: str = ""

    # CurriculumViewer
    cv_cursor: int = 0
    cv_stack: list[tuple[list[dict], str]] = field(default_factory=list)
    cv_editing: bool = False

    def _next_real(self, i: int, d: int = 1) -> int:
        o = self.qp_options; n = len(o)
        for _ in range(n):
            i = (i + d) % n
            if not o[i].get("separator"): return i
        return i


# ═══════════════════════════════════════════════════════
# 样式
# ═══════════════════════════════════════════════════════

APP_STYLE = Style.from_dict({
    "status-bar": "bg:#1a1a2e fg:#c0c0c0",
    "status-bar.phase": "bg:#1a1a2e fg:#00afaf bold",
    "status-bar.info": "bg:#1a1a2e fg:#888888",
    "prompt": "fg:#00afaf bold",
})


# ═══════════════════════════════════════════════════════
# 消息格式化
# ═══════════════════════════════════════════════════════

def _display_width(text: str) -> int:
    """计算字符串的终端显示宽度（CJK/emoji 算 2 列）。"""
    w = 0
    for ch in text:
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            w += 2
        else:
            w += 1
    return w

def _pad(text: str, width: int) -> str:
    """将文本用空格填充到指定显示宽度。"""
    dw = _display_width(text)
    if dw >= width:
        return text
    return text + " " * (width - dw)

def _wrap_by_width(text: str, max_w: int) -> list[str]:
    """按显示宽度将文本拆成多行。"""
    if not text:
        return [""]
    lines = []
    current = ""
    cw = 0
    for ch in text:
        chw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
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

def _fmt_user(text: str) -> list[tuple[str, str]]:
    text = text or ""
    lines = text.split("\n")
    r: list[tuple[str, str]] = [("", "\n"), ("bold fg:ansicyan", "● 你：")]
    r.append(("fg:gray", lines[0] if lines else ""))
    for line in lines[1:]:
        r.append(("", "\n")); r.append(("fg:gray", f"      {line}"))
    r.append(("", "\n")); return r

def _fmt_assistant_with_options(question: str, options: list[dict]) -> list[tuple[str, str]]:
    """格式化含选项的历史助手消息——选项显示为 dim 列表（不可交互）。
    边框字符单独着色，避免被内容文字样式污染。"""
    w = _term_width() - 6
    inner_w = w - 4
    bc = "fg:ansicyan"
    r: list[tuple[str, str]] = [("", "\n")]
    r.append((bc, "╭─ Keenius "))
    r.append((bc, "─" * (w - 12)))
    r.append((bc, "╮\n"))
    if question:
        for line in question.split("\n"):
            r.append((bc, "│ "))
            r.append(("", _pad(line, inner_w)))
            r.append((bc, " │"))
            r.append(("", "\n"))
        r.append((bc, "│ "))
        r.append((bc, "─" * (w - 2)))
        r.append((bc, " │"))
        r.append(("", "\n"))
    for opt in options:
        if opt.get("separator"):
            r.append((bc, "│ "))
            r.append(("fg:gray italic", _pad(f"  ── {opt['text']}"[:inner_w], inner_w)))
            r.append((bc, " │"))
            r.append(("", "\n"))
        else:
            r.append((bc, "│ "))
            r.append(("fg:gray", _pad(f"  [{opt['num']}] {opt['text'][:inner_w - 10]}"[:inner_w], inner_w)))
            r.append((bc, " │"))
            r.append(("", "\n"))
    r.append((bc, "╰"))
    r.append((bc, "─" * (w - 2)))
    r.append((bc, "╯\n"))
    return r


def _fmt_assistant(text: str, width: int = 0, phase: str = "") -> list[tuple[str, str]]:
    """ROUNDED box ╭─╮╰╯ + 阶段颜色，匹配旧版 print_response_panel。
    边框字符单独着色，避免被内容文字样式污染。"""
    text = text or ""
    if width <= 0:
        import shutil
        width = max(shutil.get_terminal_size().columns - 6, 40)
    w = width
    inner_w = w - 4  # "│ " + content + " │"
    color = "fg:ansicyan"
    if phase == "diagnosis": color = "fg:ansicyan"
    elif phase == "planning": color = "fg:ansiyellow"
    elif phase == "learning": color = "fg:ansigreen"
    elif phase == "end": color = "fg:gray"

    r: list[tuple[str, str]] = [("", "\n")]
    r.append((color, "╭─ Keenius "))
    r.append((color, "─" * (w - 12)))
    r.append((color, "╮\n"))
    for line in text.split("\n"):
        r.append((color, "│ "))
        r.append(("", _pad(line, inner_w)))
        r.append((color, " │"))
        r.append(("", "\n"))
    r.append((color, "╰"))
    r.append((color, "─" * (w - 2)))
    r.append((color, "╯\n"))
    return r

def _fmt_reasoning(text: str) -> list[tuple[str, str]]:
    text = text or ""
    max_w = _term_width() - 10
    r: list[tuple[str, str]] = [("", "\n")]
    r.append(("fg:gray italic", "  ╭ 思考过程\n"))
    for line in text.split("\n"):
        for chunk in _wrap_by_width(line, max_w):
            r.append(("fg:ansibrightblack", "  │ "))
            r.append(("fg:gray italic", chunk))
            r.append(("", "\n"))
    r.append(("fg:gray italic", "  ╰\n"))
    return r

def _fmt_tool(name: str, preview: str = "") -> list[tuple[str, str]]:
    name = name or ""
    preview = preview or ""
    r: list[tuple[str, str]] = [("fg:ansicyan", f"  ┊ ● {name}")]
    if preview: r.append(("fg:gray", f": {preview[:80]}"))
    r.append(("", "\n")); return r

def _fmt_tool_result(preview: str = "") -> list[tuple[str, str]]:
    preview = preview or ""
    short = preview.replace("\n", " ")[:100]
    return [("fg:ansigreen", f"  ┊ ✓ {short}"), ("", "\n")]

def _fmt_error(msg: str) -> list[tuple[str, str]]:
    msg = msg or ""
    return [("fg:ansired", f"✗ {msg}"), ("", "\n")]

def _fmt_info(msg: str) -> list[tuple[str, str]]:
    msg = msg or ""
    return [("fg:gray", f"  {msg}"), ("", "\n")]

def _fmt_notice(text: str) -> list[tuple[str, str]]:
    text = text or ""
    return [("", "\n"), ("fg:ansiyellow", f"⚡ {text}"), ("", "\n")]


# ═══════════════════════════════════════════════════════
# 辅助：文本裁剪 + 终端宽度（保证单行渲染）
# ═══════════════════════════════════════════════════════

def _term_width() -> int:
    import shutil
    try:
        return max(shutil.get_terminal_size().columns, 60)
    except Exception:
        return 80

def _clip(text: str, max_w: int) -> str:
    """截断文本使不超过 max_w 个字符，追加 ... 标记。"""
    if len(text) <= max_w:
        return text
    return text[:max(0, max_w - 1)] + "…"

# ═══════════════════════════════════════════════════════
# 选项解析
# ═══════════════════════════════════════════════════════

def extract_options(text: str) -> tuple[list[dict], str] | None:
    mq_split = re.split(r"^\s*##\s*问题\s*\d+", text, maxsplit=1, flags=re.MULTILINE)
    text = mq_split[0]
    options = []
    for m in re.finditer(r"\[(\d+)\]\s*(.+?)(?=\n(?:——|\[(?:\d+)\])|\n*$)", text, re.DOTALL):
        num = int(m.group(1)); desc = m.group(2).strip().rstrip(".。,， ")
        if desc.startswith("——"): options.append({"num": num, "text": "", "separator": True})
        else: options.append({"num": num, "text": desc})
    i = 0
    while i < len(options) - 1:
        if options[i].get("separator") or options[i+1].get("separator"): i += 1; continue
        if options[i+1]["num"] != options[i]["num"] + 1:
            options.insert(i + 1, {"num": 0, "text": "——", "separator": True})
        i += 1
    real = [o for o in options if not o.get("separator")]
    if len(real) < 2: return None
    first = re.search(r"^\[(\d+)\]", text, re.MULTILINE)
    question = text[:first.start()].strip() if first else ""
    return options, question


def extract_multi_questions(text: str) -> list[dict] | None:
    blocks = re.split(r"^\s*##\s*问题\s*(\d+)", text, flags=re.MULTILINE)
    if len(blocks) < 3: return None
    questions = []; i = 1
    while i + 1 < len(blocks):
        h_num = int(blocks[i].strip()); body = blocks[i + 1]; i += 2
        r = extract_options(body); q_text = ""
        if r: _, q_text = r; opts = r[0]
        else:
            opts = []
            for line in body.strip().split("\n"):
                m = re.match(r'^\s*\[(\d+)\]\s*(.+)', line)
                if m: opts.append({"num": int(m.group(1)), "text": m.group(2).strip()})
            if not opts: continue
        questions.append({"num": h_num, "text": q_text, "options": opts})
    return questions if len(questions) >= 2 else None


# ═══════════════════════════════════════════════════════
# KeeniusApp
# ═══════════════════════════════════════════════════════

class KeeniusApp:
    """统一 prompt_toolkit Application — 所有交互（REPL、picker、session、curriculum）
    在一个 layout tree 中通过 _render_body() 切换内容。"""
    def __init__(self, loop, slash_handler=None, messages=None):
        self.loop = loop
        self.state = AppState()
        if messages:
            self.state.messages = messages
        self._slash_handler = slash_handler
        self._msg_buffer = Buffer(multiline=False, name="input")
        self._input_control = BufferControl(buffer=self._msg_buffer)
        # 原地编辑 buffer（选项编辑 / 会话重命名 / 大纲编辑 共用）
        self._edit_buffer = Buffer(multiline=False, name="edit",
                                   on_text_changed=lambda _: self._invalidate())
        self._edit_control = BufferControl(buffer=self._edit_buffer)
        self._sessions = []
        self._on_session_selected = None
        self._pending_options = None  # (options_list, question) 未完成的选项
        self._build()
        _log(f"KeeniusApp init: mode={self.state.mode}, msgs={len(self.state.messages)}, sessions={len(self._sessions)}")

    def set_session_handler(self, handler):
        self._on_session_selected = handler

    def _load_history(self, messages: list[dict]):
        """加载历史消息。遵循旧版 run_shell_with_session 的规则：
        - 已完成的交互 → 格式化显示
        - 最后一条助手消息如果有选项且未被回答 → 不加载，保存为待激活 picker
        """
        _log(f"_load_history: {len(messages)} messages")
        if not messages:
            return

        # 找到最后一条有内容的助手消息
        last_assistant_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "assistant" and messages[i].get("content"):
                last_assistant_idx = i
                break

        # 检查它是否有选项且未被回答（助手消息后没有用户消息）
        pending_opts = None
        pending_question = ""
        if last_assistant_idx >= 0:
            last_content = messages[last_assistant_idx].get("content", "") or ""
            opt_result = extract_options(last_content)
            # 判断是否未回答：助手消息是最后一条，或者后面只有 system/tool 消息
            has_user_after = any(
                m.get("role") == "user"
                for m in messages[last_assistant_idx + 1:]
            )
            if opt_result and not has_user_after:
                pending_opts, pending_question = opt_result
                self._pending_options = (pending_opts, pending_question)
                _log(f"_load_history: found pending options ({len(pending_opts)}), will re-activate picker")

        # 遍历消息 — 只设置 pending_options，不添加到 messages
        # 历史消息已通过 Rich 打印到终端 scrollback
        for i, msg in enumerate(messages):
            role = msg.get("role", "")
            content = msg.get("content", "") or ""
            reasoning = msg.get("reasoning_content", "") or ""
            if not content.strip() and not reasoning.strip():
                continue
            # 不调用 add_message — 消息在终端 scrollback 中
        _log(f"_load_history done: total raw={len(messages)}, pending={pending_opts is not None}")

    # ── 一次性创建所有 widget / filter / layout ──

    def _build(self):
        st = self.state

        # -- Keybinding filter（只创建一次） --
        self._f_repl = Condition(lambda: st.mode == "repl")
        self._f_repl_idle = Condition(lambda: st.mode == "repl" and not st.thinking)
        self._f_session_nav = Condition(lambda: st.mode == "session" and not st.sp_renaming)
        self._f_session = Condition(lambda: st.mode == "session")
        self._f_session_rename = Condition(lambda: st.mode == "session" and not st.sp_renaming and st.sp_cursor < len(self._sessions))
        self._f_question_nav = Condition(lambda: st.mode == "question" and not st.qp_editing)
        self._f_question = Condition(lambda: st.mode == "question")
        self._f_multi_q = Condition(lambda: st.mode == "multi_q")
        self._f_curriculum_nav = Condition(lambda: st.mode == "curriculum" and not st.cv_editing)
        self._f_curriculum = Condition(lambda: st.mode == "curriculum")
        self._f_curriculum_edit = Condition(lambda: st.mode == "curriculum" and st.cv_editing)

        # -- 唯一 body control：根据 mode 渲染不同内容，无 layout 切换 --
        self._body_ctrl = FormattedTextControl(text=self._render_body, focusable=False)
        self._body_win = Window(self._body_ctrl, wrap_lines=True,
                                height=Dimension(weight=1), allow_scroll_beyond_bottom=True)
        # -- 编辑模式 filter：选项编辑 / 会话重命名 / 大纲编辑共用 --
        self._f_editing = Condition(lambda: st.qp_editing or st.sp_renaming or st.cv_editing)
        self._f_not_editing = Condition(lambda: not (st.qp_editing or st.sp_renaming or st.cv_editing))
        # -- REPL 输入区 filter：仅在 repl/multi_q 模式且非编辑时显示 --
        self._f_show_repl_input = Condition(
            lambda: st.mode in ("repl", "multi_q") and not (st.qp_editing or st.sp_renaming or st.cv_editing))

        self._status_ctrl = FormattedTextControl(text=self._render_status, focusable=False)
        self._input_prefix_ctrl = FormattedTextControl(
            text=lambda: FormattedText([("class:prompt", "\n❯ ")]), focusable=False)
        self._input_win = Window(self._input_control, height=1)
        self._edit_win = Window(self._edit_control, height=1)
        self._status_win = Window(self._status_ctrl, height=1, style="class:status-bar")

        from prompt_toolkit.layout import VSplit
        # -- root layout：body + edit(条件) + prompt+input / status --
        self._root_container = HSplit([
            self._body_win,
            ConditionalContainer(self._edit_win, filter=self._f_editing),
            ConditionalContainer(
                VSplit([
                    Window(self._input_prefix_ctrl, width=3, height=1),
                    self._input_win,
                ]),
                filter=self._f_show_repl_input,
            ),
            self._status_win,
        ])

        self._app = Application(
            layout=Layout(self._root_container, focused_element=self._input_control),
            key_bindings=self._build_keybindings(),
            style=APP_STYLE,
            full_screen=False,
            output=create_output(),
            input=create_input(),
        )

    # ── Render ──

    def _render_body(self) -> FormattedText:
        """唯一 body render：mode 决定内容，layout 结构不变。"""
        st = self.state
        if st.mode == "repl":
            return self._render_messages()
        elif st.mode == "question":
            return self._render_messages_with_picker(self._render_question())
        elif st.mode == "multi_q":
            return self._render_messages_with_picker(self._render_multi_q())
        elif st.mode == "session":
            return self._render_messages_with_picker(self._render_session())
        elif st.mode == "curriculum":
            return self._render_messages_with_picker(self._render_curriculum())
        return self._render_messages()

    def _render_messages_with_picker(self, picker_fragments) -> FormattedText:
        """picker 模式：消息已通过 Rich 打印到终端 scrollback，body 只渲染 picker。"""
        return FormattedText(picker_fragments)

    def _render_messages(self) -> FormattedText:
        parts: list[tuple[str, str]] = []
        for msg in self.state.messages:
            parts.extend(msg)
        if not parts:
            bc = "fg:ansicyan bold"
            w = _term_width() - 6
            parts.append((bc, "╭─ Keenius ─"))
            parts.append((bc, "─" * (w - 12)))
            parts.append((bc, "╮\n"))
            parts.append((bc, "│ "))
            parts.append(("", _pad("输入问题开始对话...", w - 4)))
            parts.append((bc, " │"))
            parts.append(("", "\n"))
            parts.append((bc, "╰"))
            parts.append((bc, "─" * (w - 2)))
            parts.append((bc, "╯\n"))
        if self.state.thinking:
            _SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
            idx = int(_time.time() * 8) % len(_SPIN)
            parts.append(("", "\n"))
            parts.append(("fg:gray", f"  {_SPIN[idx]} 思考中...\n"))
        return FormattedText(parts)

    def _render_question(self) -> FormattedText:
        st = self.state
        w = _term_width() - 6; max_w = w
        f: list[tuple[str, str]] = []

        bc = "fg:ansiyellow" if st.qp_editing else ("fg:ansiblue bold" if st.qp_is_multi else "fg:ansicyan bold")
        title = "编辑选项" if st.qp_editing else ("请选择（可多选）" if st.qp_is_multi else "请选择")
        f.append((bc, "┏━━ "))
        f.append((bc, f"{title} "))
        f.append((bc, "━" * (w - 2 - _display_width(title))))
        f.append((bc, "┓\n"))

        if st.qp_question:
            f.append((bc, "┃ "))
            f.append(("fg:white bold", _pad(_clip(st.qp_question, max_w), max_w)))
            f.append((bc, " ┃"))
            f.append(("", "\n"))
            f.append((bc, "┃ "))
            f.append((bc, "─" * max_w))
            f.append((bc, " ┃"))
            f.append(("", "\n"))

        for i, opt in enumerate(st.qp_options):
            if opt.get("separator"):
                f.append((bc, "┃ "))
                f.append(("fg:gray italic", _pad(f"  ── {opt['text']}"[:max_w], max_w)))
                f.append((bc, " ┃"))
                f.append(("", "\n"))
                continue
            sel = i == st.qp_cursor
            chk = "✓" if i in st.qp_checked else " "
            txt = _clip(opt["text"], max_w - 4)
            if st.qp_editing and sel:
                edit_txt = _clip(self._edit_buffer.text, max_w - 6)
                content = f" ✎ [{opt['num']}] {edit_txt}"
                f.append((bc, "┃ "))
                f.append(("reverse", _pad(content[:max_w], max_w)))
                f.append((bc, " ┃"))
                f.append(("", "\n"))
            elif sel:
                content = f" [{chk}] [{opt['num']}] {txt}"
                f.append((bc, "┃ "))
                f.append(("reverse", _pad(content[:max_w], max_w)))
                f.append((bc, " ┃"))
                f.append(("", "\n"))
            else:
                dm = "✓" if i in st.qp_checked else " "
                content = f"  [{dm}] [{opt['num']}] {txt}"
                f.append((bc, "┃ "))
                f.append(("", _pad(content[:max_w], max_w)))
                f.append((bc, " ┃"))
                f.append(("", "\n"))

        if st.qp_checked:
            f.append((bc, "┃ "))
            f.append(("bold fg:ansigreen", _pad(f" 已选 {len(st.qp_checked)} 项", max_w)))
            f.append((bc, " ┃"))
            f.append(("", "\n"))
        hint = "✎ 编辑中  Enter确认  Esc取消" if st.qp_editing else "↑↓选  Space编辑  +多选  Enter确认  Esc取消"
        f.append((bc, "┃ "))
        f.append(("fg:gray", _pad(hint, max_w)))
        f.append((bc, " ┃"))
        f.append(("", "\n"))
        f.append((bc, "┗"))
        f.append((bc, "━" * (w + 2)))
        f.append((bc, "┛\n"))
        f.append(("", "\n"))

        ibc = "fg:ansicyan bold" if st.qp_editing else "fg:gray"
        inp_title = "输入"
        f.append((ibc, "┏━━ "))
        f.append((ibc, f"{inp_title} "))
        f.append((ibc, "━" * (w - 2 - _display_width(inp_title))))
        f.append((ibc, "┓\n"))
        if st.qp_editing:
            f.append((ibc, "┃ "))
            f.append(("fg:white bold", _pad(f" ▸ {self._edit_buffer.text} ▌", max_w)))
            f.append((ibc, " ┃"))
            f.append(("", "\n"))
        else:
            f.append((ibc, "┃ "))
            f.append(("fg:gray", _pad(" ▸ 在此输入补充文字...", max_w)))
            f.append((ibc, " ┃"))
            f.append(("", "\n"))
        f.append((ibc, "┗"))
        f.append((ibc, "━" * (w + 2)))
        f.append((ibc, "┛\n"))
        f.append(("", "\n"))
        return FormattedText(f)

    def _render_multi_q(self) -> FormattedText:
        st = self.state; f: list[tuple[str, str]] = []
        max_w = _term_width() - 12  # 前缀 " ▶ [N] " 的宽度
        for qi, q in enumerate(st.mq_questions):
            focus = qi == st.mq_q_idx
            f.append(("bold fg:ansicyan" if focus else "fg:gray",
                      f"Q{qi+1}/{len(st.mq_questions)}: {_clip(q.get('text',''), 60)}\n"))
            for oi, opt in enumerate(q.get("options", [])):
                cur = oi == st.mq_o_idx[qi]; sel = st.mq_selected[qi] == oi
                txt = _clip(opt["text"], max_w)
                if focus and cur: f.append(("reverse", f" ▶ [{opt['num']}] {txt}\n"))
                elif sel: f.append(("bold fg:ansigreen", f"   ✓ [{opt['num']}] {txt}\n"))
                else: f.append(("", f"     [{opt['num']}] {txt}\n"))
            f.append(("", "\n"))
        all_ok = all(s is not None for s in st.mq_selected)
        if all_ok: f.append(("bold fg:ansigreen", "全部已答 — Enter 确认\n"))
        else: f.append(("fg:ansiyellow", f"⚠ {[i+1 for i,s in enumerate(st.mq_selected) if s is None]} 未选\n"))
        f.append(("fg:gray", "← →:Q ↑↓:opt Space:sel Enter:confirm Esc:cancel\n"))
        return FormattedText(f)

    def _render_session(self) -> FormattedText:
        st = self.state; sessions = self._sessions
        w = _term_width() - 6; inner_w = w
        f: list[tuple[str, str]] = []

        bc = "fg:ansicyan bold" if not st.sp_renaming else "fg:ansiyellow bold"
        title = "会话列表" if not st.sp_renaming else "重命名"
        pad_title = f" {title} "
        f.append((bc, "┏"))
        f.append((bc, "━" * (w - _display_width(pad_title))))
        f.append((bc, f"{pad_title}"))
        f.append((bc, "━━"))
        f.append((bc, "┓\n"))

        for i, s in enumerate(sessions):
            pin = "📌" if s["name"] == st.sp_pinned_name else " "
            subj = (s.get("subject") or "(无主题)")[:14]
            src = "项目" if s.get("source") == "project" else "全局"
            msg_n = f"{s.get('messages', 0)}条"
            time_str = s.get("saved_at", "")[:16]

            if st.sp_renaming and i == st.sp_cursor:
                content = f" {pin} ✎ {self._edit_buffer.text}▌"
                f.append((bc, "┃ "))
                f.append(("fg:ansiyellow", _pad(content[:inner_w], inner_w)))
                f.append((bc, " ┃"))
                f.append(("", "\n"))
            elif i == st.sp_cursor:
                content = f"▶ {pin} {s['name'][:24]}  {subj}  {msg_n}  {time_str}  {src}"
                f.append((bc, "┃ "))
                f.append(("reverse", _pad(content[:inner_w], inner_w)))
                f.append((bc, " ┃"))
                f.append(("", "\n"))
            else:
                content = f"  {pin} {s['name'][:24]}  {subj}  {msg_n}  {time_str}  {src}"
                f.append((bc, "┃ "))
                f.append(("fg:gray", _pad(content[:inner_w], inner_w)))
                f.append((bc, " ┃"))
                f.append(("", "\n"))

        if st.sp_cursor == len(sessions):
            f.append((bc, "┃ "))
            f.append(("reverse", _pad(" ＋ 新建会话", inner_w)))
            f.append((bc, " ┃"))
            f.append(("", "\n"))
        else:
            f.append((bc, "┃ "))
            f.append(("fg:gray", _pad("  新建会话", inner_w)))
            f.append((bc, " ┃"))
            f.append(("", "\n"))

        if st.sp_renaming:
            f.append((bc, "┃ "))
            f.append(("fg:ansiyellow bold", _pad("✎ 编辑中  Enter=确认  Esc=取消", inner_w)))
            f.append((bc, " ┃"))
            f.append(("", "\n"))
        else:
            f.append((bc, "┃ "))
            f.append(("fg:gray", _pad("↑↓选择  Enter打开  Space重命名  P固定  N新建  Q退出", inner_w)))
            f.append((bc, " ┃"))
            f.append(("", "\n"))
        if st.sp_pinned_name:
            f.append((bc, "┃ "))
            f.append(("fg:ansiyellow", _pad(f"📌 已固定: {st.sp_pinned_name}（启动时自动加载）", inner_w)))
            f.append((bc, " ┃"))
            f.append(("", "\n"))

        f.append((bc, "┗"))
        f.append((bc, "━" * (w + 2)))
        f.append((bc, "┛\n"))
        f.append(("", "\n"))
        return FormattedText(f)

    def _render_curriculum(self) -> FormattedText:
        st = self.state; w = _term_width() - 6; inner_w = w
        f: list[tuple[str, str]] = []
        items, _ = st.cv_stack[-1] if st.cv_stack else ([], "")
        crumbs = " > ".join(t for _, t in st.cv_stack)

        bc = "fg:ansiyellow" if st.cv_editing else "fg:ansicyan bold"
        title = f"📋 {crumbs}"[:50]
        f.append((bc, "┏━━ "))
        f.append((bc, f"{title} "))
        f.append((bc, "━" * (w - 2 - _display_width(title))))
        f.append((bc, "┓\n"))

        for i, node in enumerate(items):
            sel = i == st.cv_cursor
            icon = node.get("icon", "  ")
            node_title = node.get("title", "")[:50]
            arrow = " ▶" if node.get("children") else "  "
            if st.cv_editing and sel:
                content = f" ✎ {self._edit_buffer.text}"
                f.append((bc, "┃ "))
                f.append(("reverse", _pad(content[:inner_w], inner_w)))
                f.append((bc, " ┃"))
                f.append(("", "\n"))
            elif sel:
                content = f" {icon} {node_title} {arrow}"
                f.append((bc, "┃ "))
                f.append(("reverse", _pad(content[:inner_w], inner_w)))
                f.append((bc, " ┃"))
                f.append(("", "\n"))
            else:
                content = f" {icon} {node_title} {arrow}"
                f.append((bc, "┃ "))
                f.append(("", _pad(content[:inner_w], inner_w)))
                f.append((bc, " ┃"))
                f.append(("", "\n"))

        f.append((bc, "┃ "))
        f.append(("fg:gray", _pad("↑↓选  →进入  ←返回  Space编辑  Esc退出", inner_w)))
        f.append((bc, " ┃"))
        f.append(("", "\n"))
        f.append((bc, "┗"))
        f.append((bc, "━" * (w + 2)))
        f.append((bc, "┛\n"))
        f.append(("", "\n"))
        return FormattedText(f)

    def _render_status(self) -> FormattedText:
        st = self.state
        labels = {"repl": "输入", "question": "选择", "multi_q": "多选", "session": "会话", "curriculum": "大纲"}
        phase_icons = {"diagnosis": "🔍 诊断中", "planning": "📋 制定计划", "learning": "📖 教学中", "end": "🏁 总结"}
        phase_styles = {"diagnosis": "class:status-bar.phase", "planning": "class:status-bar.phase",
                        "learning": "class:status-bar.phase", "end": "class:status-bar.info"}
        phase_text = phase_icons.get(st.phase, st.phase)
        return FormattedText([
            (phase_styles.get(st.phase, "class:status-bar.phase"), f" {phase_text} "),
            ("class:status-bar.info",
             f" │ {getattr(self.loop, 'model', '?')} │ {getattr(self.loop, 'turn_count', 0)} 轮 │ {labels.get(st.mode, st.mode)}"),
        ])

    # ── LLM 调用（异步 — 后台线程 + 流式回调） ──

    def _call_llm(self, text: str, as_user: bool = True):
        """同步调用 LLM。阻塞事件循环直到返回。
        LLM 调用期间拦截 display.print_tool_call/result 的 Rich 输出（避免双渲染器冲突），
        改为收集为 FormattedText 消息。
        """
        _log(f"_call_llm: text='{text[:50]}', as_user={as_user}, mode={self.state.mode}")
        if as_user and text.strip():
            self.add_message(_fmt_user(text.strip()))
        self.state.thinking = True
        self._invalidate()

        # 拦截 Rich 工具调用输出，避免直接写终端绕过 prompt_toolkit screen buffer
        collected_tools: list = []
        import keenius.agent.display as _display
        _orig_tc = _display.print_tool_call
        _orig_tr = _display.print_tool_result
        def _capture_tc(name, preview=""): collected_tools.append(("call", name, preview))
        def _capture_tr(preview="", success=True): collected_tools.append(("result", preview))
        _display.print_tool_call = _capture_tc
        _display.print_tool_result = _capture_tr

        try:
            _log(f"_call_llm: calling loop.send_message...")
            response = self.loop.send_message(text.strip())
            _log(f"_call_llm: response len={len(response) if response else 0}")
        except Exception as e:
            _log(f"_call_llm ERROR: {e}")
            self._on_llm_error(str(e))
            return
        finally:
            _display.print_tool_call = _orig_tc
            _display.print_tool_result = _orig_tr

        self._on_llm_response(response, collected_tools)

    def _on_llm_response(self, response: str, collected_tools: list | None = None):
        _log(f"_on_llm_response: len={len(response) if response else 0}, mode={self.state.mode}")
        self.state.thinking = False

        # 收集到的工具调用 → 格式化为消息
        if collected_tools:
            for kind, *args in collected_tools:
                if kind == "call":
                    self.add_message(_fmt_tool(args[0], args[1] if len(args) > 1 else ""))
                elif kind == "result":
                    self.add_message(_fmt_tool_result(args[0] if args else ""))

        reasoning = getattr(self.loop, '_last_reasoning', '')
        if reasoning:
            self.add_message(_fmt_reasoning(reasoning[:400]))

        mq = extract_multi_questions(response)
        if mq:
            _log(f"_on_llm_response: multi_q detected ({len(mq)} questions)")
            self.enter_multi_question(mq)
            self._invalidate()
            return

        opts = extract_options(response)
        if opts:
            o, q = opts
            _log(f"_on_llm_response: options detected ({len(o)} opts)")
            if q:
                self.add_message(_fmt_assistant(q))
            self.enter_question_picker(*opts)
            return

        _log(f"_on_llm_response: plain text, adding to messages")
        self.add_message(_fmt_assistant(response))
        self._auto_save()
        self._invalidate()

    def _on_llm_error(self, msg: str):
        _log(f"_on_llm_error: {msg}")
        self.state.thinking = False
        self.add_message(_fmt_error(msg)); self._invalidate()

    def _auto_save(self):
        if getattr(self.loop, 'turn_count', 0) > 0:
            try: self.loop.save()
            except Exception: pass

    # ── 模式切换 ──

    def enter_question_picker(self, options: list[dict], question: str):
        st = self.state
        st.qp_options = options
        st.qp_question = question
        st.qp_cursor = 0
        st.qp_checked.clear()
        st.qp_editing = False
        st.qp_is_multi = "可多选" in question
        while st.qp_cursor < len(options) and options[st.qp_cursor].get("separator"):
            st.qp_cursor += 1
        st.mode = "question"  # 最后写 mode
        self._invalidate()

    def enter_multi_question(self, questions: list[dict]):
        st = self.state
        st.mq_questions = questions
        st.mq_q_idx = 0
        st.mq_o_idx = [0] * len(questions)
        st.mq_selected = [None] * len(questions)
        st.mode = "multi_q"  # 最后写 mode
        self._invalidate()

    def enter_session_picker(self, sessions: list[dict]):
        from keenius.agent.sessions import get_pin_config
        pin = get_pin_config()
        st = self.state
        st.sp_sessions = sessions
        st.sp_cursor = 0
        st.sp_renaming = False
        st.sp_pinned_name = pin.get("auto_load", "")
        self._sessions = sessions
        self._msg_buffer.text = ""
        st.mode = "session"  # 最后写 mode
        self._invalidate()

    def enter_curriculum(self, plan: dict):
        from keenius.cli.shell import _plan_to_tree
        tree = _plan_to_tree(plan)
        st = self.state
        st.cv_cursor = 0
        st.cv_stack = [(tree, plan.get("subject", "大纲"))]
        st.cv_editing = False
        st.mode = "curriculum"  # 最后写 mode
        self._invalidate()

    # ── 消息 ──

    def add_message(self, parts: list[tuple[str, str]]):
        self.state.messages.append(parts)

    def _invalidate(self):
        try: self._app.invalidate()
        except Exception: pass

    # ── KeyBindings ──

    def _build_keybindings(self) -> KeyBindings:
        kb = KeyBindings(); st = self.state
        f = self  # 用于在闭包中引用 self 的预建 filter

        @kb.add("c-c")
        def _(event): event.app.exit()

        @kb.add("c-d", filter=self._f_repl)
        def _(event): event.app.exit()

        # ── REPL ──
        @kb.add("enter", filter=self._f_repl_idle)
        def _(event):
            text = self._msg_buffer.text; self._msg_buffer.text = ""
            if not text.strip(): return
            if text.strip().startswith("/") and self._slash_handler:
                r = self._slash_handler(text.strip())
                if r == "EXIT": event.app.exit(); return
                if r: self.add_message(_fmt_info(r)); self._invalidate()
                return
            self._call_llm(text.strip())

        @kb.add("escape", "enter", filter=self._f_repl)
        def _(event): self._msg_buffer.insert_text("\n")

        # ── SessionPicker ──
        @kb.add("up", filter=self._f_session_nav)
        def _(event): st.sp_cursor = (st.sp_cursor - 1) % (len(self._sessions) + 1); self._invalidate()

        @kb.add("down", filter=self._f_session_nav)
        def _(event): st.sp_cursor = (st.sp_cursor + 1) % (len(self._sessions) + 1); self._invalidate()

        @kb.add("enter", filter=self._f_session)
        def _(event):
            if st.sp_renaming:
                new_name = self._edit_buffer.text.strip()
                if new_name and st.sp_cursor < len(self._sessions):
                    _rename(self._sessions[st.sp_cursor], new_name)
                    self._sessions[st.sp_cursor]["name"] = new_name
                self._edit_buffer.text = ""; st.sp_renaming = False
                event.app.layout.focus(self._input_control)
            elif st.sp_cursor < len(self._sessions):
                s = self._sessions[st.sp_cursor]; st.mode = "repl"
                if self._on_session_selected: self._on_session_selected(s)
            else:
                st.mode = "repl"
                if self._on_session_selected: self._on_session_selected("NEW")

        @kb.add("space", filter=self._f_session_rename)
        def _(event):
            st.sp_renaming = True
            self._edit_buffer.text = self._sessions[st.sp_cursor]["name"]
            event.app.layout.focus(self._edit_control)

        @kb.add("escape", filter=self._f_session)
        def _(event):
            if st.sp_renaming:
                st.sp_renaming = False; self._edit_buffer.text = ""
                event.app.layout.focus(self._input_control)
            else: st.mode = "repl"; self._on_session_selected and self._on_session_selected(None)

        @kb.add("n", filter=self._f_session_nav)
        @kb.add("N", filter=self._f_session_nav)
        def _(event): st.mode = "repl"; self._on_session_selected and self._on_session_selected("NEW")

        @kb.add("q", filter=self._f_session_nav)
        @kb.add("Q", filter=self._f_session_nav)
        def _(event): st.mode = "repl"; self._on_session_selected and self._on_session_selected(None)

        @kb.add("p", filter=self._f_session_rename)
        @kb.add("P", filter=self._f_session_rename)
        def _(event):
            from keenius.agent.sessions import set_pinned_session, clear_pinned_session
            s = self._sessions[st.sp_cursor]
            if s["name"] == st.sp_pinned_name: clear_pinned_session(); st.sp_pinned_name = ""
            else: set_pinned_session(s["name"], s["source"]); st.sp_pinned_name = s["name"]

        # ── QuestionPicker ──
        @kb.add("up", filter=self._f_question_nav)
        def _(event): st.qp_cursor = st._next_real(st.qp_cursor, -1); self._invalidate()

        @kb.add("down", filter=self._f_question_nav)
        def _(event): st.qp_cursor = st._next_real(st.qp_cursor, 1); self._invalidate()

        @kb.add("tab", filter=self._f_question_nav)
        def _(event): st.qp_cursor = st._next_real(st.qp_cursor, 1); self._invalidate()

        @kb.add("enter", filter=self._f_question)
        def _(event):
            if st.qp_editing:
                new_text = self._edit_buffer.text.strip()
                if new_text: st.qp_options[st.qp_cursor]["text"] = new_text
                st.qp_editing = False; self._edit_buffer.text = ""
                event.app.layout.focus(self._input_control)
            elif st.qp_is_multi and not st.qp_checked:
                return
            elif st.qp_checked:
                result = "；".join(st.qp_options[i]["text"] for i in sorted(st.qp_checked))
                st.qp_checked.clear(); st.mode = "repl"
                self.add_message(_fmt_user(result))
                self._call_llm(result, as_user=False)
            else:
                result = st.qp_options[st.qp_cursor]["text"]
                st.mode = "repl"
                self.add_message(_fmt_user(result))
                self._call_llm(result, as_user=False)

        @kb.add("space", filter=self._f_question_nav)
        def _(event):
            if not st.qp_options[st.qp_cursor].get("separator"):
                st.qp_editing = True
                self._edit_buffer.text = st.qp_options[st.qp_cursor]["text"]
                event.app.layout.focus(self._edit_control)

        @kb.add("escape", filter=self._f_question)
        def _(event):
            if st.qp_editing:
                st.qp_editing = False; self._edit_buffer.text = ""
                event.app.layout.focus(self._input_control)
            elif st.qp_checked: st.qp_checked.clear()
            else: st.mode = "repl"

        @kb.add("+", filter=self._f_question_nav)
        @kb.add("=", filter=self._f_question_nav)
        def _(event):
            i = st.qp_cursor
            if not st.qp_options[i].get("separator"):
                if i in st.qp_checked: st.qp_checked.discard(i)
                else: st.qp_checked.add(i)

        # ── MultiQuestion ──
        @kb.add("up", filter=self._f_multi_q)
        def _(event):
            opts = st.mq_questions[st.mq_q_idx].get("options", [])
            if opts: st.mq_o_idx[st.mq_q_idx] = (st.mq_o_idx[st.mq_q_idx] - 1) % len(opts)
            self._invalidate()

        @kb.add("down", filter=self._f_multi_q)
        def _(event):
            opts = st.mq_questions[st.mq_q_idx].get("options", [])
            if opts: st.mq_o_idx[st.mq_q_idx] = (st.mq_o_idx[st.mq_q_idx] + 1) % len(opts)
            self._invalidate()

        @kb.add("left", filter=self._f_multi_q)
        def _(event): st.mq_q_idx = (st.mq_q_idx - 1) % len(st.mq_questions); self._invalidate()

        @kb.add("right", filter=self._f_multi_q)
        def _(event): st.mq_q_idx = (st.mq_q_idx + 1) % len(st.mq_questions); self._invalidate()

        @kb.add("space", filter=self._f_multi_q)
        def _(event): st.mq_selected[st.mq_q_idx] = st.mq_o_idx[st.mq_q_idx]; self._invalidate()

        @kb.add("enter", filter=self._f_multi_q)
        def _(event):
            if not all(s is not None for s in st.mq_selected): return
            answers = []
            for qi, s in enumerate(st.mq_selected):
                q = st.mq_questions[qi]
                answers.append(f"问题{q['num']}：{q['options'][s]['text']}")
            result = "；".join(answers)
            st.mode = "repl"; st.mq_questions = []
            self.add_message(_fmt_user(result))
            self._call_llm(result, as_user=False)

        @kb.add("escape", filter=self._f_multi_q)
        def _(event): st.mode = "repl"; st.mq_questions = []

        # ── CurriculumViewer ──
        @kb.add("up", filter=self._f_curriculum_nav)
        def _(event):
            items, _ = st.cv_stack[-1] if st.cv_stack else ([], "")
            if items: st.cv_cursor = (st.cv_cursor - 1) % len(items); self._invalidate()

        @kb.add("down", filter=self._f_curriculum_nav)
        def _(event):
            items, _ = st.cv_stack[-1] if st.cv_stack else ([], "")
            if items: st.cv_cursor = (st.cv_cursor + 1) % len(items); self._invalidate()

        @kb.add("right", filter=self._f_curriculum_nav)
        @kb.add("enter", filter=self._f_curriculum_nav)
        def _(event):
            items, _ = st.cv_stack[-1] if st.cv_stack else ([], "")
            if items and st.cv_cursor < len(items):
                kids = items[st.cv_cursor].get("children", [])
                if kids: st.cv_stack.append((kids, items[st.cv_cursor].get("title", ""))); st.cv_cursor = 0
                self._invalidate()

        @kb.add("left", filter=self._f_curriculum_nav)
        def _(event):
            if len(st.cv_stack) > 1: st.cv_stack.pop(); st.cv_cursor = 0; self._invalidate()

        @kb.add("space", filter=self._f_curriculum_nav)
        def _(event):
            items, _ = st.cv_stack[-1] if st.cv_stack else ([], "")
            if items and st.cv_cursor < len(items):
                st.cv_editing = True
                self._edit_buffer.text = items[st.cv_cursor].get("title", "")
                event.app.layout.focus(self._edit_control)
                self._invalidate()

        @kb.add("enter", filter=self._f_curriculum_edit)
        def _(event):
            items, _ = st.cv_stack[-1] if st.cv_stack else ([], "")
            new_text = self._edit_buffer.text.strip()
            if new_text and items and st.cv_cursor < len(items):
                items[st.cv_cursor]["title"] = new_text
            st.cv_editing = False; self._edit_buffer.text = ""
            event.app.layout.focus(self._input_control)

        @kb.add("escape", filter=self._f_curriculum)
        def _(event):
            if st.cv_editing:
                st.cv_editing = False; self._edit_buffer.text = ""
                event.app.layout.focus(self._input_control)
            else: st.mode = "repl"

        return kb

    # ── 回调 ──

    def set_session_handler(self, handler):
        self._on_session_selected = handler

    # ── API ──

    def run(self):
        self._app.run()

    def exit(self):
        self._app.exit()


# ── 辅助 ──

def _rename(s: dict, new_name: str):
    from keenius.agent.sessions import sessions_dir
    old = sessions_dir() / f"{s['name']}.json"
    new = sessions_dir() / f"{new_name}.json"
    if old.exists() and not new.exists(): old.rename(new)
