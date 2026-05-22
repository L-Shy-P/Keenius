"""Built-in teaching tools for the OpenTeacher agent.

All tool descriptions are in Chinese since the primary teaching language is Chinese.
Tools are registered via the @register_tool decorator — just importing this module
is enough to make them available to the agent.
"""

from openteacher.tools.registry import register_tool, tool_result, tool_error

# ============================================================
# Standard file I/O tools (Claude Code / Hermes compatible format)
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

    # Line-numbered output (matching Claude Code `cat -n` format)
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
        "只能写入 ~/.openteacher/ 目录或当前项目目录下的文件。"
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
        Path.home() / ".openteacher",
        Path.cwd(),
    ]
    if not any(str(p).startswith(str(d)) for d in allowed_dirs):
        return tool_error(
            f"安全限制：只能写入 ~/.openteacher/ 或当前项目目录下的文件。\n"
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
# Quiz & Assessment tools
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
def create_quiz(topic: str, question_count: int = 3, difficulty: str = "medium") -> str:
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
def check_answer(question: str, student_answer: str, correct_answer: str) -> str:
    return (
        "🔍 **批改请求**\n"
        f"问题: {question}\n"
        f"学生回答: {student_answer}\n"
        f"答案要点: {correct_answer}\n"
        "请给出对错判断和详细反馈。"
    )


# ============================================================
# Explanation & Examples
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
def give_examples(concept: str, example_type: str = "code") -> str:
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
def explain_deeper(concept: str, depth: str = "mechanism") -> str:
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
# Review & Summarization
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
def summarize_lesson(topic: str, format: str = "bullets") -> str:
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
def spaced_review_reminder(concept: str, days_since_learned: int = 1) -> str:
    return (
        f"⏰ **复习提醒**: {concept}\n"
        f"距上次学习: {days_since_learned} 天\n"
        "请根据遗忘曲线给出复习建议和测试问题。"
    )


# ============================================================
# Student profiling
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
# Progress tracking
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
def save_note(title: str, content: str, tags: list[str] | None = None) -> str:
    import json, datetime
    from openteacher.config import DATA_DIR
    notes_dir = DATA_DIR / "notes"
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
# Learning plan tools
# ============================================================


@register_tool(
    name="manage_plan",
    description=(
        "管理学习计划。可以创建新计划、添加课程、更新课程状态。"
        "action: create(创建空计划) / add_lesson(添加一堂课) / "
        "complete_lesson(标记课程完成并记录画像变化)"
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
            "lesson_id": {
                "type": "integer",
                "description": "课程编号（complete_lesson 时必填）",
            },
            "profile_changes": {
                "type": "string",
                "description": "完成课程后观察到的学生画像变化（JSON 格式或自由文本描述）",
            },
        },
        "required": ["action"],
    },
)
def manage_plan(
    action: str, title: str = "", lesson_id: int = 0, profile_changes: str = ""
) -> str:
    from openteacher.tutor.planner import (
        create_plan, add_lesson, mark_lesson_complete, load_plan, plan_path,
    )
    # Get subject from the current session context — we use a simple approach
    # The subject is inferred from the plan file name
    subject = title if action == "create" and title else ""

    if action == "create":
        plan = create_plan(subject or "general")
        return f"📋 学习计划已创建: {subject or 'general'}\n存储位置: {plan_path(subject or 'general')}"

    elif action == "add_lesson":
        if not title:
            return "请提供课程标题。"
        # Find the active plan by listing plan files
        from openteacher.config import PLANS_DIR
        import json
        plan_files = list(PLANS_DIR.glob("*.json"))
        if not plan_files:
            return "未找到学习计划。请先用 action=create 创建。"
        latest_plan = max(plan_files, key=lambda p: p.stat().st_mtime)
        plan = json.loads(latest_plan.read_text(encoding="utf-8"))
        subject = plan["subject"]
        lesson = add_lesson(subject, title)
        return f"📝 已添加第 {lesson['id']} 课: {title}\n计划: {subject}"

    elif action == "complete_lesson":
        if not lesson_id:
            return "请提供课程编号。"
        from openteacher.config import PLANS_DIR
        import json
        plan_files = list(PLANS_DIR.glob("*.json"))
        if not plan_files:
            return "未找到学习计划。"
        latest_plan = max(plan_files, key=lambda p: p.stat().st_mtime)
        plan = json.loads(latest_plan.read_text(encoding="utf-8"))
        subject = plan["subject"]
        changes = {}
        if profile_changes:
            changes["notes"] = profile_changes
        result = mark_lesson_complete(subject, lesson_id, changes)
        if result:
            return f"✅ 第 {lesson_id} 课已完成: {result['title']}"
        return f"未找到第 {lesson_id} 课。"

    return "未知操作。"


@register_tool(
    name="plan_summary",
    description="展示当前学习计划概览，包括所有课程及完成状态。",
    parameters={"type": "object", "properties": {}, "required": []},
)
@register_tool(
    name="write_lesson_content",
    description=(
        "写入或更新一堂课的详细教学内容。lesson_id 指定课程编号，"
        "section 指定要更新的部分：definition(定义原文+直观解释)、"
        "examples(方法典例)、quiz(当堂测试)、extension(拓展内容)。"
        "content 是自由格式文本，Agent 应写入完整的课程内容。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "lesson_id": {"type": "integer", "description": "课程编号"},
            "section": {
                "type": "string",
                "enum": ["definition", "examples", "quiz", "extension"],
                "description": "课程部分",
            },
            "content": {"type": "string", "description": "该部分的完整内容（Markdown 格式）"},
            "intuitive_explanation": {
                "type": "string",
                "description": "直观解释版本（仅 definition 部分需要）",
            },
        },
        "required": ["lesson_id", "section", "content"],
    },
)
def write_lesson_content(
    lesson_id: int, section: str, content: str, intuitive_explanation: str = ""
) -> str:
    from openteacher.config import PLANS_DIR
    import json, datetime

    plan_files = list(PLANS_DIR.glob("*.json"))
    if not plan_files:
        return "未找到学习计划。请先用 manage_plan 创建。"
    latest_plan = max(plan_files, key=lambda p: p.stat().st_mtime)
    plan = json.loads(latest_plan.read_text(encoding="utf-8"))

    for lesson in plan["lessons"]:
        if lesson["id"] == lesson_id:
            if section == "definition":
                lesson["sections"]["definition"]["original"] = content
                if intuitive_explanation:
                    lesson["sections"]["definition"]["intuitive"] = intuitive_explanation
            elif section == "examples":
                lesson["sections"]["examples"].append({
                    "content": content, "added_at": datetime.datetime.now().isoformat(),
                })
            elif section == "quiz":
                lesson["sections"]["quiz"].append({
                    "content": content, "added_at": datetime.datetime.now().isoformat(),
                })
            elif section == "extension":
                lesson["sections"]["extension"] = content

            plan["updated_at"] = datetime.datetime.now().isoformat()
            from openteacher.tutor.planner import save_plan
            save_plan(plan["subject"], plan)

            sections_cn = {"definition": "定义与解释", "examples": "方法典例",
                          "quiz": "当堂测试", "extension": "拓展内容"}
            return f"📝 第 {lesson_id} 课「{lesson['title']}」的 {sections_cn.get(section, section)} 已写入"

    return f"未找到第 {lesson_id} 课。"


@register_tool(
    name="generate_curriculum",
    description=(
        "生成课程大纲写入计划文件。每课一个具体知识点，一门学科20-50课。"
        "title=课程名(如 '函数参数类型')，description=一句话描述。调用后覆盖已有。"
    ),
    parameters={
        "type": "object",
        "properties": {
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
                "description": "课程列表，按教学顺序排列",
            },
        },
        "required": ["lessons"],
    },
)
def generate_curriculum(lessons: list[dict]) -> str:
    import json, datetime
    from openteacher.config import PLANS_DIR
    from openteacher.tutor.planner import create_plan, add_lesson, save_plan

    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    plan_files = list(PLANS_DIR.glob("*.json"))
    if plan_files:
        latest = max(plan_files, key=lambda p: p.stat().st_mtime)
        plan = json.loads(latest.read_text(encoding="utf-8"))
    else:
        plan = create_plan("general")

    plan["lessons"] = []
    for i, lesson in enumerate(lessons):
        plan["lessons"].append({
            "id": i + 1,
            "title": lesson["title"],
            "description": lesson.get("description", ""),
            "status": "pending",
            "skipped": False,
            "created_at": datetime.datetime.now().isoformat(),
        })

    save_plan(plan["subject"], plan)
    return f"📋 课程大纲已生成: {len(lessons)} 节课"


def plan_summary_tool() -> str:
    from openteacher.config import PLANS_DIR
    import json
    files = list(PLANS_DIR.glob("*.json"))
    if not files:
        return "尚无学习计划。用 manage_plan(action='create') 创建。"
    latest = max(files, key=lambda p: p.stat().st_mtime)
    plan = json.loads(latest.read_text(encoding="utf-8"))
    from openteacher.tutor.planner import plan_summary
    return plan_summary(plan["subject"])
