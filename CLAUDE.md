# Keenius CLI Standards

## 强制规则

### 始终对标 Claude Code 和 Hermes Agent 的 CLI 标准格式

参考源码：
- Hermes: `c:\Users\L_Shy_P user\Desktop\Code\Python\Projects\Hermes\hermes-agent-main\`
- Claude Code: `c:\Users\L_Shy_P user\Desktop\Code\Python\Projects\Claude Code\`

### 工具格式标准
- 每个工具必须有: name, description, parameters (JSON Schema with type/object/properties/required)
- 成功用 `tool_result(data)` 返回 JSON
- 失败用 `tool_error(message)` 返回 JSON `{"error": "..."}`
- 文件读: `read_file(file_path, offset, limit)` — 带行号的 cat -n 格式
- 文件写: `write_file(file_path, content)` — 安全限制到 ~/.keenius/ 和项目目录
- 命令行: `SLASH_COMMANDS` 按 category 分组的 dict，包含 desc 和 action

### 交互标准
- 纯 REPL，所有操作通过 `/` 斜杠命令
- 选择界面：↑↓/Tab 移动，Enter 确认，Esc 取消，Space 备注
- 纯键盘交互，不依赖输入框数字选择
- Ctrl+Enter 换行、Ctrl+D 退出
- LLM 诊断一次一个问题，带 `[1]`-`[5]` 选项
- 底部工具栏显示阶段/模式/模型

### 教学标准
- 极简直觉讲解：一句话给核心关系，不给口诀
- 学生画像三层：学科层(C/S轴) + 认知层(记忆模式/优势/速度/自律) + 性格层
- 三阶段流程：diagnosis → learning → end
- 每课结构：定义原文 + 直观解释 + 方法典例 + 当堂测试 + 拓展内容

### 项目结构
- 包名 Keenius，命令 Keenius
- 配置 ~/.keenius/，计划 ~/.keenius/plans/，画像 ~/.keenius/profiles/
- 核心文件: tutor/prompts.py（提示词）、cli/shell.py（REPL）、agent/loop.py（对话循环）
- 工具: tools/builtin.py（教学工具）、tools/registry.py（注册系统）
