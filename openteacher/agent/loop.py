"""The core conversation loop for the OpenTeacher agent.

This is the heart of the agent — it handles the back-and-forth between
the user, the LLM, and tool execution.
"""

from __future__ import annotations
import json
from typing import Any
from openteacher import config
from openteacher.agent import api_client, display
from openteacher.tools.registry import registry
from openteacher.tutor.prompts import build_system_prompt


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

    def start(self) -> str:
        """Initialize the conversation with the system prompt. Returns opening message."""
        system_prompt = build_system_prompt(
            subject=self.subject,
            language=self.language,
            teaching_style=self.teaching_style,
        )
        self.messages = [{"role": "system", "content": system_prompt}]
        self.running = True

        with display.spinner("正在与 AI 导师建立连接..."):
            response = self._call_llm(with_tools=False)

        assistant_msg = response.choices[0].message.content or ""
        self.messages.append({"role": "assistant", "content": assistant_msg})
        return assistant_msg

    def send_message(self, user_input: str) -> str:
        """Process a user message and return the assistant response.

        This runs one or more iterations of the agent loop:
        1. Send user message + history to LLM
        2. If LLM returns tool calls, execute them and loop
        3. If LLM returns text, return it to the user
        """
        self.turn_count += 1
        if self.turn_count > self.max_turns:
            return "已达到本轮对话的最大轮次限制。请输入 /new 开始新对话。"

        self.messages.append({"role": "user", "content": user_input})

        with display.spinner("思考中..."):
            return self._run_agent_loop()

    def _run_agent_loop(self) -> str:
        """Inner loop: call LLM, handle tool calls, repeat until final response."""
        tools = registry.get_tool_definitions()
        max_iterations = 5  # max tool-calling iterations per user turn

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
        """Execute tool calls and add results to messages."""
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

            tool_results.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                }
            )

        self.messages.append(
            {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ],
            }
        )
        self.messages.extend(tool_results)

    def reset(self) -> None:
        """Reset the conversation."""
        self.messages = []
        self.turn_count = 0

    @property
    def history_length(self) -> int:
        return len(self.messages)
