"""The core conversation loop for the OpenTeacher agent."""

from __future__ import annotations
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from openteacher import config
from openteacher.agent import api_client, display
from openteacher.tools.registry import registry
from openteacher.tutor.prompts import build_system_prompt

SESSIONS_DIR = config.DATA_DIR / "sessions"


def _ensure_sessions_dir() -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


class ConversationLoop:
    """Manages one teaching session's conversation loop."""

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
        self.max_turns = config.get_config_value("max_turns", 20)

        self.messages: list[dict[str, Any]] = []
        self.turn_count = 0
        self.running = False
        self._created_at = datetime.now().isoformat()
        self._session_name: str | None = None

    def start(self) -> None:
        """Initialize the conversation with system prompt. No API call — silent start."""
        system_prompt = build_system_prompt(
            subject=self.subject,
            language=self.language,
            teaching_style=self.teaching_style,
        )
        self.messages = [{"role": "system", "content": system_prompt}]
        self.running = True

    def send_message(self, user_input: str) -> str:
        """Process a user message and return the assistant response."""
        if not self.running:
            self.start()

        self.turn_count += 1
        if self.turn_count > self.max_turns:
            return "已达到本轮对话的最大轮次限制。请输入 /new 开始新对话。"

        self.messages.append({"role": "user", "content": user_input})

        with display.spinner("思考中..."):
            return self._run_agent_loop()

    def _run_agent_loop(self) -> str:
        tools = registry.get_tool_definitions()
        max_iterations = 5

        for _ in range(max_iterations):
            response = self._call_llm(with_tools=bool(tools))
            choice = response.choices[0]
            message = choice.message

            if message.tool_calls:
                self._handle_tool_calls(message)
                continue
            elif message.content:
                self.messages.append({"role": "assistant", "content": message.content})
                return message.content
            else:
                return "（没有收到有效回复，请重试）"

        return "（工具调用次数过多，请简化你的问题）"

    def _call_llm(self, with_tools: bool = True):
        tools = registry.get_tool_definitions() if with_tools else None
        return api_client.call_llm(
            messages=self.messages,
            tools=tools,
            model=self.model,
            temperature=self.temperature,
            stream=False,
        )

    def _handle_tool_calls(self, message) -> None:
        tool_results = []
        for tc in message.tool_calls:
            tool_name = tc.function.name
            tool_def = registry.get_tool(tool_name)
            if tool_def is None:
                result = f"未知工具: {tool_name}"
            else:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                display.print_tool_call(tool_name, args)
                result = tool_def.handler(**args)
                display.print_tool_result(result)

            tool_results.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

        self.messages.append({
            "role": "assistant",
            "content": message.content,
            "tool_calls": [
                {"id": tc.id, "type": "function", "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }}
                for tc in message.tool_calls
            ],
        })
        self.messages.extend(tool_results)

    def reset(self) -> None:
        self.messages = []
        self.turn_count = 0
        self.running = False
        self._session_name = None

    # ── Session persistence ────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "subject": self.subject,
            "language": self.language,
            "teaching_style": self.teaching_style,
            "model": self.model,
            "temperature": self.temperature,
            "turn_count": self.turn_count,
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
        loop._created_at = data.get("created_at", datetime.now().isoformat())
        loop.messages = data.get("messages", [])
        loop.running = True
        return loop

    def save(self, name: str | None = None) -> str:
        """Save session to disk. Returns the session name."""
        _ensure_sessions_dir()
        save_name = name or self._session_name or _auto_session_name(self)
        self._session_name = save_name
        filepath = SESSIONS_DIR / f"{save_name}.json"
        filepath.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return save_name

    def load(self, name: str) -> bool:
        """Load session from disk. Returns True on success."""
        filepath = SESSIONS_DIR / f"{name}.json"
        if not filepath.exists():
            return False
        data = json.loads(filepath.read_text(encoding="utf-8"))
        loaded = self.from_dict(data)
        self.__dict__.update(loaded.__dict__)
        self._session_name = name
        return True

    @staticmethod
    def list_sessions() -> list[dict]:
        """List all saved sessions with metadata."""
        _ensure_sessions_dir()
        sessions = []
        for f in sorted(SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                sessions.append({
                    "name": f.stem,
                    "subject": data.get("subject", ""),
                    "model": data.get("model", ""),
                    "messages": len(data.get("messages", [])),
                    "created_at": data.get("created_at", "")[:16],
                    "saved_at": data.get("saved_at", "")[:16],
                })
            except json.JSONDecodeError:
                continue
        return sessions

    @property
    def history_length(self) -> int:
        return len(self.messages)


def _auto_session_name(loop: ConversationLoop) -> str:
    """Generate a default session name from subject and date."""
    base = loop.subject.replace(" ", "-") if loop.subject else "session"
    date_str = datetime.now().strftime("%Y%m%d-%H%M")
    return f"{base}-{date_str}"
