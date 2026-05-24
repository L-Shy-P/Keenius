# Keenius 架构文档

## 概述

Keenius 是一个 CLI AI 导师，帮助自学者高效、扎实地掌握任何学科。
对标 Claude Code / Hermes Agent 的交互模式，但专注于教学场景。

## 项目结构

```
Keenius/
├── ARCHITECTURE.md               ← 你正在读的文件
├── pyproject.toml                ← 项目元数据 & 依赖 & console_scripts 入口
├── .env.example                  ← API Key 配置模板（用户复制为 .env）
├── .gitignore
│
├── config/
│   └── config.yaml.example       ← 教学设置模板（复制到 ~/.keenius/config.yaml）
│
├── Keenius/                  ← 主包
│   ├── __init__.py               ← 版本号
│   ├── __main__.py               ← `python -m Keenius` 入口 → cli.main
│   ├── config.py                 ← 配置管理（.env + YAML + 目录结构）
│   │
│   ├── cli/                      ← CLI 层
│   │   ├── main.py               ← argparse 入口（仅解析 -s/-l/-m 等 flag→启动 REPL）
│   │   └── shell.py              ← prompt_toolkit REPL 核心
│   │       ├── SlashCompleter      Tab 补全
│   │       ├── Key bindings        Ctrl+D/Alt+Enter/Ctrl+C
│   │       ├── Slash commands      /setup /config /profile /save /load /sessions ...
│   │       └── run_shell()         主 REPL 循环
│   │
│   ├── agent/                    ← Agent 层
│   │   ├── api_client.py         ← OpenAI 兼容 API 调用（stream/非stream）
│   │   ├── loop.py               ← ConversationLoop：对话循环 & 会话持久化
│   │   │   ├── start()             初始化 system prompt（不发 API 调用）
│   │   │   ├── send_message()      发送用户消息 → 返回 LLM 回复
│   │   │   ├── _stream_llm()       token 级别流式输出（Rich Live）
│   │   │   ├── save() / load()     会话 JSON 存档
│   │   │   └── list_sessions()     列出历史会话
│   │   └── display.py            ← Rich 终端美化输出（欢迎横幅/工具调用/流式显示）
│   │
│   ├── tutor/                    ← 教学层（你主要修改这里）
│   │   └── prompts.py            ← 系统提示词 + 学生画像框架 + 学科适配
│   │       ├── STUDENT_PROFILE_FRAMEWORK  学生画像系统（C轴/S轴/动机）
│   │       ├── SYSTEM_PROMPT_TEMPLATE     主提示词模板
│   │       ├── SUBJECT_AUGMENTS          学科专项提示词
│   │       └── build_system_prompt()     组装最终提示词
│   │
│   └── tools/                    ← 工具层
│       ├── registry.py           ← ToolRegistry：@register_tool 装饰器注册
│       └── builtin.py            ← 内置教学工具（8个工具）
│           ├── create_quiz / check_answer
│           ├── give_examples / explain_deeper
│           ├── summarize_lesson / spaced_review_reminder
│           ├── assess_student / track_progress / save_note
│
├── scripts/
│   └── install.ps1              ← Windows 安装脚本（可选）
│
└── tests/
    ├── test_prompts.py
    └── test_tools.py
```

## 数据流

```
用户输入 "我想学 Python"
        │
        ▼
┌─────────────────┐
│  shell.py       │  prompt_toolkit REPL
│  ❯ 提示符       │
└────────┬────────┘
         │ 非 / 命令 → loop.send_message()
         │ / 命令   → handle_slash_command()
         ▼
┌─────────────────┐
│  loop.py        │  ConversationLoop
│  _stream_llm()  │  → 流式调用 LLM
└────────┬────────┘
         │
    ┌────┴────┐
    │ 有工具调用?  │──Yes──→ 执行工具 → 追加结果 → 循环
    │          │
    └────┬────┘
         │ No
         ▼
    display.py 流式渲染 Markdown → 返回文本
         │
         ▼
    shell.py 打印分隔线 → 等待下次输入
```

## 配置系统

三层配置，后者覆盖前者：

| 优先级 | 位置 | 内容 |
|--------|------|------|
| 低 | `config.py::DEFAULT_CONFIG` | 硬编码默认值 |
| 中 | `~/.keenius/config.yaml` | 教学设置（模型/语言/风格） |
| 高 | `~/.keenius/.env` | API Key / Base URL |

## 运行时数据目录

```
~/.keenius/
├── .env                          ← API Key（/setup 写入）
├── config.yaml                   ← 教学设置
├── profiles/
│   └── default.json              ← 学生画像（Agent 自动构建）
│       ├── learning_orientation   ← 学习倾向
│       ├── concept_levels{}       ← C轴：每个概念的理解层级 C0-C4
│       ├── skill_levels{}         ← S轴：每个技能的应用层级 S0-S4
│       └── history[]              ← 评估历史记录
├── data/
│   ├── sessions/                 ← 会话存档（/save /load）
│   │   └── *.json
│   ├── progress.json             ← 学习进度
│   ├── student_profile.json      ← 旧版画像（已被 profiles/ 替代）
│   └── chat_history.txt          ← prompt_toolkit 输入历史
```

## 工具系统

### 注册新工具

```python
# 在 builtin.py 中
from keenius.tools.registry import register_tool

@register_tool(
    name="my_tool",
    description="工具描述（LLM 据此决定何时调用）",
    parameters={
        "type": "object",
        "properties": {
            "arg1": {"type": "string", "description": "参数说明"},
        },
        "required": ["arg1"],
    },
)
def my_tool(arg1: str) -> str:
    return f"结果: {arg1}"
```

工具会被自动传递给 LLM 作为 function calling schema。LLM 决定何时调用、传什么参数。

### 工具持久化

在 `shell.py::monkeypatch_track_progress()` 中，可以给工具 handler 加持久化钩子。
参考 `track_progress` 和 `assess_student` 的处理方式。

## 学生画像系统

### 维度

| 维度 | 键 | 取值 |
|------|-----|------|
| 学习倾向 | learning_orientation | theory/practice/exam/curiosity/project |
| 概念掌握度 | concept_levels (C轴) | C0-C4（见 prompts.py） |
| 应用能力 | skill_levels (S轴) | S0-S4（见 prompts.py） |

### C/S 独立评估

- C轴（概念）：知道多少、理解多深。对文科来说包括：概念辨析、理论框架、背景知识
- S轴（应用）：能做什么。编程→写代码；数学→解题证明；文科→分析写作、论证、文本解读

### 画像构建流程

1. Agent 根据学科类型自适应选择诊断方式
2. 首次对话通过自然提问评估
3. 教学过程中持续更新
4. `/profile` 命令可查看当前画像
5. 数据持久化在 `~/.keenius/profiles/default.json`

## 修改指南

| 你要改什么 | 改哪个文件 |
|------------|-----------|
| Agent 人格 / 教学策略 | `Keenius/tutor/prompts.py` |
| 添加教学工具 | `Keenius/tools/builtin.py` |
| 修改 REPL 命令 | `Keenius/cli/shell.py`（SLASH_COMMANDS 字典） |
| 修改终端样式 | `Keenius/agent/display.py` |
| 修改快捷键 | `Keenius/cli/shell.py`（bindings） |
| 修改配置项 | `Keenius/config.py`（DEFAULT_CONFIG 字典） |
| 修改 API 调用逻辑 | `Keenius/agent/api_client.py` |
| 修改会话存储格式 | `Keenius/agent/loop.py`（to_dict/from_dict） |

## 安装与使用

```bash
# 从项目目录安装（开发模式）
pip install -e .

# 启动
Keenius                  # 默认
Keenius -s 机器学习       # 指定主题
Keenius -l en            # 英文教学
Keenius -m deepseek-chat # 指定模型

# REPL 内命令
/setup     配置 API
/config    查看配置
/profile   查看学生画像
/save      保存会话
/load      加载会话
/sessions  会话列表
/progress  学习进度
/new       重置对话
/subject   切换主题
/style     切换风格
/help      帮助
/quit      退出
```
