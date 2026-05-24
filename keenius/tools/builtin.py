"""Keenius agent 的内置教学工具。

所有工具描述均为中文，因为主要教学语言是中文。
工具通过 @register_tool 装饰器注册 —— 只需导入此模块即可让 agent 使用它们。
"""

from keenius.tools.registry import register_tool, tool_result, tool_error

# ═══════════════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════════════


def _is_under_dir(p, d):
    """检查路径 p 是否在目录 d 下（安全：使用 Path.is_relative_to）。"""
    try:
        p.relative_to(d)
        return True
    except ValueError:
        return False


# ============================================================
# 标准文件 I/O 工具（Claude Code / Hermes 兼容格式）
# ============================================================


@register_tool(
    name="read_file",
    description=(
        "读取文件内容。支持文本文件和 PDF。返回带行号的内容。"
        "使用绝对路径。要读取大文件时使用 offset 和 limit 参数分段读取。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "要读取的文件的绝对路径",
            },
            "offset": {
                "type": "integer",
                "description": "起始行号（1-indexed，默认 1）",
                "default": 1,
                "minimum": 1,
            },
            "limit": {
                "type": "integer",
                "description": "最大读取行数（默认 500，最大 2000）",
                "default": 500,
                "maximum": 2000,
            },
        },
        "required": ["file_path"],
    },
)
def read_file(file_path: str, offset: int = 1, limit: int = 500) -> str:
    from pathlib import Path

    p = Path(file_path).expanduser().resolve()
    if not p.exists():
        return tool_error(f"文件不存在: {file_path}")
    if p.is_dir():
        return tool_error(f"路径是目录而非文件: {file_path}")

    try:
        content = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return tool_error(f"无法以 UTF-8 解码文件（可能是二进制文件）: {file_path}")
    except Exception as e:
        return tool_error(f"读取失败: {e}")

    lines = content.splitlines()
    total = len(lines)
    start = max(0, offset - 1)
    end = min(start + limit, total)
    selected = lines[start:end]

    # 带行号的输出（匹配 Claude Code `cat -n` 格式）
    numbered = "\n".join(f"{start + i + 1:6d}\t{line}" for i, line in enumerate(selected))

    result = {
        "content": numbered,
        "total_lines": total,
        "start_line": start + 1,
        "end_line": end,
        "truncated": end < total,
    }
    if result["truncated"]:
        result["hint"] = f"文件还有 {total - end} 行。使用 offset={end + 1} 继续读取。"
    return tool_result(result)


@register_tool(
    name="write_file",
    description=(
        "将内容写入文件。会完全覆盖已有内容。"
        "只能写入 ~/.keenius/ 目录或当前项目目录下的文件。"
        "不会自动创建父目录——如需创建目录请先用 Bash 工具。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "要写入的文件的绝对路径",
            },
            "content": {
                "type": "string",
                "description": "要写入文件的完整内容",
            },
        },
        "required": ["file_path", "content"],
    },
)
def write_file(file_path: str, content: str) -> str:
    from pathlib import Path

    p = Path(file_path).expanduser().resolve()
    allowed_dirs = [
        Path.home() / ".keenius",
        Path.cwd(),
    ]
    if not any(_is_under_dir(p, d) for d in allowed_dirs):
        return tool_error(
            f"安全限制：只能写入 ~/.keenius/ 或当前项目目录下的文件。\n"
            f"目标路径: {file_path}"
        )

    try:
        existed = p.exists()
        p.parent.mkdir(parents=True, exist_ok=True)
        old_size = p.stat().st_size if existed else 0
        p.write_text(content, encoding="utf-8")
        new_size = p.stat().st_size
        action = "更新" if existed else "创建"
        return tool_result({
            "action": action,
            "file_path": str(p),
            "bytes_written": new_size,
            "previous_bytes": old_size if existed else 0,
        })
    except Exception as e:
        return tool_error(f"写入失败: {e}")


# ============================================================
# 测验与评估工具
# ============================================================


@register_tool(
    name="create_quiz",
    description="根据当前教学内容生成小测验，包含选择题、判断题和简答题，帮助学生检验理解程度。",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "测验主题"},
            "question_count": {
                "type": "integer",
                "description": "题目数量，默认 3",
                "default": 3,
            },
            "difficulty": {
                "type": "string",
                "enum": ["easy", "medium", "hard"],
                "description": "难度等级",
                "default": "medium",
            },
        },
        "required": ["topic"],
    },
)
def create_quiz(topic: str, question_count: int = 3, difficulty: str = "medium", **_) -> str:
    return (
        f"📝 **生成测验**: {topic}\n"
        f"难度: {difficulty} | 题目数量: {question_count}\n"
        "请在下一轮对话中直接输出测验题目。"
    )


@register_tool(
    name="check_answer",
    description="检查学生对问题的回答是否正确，给出详细反馈和解释。",
    parameters={
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "原问题"},
            "student_answer": {"type": "string", "description": "学生的回答"},
            "correct_answer": {"type": "string", "description": "正确答案或要点"},
        },
        "required": ["question", "student_answer", "correct_answer"],
    },
)
def check_answer(question: str, student_answer: str, correct_answer: str, **_) -> str:
    return (
        "🔍 **批改请求**\n"
        f"问题: {question}\n"
        f"学生回答: {student_answer}\n"
        f"答案要点: {correct_answer}\n"
        "请给出对错判断和详细反馈。"
    )


# ============================================================
# 讲解与示例
# ============================================================


@register_tool(
    name="give_examples",
    description="为当前学习的概念提供具体实例和应用场景，帮助学生建立直觉理解。",
    parameters={
        "type": "object",
        "properties": {
            "concept": {"type": "string", "description": "需要举例说明的概念"},
            "example_type": {
                "type": "string",
                "enum": ["real_world", "code", "analogy"],
                "description": "例子类型：真实场景、代码示例或类比",
                "default": "code",
            },
        },
        "required": ["concept"],
    },
)
def give_examples(concept: str, example_type: str = "code", **_) -> str:
    type_names = {"real_world": "真实场景", "code": "代码示例", "analogy": "类比"}
    type_name = type_names.get(example_type, example_type)
    return (
        f"💡 **举例请求**: {concept}\n"
        f"类型: {type_name}\n"
        "请在下一轮对话中提供具体示例。"
    )


@register_tool(
    name="explain_deeper",
    description="对某个概念进行更深入的讲解，揭露底层原理和连接其他知识。",
    parameters={
        "type": "object",
        "properties": {
            "concept": {"type": "string", "description": "要深入讲解的概念"},
            "depth": {
                "type": "string",
                "enum": ["foundation", "mechanism", "expert"],
                "description": "讲解深度：基础原理、工作机制或专家级",
                "default": "mechanism",
            },
        },
        "required": ["concept"],
    },
)
def explain_deeper(concept: str, depth: str = "mechanism", **_) -> str:
    depth_names = {
        "foundation": "基础原理",
        "mechanism": "工作机制",
        "expert": "专家级深入",
    }
    return (
        f"🔬 **深入讲解**: {concept}\n"
        f"深度: {depth_names.get(depth, depth)}\n"
        "请在下一轮对话中提供深度讲解。"
    )


# ============================================================
# 复习与总结
# ============================================================


@register_tool(
    name="summarize_lesson",
    description="总结当前学习内容的要点，生成结构化的复习笔记。",
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "要总结的主题"},
            "format": {
                "type": "string",
                "enum": ["outline", "mindmap", "bullets"],
                "description": "总结格式：大纲、思维导图或要点列表",
                "default": "bullets",
            },
        },
        "required": ["topic"],
    },
)
def summarize_lesson(topic: str, format: str = "bullets", **_) -> str:
    format_names = {"outline": "大纲", "mindmap": "思维导图", "bullets": "要点列表"}
    return (
        f"📋 **总结请求**: {topic}\n"
        f"格式: {format_names.get(format, format)}\n"
        "请在下一轮对话中输出结构化的复习笔记。"
    )


@register_tool(
    name="spaced_review_reminder",
    description="生成间隔复习提醒，根据遗忘曲线安排复习时间点。",
    parameters={
        "type": "object",
        "properties": {
            "concept": {"type": "string", "description": "需要复习的概念"},
            "days_since_learned": {
                "type": "integer",
                "description": "上次学习至今的天数",
                "default": 1,
            },
        },
        "required": ["concept"],
    },
)
def spaced_review_reminder(concept: str, days_since_learned: int = 1, **_) -> str:
    return (
        f"⏰ **复习提醒**: {concept}\n"
        f"距上次学习: {days_since_learned} 天\n"
        "请根据遗忘曲线给出复习建议和测试问题。"
    )


# ============================================================
# 学生画像
# ============================================================


@register_tool(
    name="assess_student",
    description=(
        "记录或更新学生画像。学科层用 concept_level/skill_level，"
        "认知层和性格层用 memory_style/cognitive_strength/grasp_speed/discipline。"
        "可以在对话中自然调用，无需告知学生。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "dimension": {
                "type": "string",
                "enum": [
                    "learning_orientation",
                    "concept_level",
                    "skill_level",
                    "memory_style",
                    "cognitive_strength",
                    "grasp_speed",
                    "discipline",
                    "overall_summary",
                ],
                "description": (
                    "学科层: concept_level(C0-C4)/skill_level(S0-S4)/learning_orientation。"
                    "认知层(全局): memory_style(understanding_driven/repetition_driven/visual_spatial/logical_deduction), "
                    "cognitive_strength(spatial/logical/verbal/intuitive/systematic), "
                    "grasp_speed(fast/moderate/slow), "
                    "discipline(high/moderate/low)。"
                    "性格层(全局): learning_orientation(theory_focused/practice_focused/exam_focused/curiosity_driven/project_driven)。"
                    "overall_summary: 跨学科总体评估"
                ),
            },
            "value": {
                "type": "string",
                "description": "评估值，对应 dimension 的选项之一或自由文本",
            },
            "concept": {
                "type": "string",
                "description": "concept_level 或 skill_level 时指定概念/技能名称",
            },
            "evidence": {
                "type": "string",
                "description": "学生哪句话/哪个行为让你做出此判断",
            },
        },
        "required": ["dimension", "value"],
    },
)
def assess_student(
    dimension: str, value: str, concept: str = "", evidence: str = ""
) -> str:
    concept_str = f" [{concept}]" if concept else ""
    labels = {
        "learning_orientation": "🎯 学习倾向",
        "concept_level": "📊 概念层级",
        "skill_level": "🛠️ 技能层级",
        "memory_style": "🧠 记忆模式",
        "cognitive_strength": "💡 认知优势",
        "grasp_speed": "⚡ 理解速度",
        "discipline": "🎯 自律程度",
        "overall_summary": "📋 总体评估",
    }
    label = labels.get(dimension, dimension)
    result = f"{label}{concept_str}: {value}"
    if evidence:
        result += f"\n  依据: {evidence}"
    return result


# ============================================================
# 进度追踪
# ============================================================


@register_tool(
    name="track_progress",
    description="记录学习进度，标记已掌握的概念和待复习的内容。",
    parameters={
        "type": "object",
        "properties": {
            "concept": {"type": "string", "description": "概念名称"},
            "status": {
                "type": "string",
                "enum": ["mastered", "in_progress", "needs_review"],
                "description": "掌握状态",
            },
            "notes": {"type": "string", "description": "备注（可选）"},
        },
        "required": ["concept", "status"],
    },
)
def track_progress(concept: str, status: str, notes: str = "") -> str:
    emoji = {"mastered": "✅", "in_progress": "🔄", "needs_review": "📌"}.get(status, "📎")
    result = f"{emoji} **{concept}**: {status}"
    if notes:
        result += f"\n  备注: {notes}"
    return result


@register_tool(
    name="save_note",
    description="保存一条重要的学习笔记到当前会话中。",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "笔记标题"},
            "content": {"type": "string", "description": "笔记内容"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "分类标签（可选）",
            },
        },
        "required": ["title", "content"],
    },
)
def save_note(title: str, content: str, tags: list[str] | None = None, **_) -> str:
    import json, datetime
    from keenius.config import NOTES_DIR
    notes_dir = NOTES_DIR
    notes_dir.mkdir(parents=True, exist_ok=True)
    safe_name = title.strip().replace(" ", "-")[:60]
    note_file = notes_dir / f"{safe_name}.json"
    note_data = {
        "title": title, "content": content,
        "tags": tags or [],
        "created_at": datetime.datetime.now().isoformat(),
    }
    note_file.write_text(json.dumps(note_data, ensure_ascii=False, indent=2), encoding="utf-8")
    tag_str = ", ".join(tags) if tags else "通用"
    return f"📓 笔记已保存: '{title}' [{tag_str}] → {note_file}"


# ============================================================
# 学习计划工具
# ============================================================


@register_tool(
    name="manage_plan",
    description=(
        "管理学习计划。action: create(创建空计划) / add_lesson(添加课程到指定章节单元) / "
        "complete_lesson(标记课程完成)。add_lesson 时必须提供 section 和 unit 来组织课程层级。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "add_lesson", "complete_lesson"],
                "description": "操作类型",
            },
            "title": {
                "type": "string",
                "description": "课程标题（add_lesson 时必填）",
            },
            "section": {
                "type": "string",
                "description": "章节名称，如 '01-基础概念'。add_lesson 时必填，课程按此分组",
            },
            "unit": {
                "type": "string",
                "description": "单元名称，如 '01-变量与类型'。add_lesson 时必填，同一单元的课放一起",
            },
            "lesson_id": {
                "type": "integer",
                "description": "课程编号（complete_lesson 时必填）",
            },
            "profile_changes": {
                "type": "string",
                "description": "完成课程后观察到的学生画像变化",
            },
        },
        "required": ["action"],
    },
)
def manage_plan(
    action: str, title: str = "", lesson_id: int = 0, profile_changes: str = "",
    section: str = "", unit: str = "",
) -> str:
    from keenius.tutor.planner import (
        create_plan, add_lesson, mark_lesson_complete,
        ensure_subject, list_subjects, subject_dir,
    )
    subjects = list_subjects()
    subject = subjects[0] if subjects else (title if action == "create" and title else "general")

    if action == "create":
        ensure_subject(subject)
        return f"📋 学习计划已创建: {subject}\n存储位置: {subject_dir(subject)}"

    elif action == "add_lesson":
        if not title:
            return "请提供课程标题。"
        if not subjects:
            return "请先用 action=create 创建学习计划。"
        sec = section or "默认章节"
        unt = unit or "默认单元"
        lesson_path = add_lesson(subject, sec, unt, title)
        return f"📝 已添加课程: {title}\n章节: {sec} → {unt}\n文件: {lesson_path}"

    elif action == "complete_lesson":
        if not lesson_id:
            return "请提供课程编号。"
        if not subjects:
            return "未找到学习计划。"
        result = mark_lesson_complete(subject, lesson_id)
        if result:
            return f"✅ 第 {lesson_id} 课已完成: {result.get('title', '')}"
        return f"未找到第 {lesson_id} 课。"

    return "未知操作。"


@register_tool(
    name="write_lesson_content",
    description=(
        "写入或更新一堂课的详细教学内容。用 subject+title 定位课程文件。"
        "section 指定要更新的部分：definition(定义原文+直观解释)、"
        "examples(方法典例)、quiz(当堂测试)、extension(拓展内容)。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "subject": {"type": "string", "description": "学科名，如 'python'"},
            "lesson_title": {"type": "string", "description": "课程标题（.md 文件名不含编号），如 '什么是变量'"},
            "section": {
                "type": "string",
                "enum": ["definition", "examples", "quiz", "extension"],
                "description": "课程部分",
            },
            "content": {"type": "string", "description": "该部分的完整内容（Markdown 格式）"},
        },
        "required": ["subject", "lesson_title", "section", "content"],
    },
)
def write_lesson_content(
    subject: str, lesson_title: str, section: str, content: str, intuitive_explanation: str = ""
) -> str:
    from keenius.tutor.planner import subject_dir, read_lesson, write_lesson
    base = subject_dir(subject)
    if not base.exists():
        return f"未找到学科 '{subject}' 的计划。请先用 generate_curriculum 创建。"

    # 查找匹配标题的 .md 文件
    for md_file in base.rglob("*.md"):
        if md_file.parent.name == "test":
            continue
        meta, body = read_lesson(md_file)
        if meta.get("title") == lesson_title or lesson_title in md_file.stem:
            # 更新 markdown 正文中的对应部分
            heading_map = {
                "definition": "## 定义原文",
                "examples": "## 方法典例",
                "quiz": "## 当堂测试",
                "extension": "## 拓展内容",
            }
            heading = heading_map.get(section, f"## {section}")
            # 替换标题下的内容
            new_body = _replace_section(body, heading, content)
            write_lesson(md_file, meta, new_body)
            return f"✓ 已更新课程 '{meta.get('title', lesson_title)}' 的 {section} 部分"

    return f"未找到课程 '{lesson_title}'。请确认标题正确。"


def _replace_section(body: str, heading: str, new_content: str) -> str:
    """替换 markdown 正文中 ## 标题下的内容。"""
    import re
    pattern = re.compile(rf"^{re.escape(heading)}\s*\n.*?(?=^## |\Z)", re.DOTALL | re.MULTILINE)
    replacement = f"{heading}\n\n{new_content}\n"
    if pattern.search(body):
        return pattern.sub(replacement, body)
    else:
        return body + f"\n\n{heading}\n\n{new_content}\n"


@register_tool(
    name="generate_curriculum",
    description=(
        "生成课程大纲。按章节→单元→课程的三层结构组织。"
        "每个 section 包含多个 unit，每个 unit 包含多个 lesson。"
        "section.title 如 '01-基础概念'，unit.title 如 '01-变量与类型'，"
        "lesson.title 如 '什么是变量'。一门学科 2-5 个 section，20-50 课。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "章节标题，如 '01-基础概念'"},
                        "units": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string", "description": "单元标题，如 '01-变量与类型'"},
                                    "lessons": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "title": {"type": "string", "description": "课程标题"},
                                                "description": {"type": "string", "description": "一句话描述本课内容"},
                                            },
                                            "required": ["title", "description"],
                                        },
                                    },
                                },
                                "required": ["title", "lessons"],
                            },
                        },
                    },
                    "required": ["title", "units"],
                },
            },
        },
        "required": ["sections"],
    },
)
def generate_curriculum(sections: list[dict]) -> str:
    from keenius.tutor.planner import ensure_subject, add_lesson, list_subjects

    subjects = list_subjects()
    subject = subjects[0] if subjects else "general"
    ensure_subject(subject)

    total = 0
    for sec in sections:
        sec_title = sec.get("title", "默认章节")
        for unit in sec.get("units", []):
            unit_title = unit.get("title", "默认单元")
            for lesson in unit.get("lessons", []):
                title = lesson.get("title", f"第{total+1}课")
                desc = lesson.get("description", "")
                content = f"# {title}\n\n## 定义原文\n\n## 直观解释\n\n## 方法典例\n\n## 当堂测试\n\n## 拓展内容\n\n{desc}"
                add_lesson(subject, sec_title, unit_title, title, content)
                total += 1

    return f"📋 课程大纲已生成: {total} 节课，{len(sections)} 个章节"


@register_tool(
    name="plan_summary",
    description="展示当前学习计划概览，包括所有课程及完成状态。",
    parameters={"type": "object", "properties": {}, "required": []},
)
def plan_summary_tool() -> str:
    from keenius.tutor.planner import list_subjects, plan_summary
    subjects = list_subjects()
    if not subjects:
        return "尚无学习计划。用 manage_plan(action='create') 创建。"
    return plan_summary(subjects[0])


@register_tool(
    name="ask_fill_blank",
    description=(
        "创建填空题。question=题目文字，用 ___ 标记空位。"
        "学生会直接在空上填写答案，按 Tab 在空之间切换。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "题目文字，用 ___ 标记空位"},
            "hint": {"type": "string", "description": "可选的提示文字"},
        },
        "required": ["question"],
    },
)
def ask_fill_blank(question: str, hint: str = "", **_) -> str:
    # 以选项格式返回，使选择器激活并在行内填空
    return (
        f"请填空（直接在空上输入，Tab 切换空位）：\n"
        f"\n[1] {question}\n"
        f"\n选 [1] 后直接在 ___ 上打字填充。"
    )


@register_tool(
    name="show_curriculum",
    description=(
        "展示课程大纲的指定部分。可指定 section（章节名）和 unit（单元名），"
        "不指定则显示全部。用于让学生了解当前学习进度和课程结构。"
        "返回结构化的课程列表文本。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "subject": {"type": "string", "description": "学科名，如 'python'"},
            "section": {"type": "string", "description": "要展示的章节名，如 '01-基础概念'。不填则显示全部"},
            "unit": {"type": "string", "description": "要展示的单元名，如 '01-变量与类型'。不填则显示该章节下所有单元"},
        },
        "required": [],
    },
)
def show_curriculum(subject: str = "", section: str = "", unit: str = "") -> str:
    from keenius.tutor.planner import list_subjects, scan_tree
    subjects = list_subjects()
    if not subjects:
        return "尚无学习计划。"

    subj = subject or subjects[0]
    tree = scan_tree(subj)
    if not tree:
        return f"学科 '{subj}' 暂无课程内容。"

    lines = [f"📋 教学大纲：{subj}\n"]
    for sec in tree:
        if section and sec.get("title", "") != section:
            continue
        done = sum(1 for u in sec.get("children", []) for l in u.get("children", [])
                   if l.get("status") == "completed")
        total = sum(1 for u in sec.get("children", []) for l in u.get("children", [])
                    if l.get("type") == "lesson")
        lines.append(f"📁 {sec['title']}  [{done}/{total}]")
        for unode in sec.get("children", []):
            if unode.get("type") == "test":
                lines.append(f"  🧪 {unode['title']}")
                continue
            if unit and unode.get("title", "") != unit:
                continue
            u_done = sum(1 for l in unode.get("children", []) if l.get("status") == "completed")
            u_total = sum(1 for l in unode.get("children", []) if l.get("type") == "lesson")
            lines.append(f"  📂 {unode['title']}  [{u_done}/{u_total}]")
            for lnode in unode.get("children", []):
                if lnode.get("type") == "test":
                    lines.append(f"    🧪 {lnode['title']}")
                    continue
                icon = lnode.get("icon", "⏳")
                title = lnode.get("title", "")
                lines.append(f"    {icon} {title}")
    lines.append(f"\n提示：学生可输入 /plan 查看交互式大纲。")
    return "\n".join(lines)
