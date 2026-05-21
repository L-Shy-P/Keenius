"""Tool registry for OpenTeacher.

Tools are OpenAI-compatible function definitions that the LLM can call.
Register tools here and they become available to the teaching agent.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

Handler = Callable[..., str | Awaitable[str]]


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler
    require_confirmation: bool = False


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        require_confirmation: bool = False,
    ) -> Callable[[Handler], Handler]:
        """Decorator to register a tool handler."""

        def decorator(handler: Handler) -> Handler:
            self._tools[name] = ToolDef(
                name=name,
                description=description,
                parameters=parameters,
                handler=handler,
                require_confirmation=require_confirmation,
            )
            return handler

        return decorator

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI-compatible tool definitions for enabled tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    def get_tool(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def execute(self, name: str, **kwargs) -> str:
        """Execute a tool by name and return its result."""
        tool = self.get_tool(name)
        if tool is None:
            return f"[ERROR] Unknown tool: {name}"
        try:
            return tool.handler(**kwargs)
        except Exception as e:
            return f"[ERROR] Tool '{name}' failed: {e}"

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())


def tool_result(data: dict | str = None, **kwargs) -> str:
    """Standard tool success result. Accepts dict or keyword args. Returns JSON string.

    Usage:
        tool_result({"content": "...", "lines": 42})
        tool_result(success=True, count=10)
    """
    import json
    if isinstance(data, str):
        return json.dumps({"result": data}, ensure_ascii=False)
    if data is not None:
        return json.dumps(data, ensure_ascii=False)
    return json.dumps(kwargs, ensure_ascii=False)


def tool_error(message: str, **extra) -> str:
    """Standard tool error result. Returns JSON string with error key.

    Usage:
        tool_error("文件不存在: /path/to/file")
        tool_error("写入失败", code=403)
    """
    import json
    return json.dumps({"error": message, **extra}, ensure_ascii=False)


# Global tool registry
registry = ToolRegistry()
register_tool = registry.register
