"""Built-in teaching tools for the OpenTeacher agent.

All tool descriptions are in Chinese since the primary teaching language is Chinese.
Tools are registered via the @register_tool decorator — just importing this module
is enough to make them available to the agent.
"""

from openteacher.tools.registry import register_tool

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
    tag_str = ", ".join(tags) if tags else "通用"
    return f"📓 **笔记已保存**: '{title}' [{tag_str}]\n{content}"
