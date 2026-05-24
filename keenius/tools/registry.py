"""Keenius 工具注册系统。

工具是 LLM 可以调用的 OpenAI 兼容函数定义。
在此注册工具后，教学 agent 即可使用它们。
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
        """装饰器：注册工具处理函数。"""

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
        """返回已启用工具的 OpenAI 兼容工具定义列表。"""
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
        """按名称执行工具并返回其结果。"""
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
    """标准工具成功结果。接受字典或关键字参数，返回 JSON 字符串。

    用法：
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
    """标准工具错误结果。返回包含 error 键的 JSON 字符串。

    用法：
        tool_error("文件不存在: /path/to/file")
        tool_error("写入失败", code=403)
    """
    import json
    return json.dumps({"error": message, **extra}, ensure_ascii=False)


# 全局工具注册表
registry = ToolRegistry()
register_tool = registry.register
