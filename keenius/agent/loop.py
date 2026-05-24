"""Keenius agent 的核心对话循环。"""

from __future__ import annotations
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from keenius import config
from keenius.agent import api_client, display
from keenius.tools.registry import registry
from keenius.tutor.prompts import build_system_prompt

SESSIONS_DIR = config.SESSIONS_DIR


def _ensure_sessions_dir() -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


class ConversationLoop:
    """管理一次教学会话的对话循环。"""

    def __init__(
        self,
        subject: str = "",
        language: str = "zh",
        teaching_style: str = "socratic",
        model: str | None = None,
    ) -> None:
        self.subject = subject
        self.language = language
        self.teaching_style = teaching_style
        self.model = model or config.get_model()
        self.temperature = config.get_config_value("temperature", 0.7)
        self.max_turns = config.get_config_value("max_turns", 200)

        self.messages: list[dict[str, Any]] = []
        self.turn_count = 0
        self.running = False
        self.phase = "diagnosis"  # diagnosis → planning → learning → end
        self.mode = "mixed"  # guided / direct / mixed
        self._created_at = datetime.now().isoformat()
        self._session_name: str | None = None
        self._pending_notice: str | None = None  # 下轮 LLM 调用时的系统通知
        self._last_reasoning: str = ""  # 最近一次推理内容，供显示用

    def _inject_notice(self) -> None:
        """将待发送的系统通知注入消息列表，让 LLM 看到。"""
        if self._pending_notice:
            self.messages.append({"role": "user", "content": f"[系统通知] {self._pending_notice}"})
            self._pending_notice = None

    def notify_llm(self, note: str) -> None:
        """将系统通知加入队列，LLM 下一轮会看到。"""
        self._pending_notice = note

    def start(self) -> None:
        """初始化对话：加载系统提示词。不调用 API，静默启动。"""
        system_prompt = build_system_prompt(
            subject=self.subject,
            language=self.language,
            teaching_style=self.teaching_style,
            phase=self.phase,
        )
        self.messages = [{"role": "system", "content": system_prompt}]
        self.running = True

    def _auto_compress(self) -> None:
        """压缩旧的对话历史以保持在上下文窗口内。

        当消息超过 15 对用户/助手消息时，将最早的部分总结
        并替换为一条紧凑的摘要消息。
        保留系统提示词 + 最近 6 条消息不变。
        """
        # 统计用户/助手消息数（不含系统提示词）
        user_msgs = [m for m in self.messages if m["role"] in ("user", "assistant")]
        if len(user_msgs) <= 15:
            return  # 无需压缩

        # 保留最后 6 条消息，压缩其余
        keep_count = 6
        to_compress = user_msgs[:-keep_count]

        # 构建待总结的对话文本
        conv_text = []
        for m in to_compress:
            role_label = "学生" if m["role"] == "user" else "老师"
            content = (m.get("content") or "")[:500]
            conv_text.append(f"[{role_label}]: {content}")

        # 调用 LLM 生成摘要（非流式）
        try:
            response = api_client.call_llm(
                messages=[
                    {"role": "system", "content": "你是一个对话压缩器。将以下教学对话压缩为一段简洁的摘要（中文，200字以内），保留：学了什么、学生掌握程度、当前进度。只输出摘要。"},
                    {"role": "user", "content": "\n".join(conv_text)},
                ],
                tools=None,
                model=self.model,
                temperature=0.3,
                stream=False,
            )
            summary = response.choices[0].message.content.strip()
        except Exception:
            # 如果摘要生成失败，直接裁剪旧消息
            summary = f"（已讨论 {len(to_compress)} 轮对话，内容较长已省略）"

        # 重建：系统提示词 + 摘要 + 最后 8 条消息（保留工具消息）
        sys_msg = self.messages[0] if self.messages and self.messages[0]["role"] == "system" else None
        recent = self.messages[-8:]  # 保留用户/助手之间的工具消息

        new_messages = []
        if sys_msg:
            new_messages.append(sys_msg)
        new_messages.append({
            "role": "system",
            "content": f"[对话摘要] {summary}"
        })
        new_messages.extend(recent)

        self.messages = new_messages
        self.turn_count = len([m for m in new_messages if m["role"] == "user"])

    def send_message(self, user_input: str) -> str:
        """处理用户消息并返回助手回复。"""
        if not self.running:
            self.start()

        self.turn_count += 1
        # 安全阀：仍然执行硬限制，但阈值更高
        if self.turn_count > self.max_turns:
            self.notify_llm("对话轮次过多，请总结当前教学进度并建议学生开始新的学习主题。")

        # 上下文过长时自动压缩
        self._auto_compress()

        self.messages.append({"role": "user", "content": user_input})
        return self._run_agent_loop()

    def _run_agent_loop(self) -> str:
        max_iterations = 8
        for _ in range(max_iterations):
            response = self._stream_llm()
            if response is None:
                return "（没有收到有效回复，请重试）"
            self._detect_phase_transition(response)
            return response
        return "（工具调用次数过多，请简化你的问题）"

    def _detect_phase_transition(self, response: str) -> None:
        """根据 LLM 操作自动推进阶段。"""
        # 检查本轮是否调用了工具
        # 根据上下文和回复内容判断阶段切换
        if self.phase == "diagnosis":
            # 如果 LLM 开始讨论教学策略或课程，进入 planning 阶段
            if any(kw in response for kw in ["教学方针", "学习计划", "课程大纲", "教学策略"]):
                self.phase = "planning"
                self._update_system_prompt()
        elif self.phase == "planning":
            # 如果 LLM 开始上课，进入 learning 阶段
            if any(kw in response for kw in ["开始上课", "第一课", "第 1 课", "📖 第"]):
                self.phase = "learning"
                self._update_system_prompt()

    def _update_system_prompt(self) -> None:
        """为当前阶段重新构建系统提示词。"""
        new_prompt = build_system_prompt(
            subject=self.subject, language=self.language,
            teaching_style=self.teaching_style, phase=self.phase,
        )
        if self.messages and self.messages[0]["role"] == "system":
            self.messages[0] = {"role": "system", "content": new_prompt}

    def set_phase(self, new_phase: str) -> None:
        """手动设置阶段并更新系统提示词。"""
        if new_phase in ("diagnosis", "planning", "learning", "end"):
            self.phase = new_phase
            self._update_system_prompt()

    def _stream_llm(self) -> str | None:
        """流式传输 LLM 回复，使用 Hermes 风格的边框面板。

        内容以纯文本形式在 ╭─ Keenius ──╮ / ╰──────────╯ 框中流式输出。
        当检测到 [N] 选项时，将其标记，调用者（shell）在流式完成后
        显示交互式键盘选择器。选择后，结果追加到历史记录并递归调用本方法。
        """

        tools = registry.get_tool_definitions()

        # 将待发送的系统通知注入消息，让 LLM 看到
        self._inject_notice()

        stream = api_client.call_llm(
            messages=self.messages,
            tools=tools or None,
            model=self.model,
            temperature=self.temperature,
            stream=True,
        )

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_call_buffer: dict[int, dict] = {}  # index → {id, name, args_str}
        options_active: bool = False  # 流式传输期间的视觉样式标记

        # ── 旋转动画 ──
        _SPIN_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        _spin_i = 0

        def _spinner_text():
            nonlocal _spin_i
            c = _SPIN_CHARS[_spin_i % len(_SPIN_CHARS)]
            _spin_i += 1
            return f"[dim]{c} 思考中...[/dim]"

        # ── 选项解析 ──
        _OPT_RE = re.compile(r"^\[(\d+)\]\s*(.+)$")
        _MQ_HEADING_RE = re.compile(r"^\s*##\s*问题\s*(\d+)\s*")

        def _parse_opts(lines_slice):
            """从行列表中解析 [N] 选项。返回 (opts, pre_text, post_text) 或 None。
            —— 分隔行被忽略（不追加到选项文本）。"""
            opt_indices = [j for j, ln in enumerate(lines_slice) if _OPT_RE.match(ln)]
            if len(opt_indices) < 2:
                return None
            first, last = opt_indices[0], opt_indices[-1]
            pre = "\n".join(lines_slice[:first]).strip()
            opts = []
            for j in opt_indices:
                m = _OPT_RE.match(lines_slice[j])
                if m:
                    # 只取第一行；后续的 —— 分隔行被忽略
                    opts.append({"num": int(m.group(1)), "text": m.group(2).rstrip(".。,， ")})
            post_lines = [ln for ln in lines_slice[last + 1:] if not ln.strip().startswith("——")]
            post = "\n".join(post_lines).strip()
            return opts, pre, post

        def _split_stream(text: str):
            """返回 (pre, opts_list, post) 或 None（单问题）。
            遇到 ## 标题时截断，防止多问题块合并。"""
            lines = text.split("\n")
            # 在第一个 ## 标题处截断，避免跨问题合并
            heading_idx = None
            for i, ln in enumerate(lines):
                if _MQ_HEADING_RE.match(ln):
                    heading_idx = i
                    break
            if heading_idx is not None and heading_idx > 0:
                lines = lines[:heading_idx]
            result = _parse_opts(lines)
            if result is None:
                return None
            opts, pre, post = result
            return pre, opts, post

        def _split_multi_stream(text: str):
            """返回 {num, text, options} 列表或 None（多问题）。"""
            lines = text.split("\n")
            # 查找 ## 问题 N 标题
            headings = []  # (num, line_index)
            for i, ln in enumerate(lines):
                m = _MQ_HEADING_RE.match(ln)
                if m:
                    headings.append((int(m.group(1)), i))
            if len(headings) < 2:
                return None
            questions = []
            for qi, (h_num, h_start) in enumerate(headings):
                h_end = headings[qi + 1][1] if qi + 1 < len(headings) else len(lines)
                block_lines = lines[h_start + 1:h_end]  # 跳过标题行
                result = _parse_opts(block_lines)
                if result is None:
                    continue
                opts, pre, _post = result
                questions.append({"num": h_num, "text": pre, "options": opts})
            return questions if len(questions) >= 2 else None



        def _check_truncation():
            """检查流终止原因，并为 LLM 排队相应的通知。"""
            if finish_reason is None:
                self.notify_llm("上一条回复在输出过程中被中断（可能是网络波动或连接断开），消息可能不完整。")
            elif finish_reason == "length":
                self.notify_llm("上一条回复因 token 数量达到上限被截断，消息不完整。请继续或总结。")
            elif finish_reason == "content_filter":
                self.notify_llm("上一条回复因内容安全策略被拦截，部分内容未输出。")

        # ── 主循环：带自然滚动的流式输出 ──
        # 纯文本 → console.print 终端原生滚动。
        # 检测到选项 → 切换到 Live 面板。
        finish_reason: str | None = None

        try:
            for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                if choice is None:
                    continue
                delta = choice.delta
                if delta is None:
                    continue
                if choice.finish_reason:
                    finish_reason = choice.finish_reason

                if getattr(delta, "reasoning_content", None):
                    reasoning_parts.append(delta.reasoning_content)

                if delta.content:
                    content_parts.append(delta.content)
                    display.console.print(delta.content, end="", markup=False)

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx_tc = tc.index
                        if idx_tc not in tool_call_buffer:
                            tool_call_buffer[idx_tc] = {"id": tc.id or "", "name": tc.function.name if tc.function else "", "args": ""}
                        buf = tool_call_buffer[idx_tc]
                        if tc.id:
                            buf["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                buf["name"] = tc.function.name
                            if tc.function.arguments:
                                buf["args"] += tc.function.arguments

                if content_parts and not options_active:
                    text = "".join(content_parts)
                    if _split_stream(text) or _split_multi_stream(text):
                        options_active = True

            display.console.print()

            if tool_call_buffer:
                text = "".join(content_parts)
                self._handle_streamed_tool_calls(tool_call_buffer, text, "".join(reasoning_parts))
                return self._run_agent_loop()

            if content_parts:
                final_text = "".join(content_parts)
                final_reasoning = "".join(reasoning_parts)
                self._store_assistant_msg(final_text, final_reasoning)
                # 如果存在推理内容，显示（Hermes 风格 dim 框）
                if final_reasoning:
                    self._last_reasoning = final_reasoning
                _check_truncation()
                return final_text

            return None
        except Exception as exc:
            display.console.print()
            if content_parts:
                final_text = "".join(content_parts)
                final_reasoning = "".join(reasoning_parts)
                self._store_assistant_msg(final_text, final_reasoning)
                try:
                    if not options_active:
                        display.print_response_panel(final_text, self.phase)
                except Exception:
                    pass
            self._classify_error(exc)
            raise


    def _classify_error(self, exc: Exception) -> None:
        """根据异常类型为 LLM 排队适当的系统通知。"""
        import openai
        if isinstance(exc, openai.AuthenticationError):
            self.notify_llm("API Key 验证失败，上一轮对话请求被中断。")
        elif isinstance(exc, openai.RateLimitError):
            self.notify_llm("API 调用频率超限，上一轮对话请求被中断。")
        elif isinstance(exc, openai.APITimeoutError):
            self.notify_llm("API 请求超时，上一轮对话请求未完成。")
        elif isinstance(exc, openai.APIConnectionError):
            self.notify_llm("网络连接失败，上一轮对话请求未完成。")
        elif isinstance(exc, openai.InternalServerError):
            self.notify_llm("API 服务器内部错误（500），上一轮对话请求失败。")
        elif isinstance(exc, openai.BadRequestError):
            self.notify_llm(f"API 请求格式错误 ({exc.status_code})，上一轮对话请求失败。请检查消息格式。")
        elif isinstance(exc, openai.APIStatusError):
            self.notify_llm(f"API 返回错误状态码 {exc.status_code}，上一轮对话请求失败。")
        elif "API" in str(exc).upper() or "api" in str(exc):
            self.notify_llm(f"API 配置问题，上一轮对话请求失败：{str(exc)[:100]}")
        elif "timeout" in str(exc).lower():
            self.notify_llm("请求超时，上一轮对话未完成。可能是网络延迟或服务器繁忙。")
        else:
            msg = str(exc)[:150]
            self.notify_llm(f"程序运行中出现错误，上一轮对话请求未完成。{msg}")

    def _store_assistant_msg(self, text: str, reasoning: str = "") -> None:
        """将助手回复存储到对话历史中。"""
        if not text:
            return
        msg: dict = {"role": "assistant", "content": text}
        if reasoning:
            msg["reasoning_content"] = reasoning
        self.messages.append(msg)

    def _finish_option_selection(self, assistant_text: str, reasoning: str, selected: str) -> None:
        """存储助手消息和用户选择，然后打印确认信息。"""
        self._store_assistant_msg(assistant_text, reasoning)
        self.messages.append({"role": "user", "content": selected})
        from rich.markup import escape as _e
        display.console.print(f"  [dim]已选择: {_e(selected[:80])}[/dim]")
        display.console.print()

    def _handle_streamed_tool_calls(self, tool_call_buffer: dict, prefix_text: str, reasoning: str = "") -> None:
        """从流式工具调用构建消息，执行工具，并存入历史记录。"""
        tool_msgs = []
        for idx in sorted(tool_call_buffer.keys()):
            buf = tool_call_buffer[idx]
            name = buf["name"]
            args_preview = buf["args"][:50] + "..." if len(buf["args"]) > 50 else buf["args"]
            display.print_tool_call(name, args_preview)
            try:
                args = json.loads(buf["args"])
            except json.JSONDecodeError:
                args = {}
            tool_def = registry.get_tool(name)
            if tool_def:
                result = tool_def.handler(**args)
            else:
                result = f"未知工具: {name}"
            display.print_tool_result(result)
            tool_msgs.append({
                "role": "tool",
                "tool_call_id": buf["id"],
                "content": result,
            })

        assistant_msg: dict = {
            "role": "assistant",
            "content": prefix_text or None,
            "tool_calls": [
                {
                    "id": buf["id"],
                    "type": "function",
                    "function": {"name": buf["name"], "arguments": buf["args"]},
                }
                for buf in tool_call_buffer.values()
            ],
        }
        if reasoning:
            assistant_msg["reasoning_content"] = reasoning
        self.messages.append(assistant_msg)
        self.messages.extend(tool_msgs)

    def reset(self) -> None:
        self.messages = []
        self.turn_count = 0
        self.running = False
        self._session_name = None

    # ── 会话持久化 ────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "subject": self.subject,
            "language": self.language,
            "teaching_style": self.teaching_style,
            "model": self.model,
            "temperature": self.temperature,
            "turn_count": self.turn_count,
            "phase": self.phase,
            "session_name": self._session_name,

            "created_at": self._created_at,
            "saved_at": datetime.now().isoformat(),
            "messages": self.messages,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ConversationLoop:
        loop = cls(
            subject=data.get("subject", ""),
            language=data.get("language", "zh"),
            teaching_style=data.get("teaching_style", "socratic"),
            model=data.get("model"),
        )
        loop.temperature = data.get("temperature", 0.7)
        loop.turn_count = data.get("turn_count", 0)
        loop.phase = data.get("phase", "diagnosis")

        loop._created_at = data.get("created_at", datetime.now().isoformat())
        loop._session_name = data.get("session_name")
        loop.messages = data.get("messages", [])
        loop.running = True
        return loop

    def save(self, name: str | None = None) -> str:
        """保存会话到 ~/.keenius/sessions/。"""
        save_name = name or self._session_name or _auto_session_name(self)
        self._session_name = save_name

        from keenius.agent.sessions import sessions_dir
        target_dir = sessions_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        filepath = target_dir / f"{save_name}.json"
        filepath.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return save_name

    def load(self, name: str) -> bool:
        """从 ~/.keenius/sessions/ 加载会话。成功返回 True。"""
        from keenius.agent.sessions import sessions_dir
        filepath = sessions_dir() / f"{name}.json"
        if filepath.exists():
            data = json.loads(filepath.read_text(encoding="utf-8"))
            loaded = self.from_dict(data)
            self.__dict__.update(loaded.__dict__)
            self._session_name = name
            return True
        return False

    @staticmethod
    def list_sessions() -> list[dict]:
        """列出所有保存的会话（使用 sessions 模块的 scan_sessions）。"""
        from keenius.agent.sessions import scan_sessions
        return scan_sessions()

    @property
    def history_length(self) -> int:
        return len(self.messages)


def _auto_session_name(loop: ConversationLoop) -> str:
    """从最后一条用户消息生成默认会话名称，截断处理。"""
    for m in reversed(loop.messages):
        if m.get("role") == "user" and m.get("content"):
            text = m["content"].strip().replace("\n", " ")
            if len(text) > 30:
                text = text[:30] + "..."
            if text:
                return text
    base = loop.subject.replace(" ", "-") if loop.subject else "session"
    date_str = datetime.now().strftime("%Y%m%d-%H%M")
    return f"{base}-{date_str}"
