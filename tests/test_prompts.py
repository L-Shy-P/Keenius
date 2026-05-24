"""提示词构建系统的测试。"""

from keenius.tutor.prompts import build_system_prompt, SUBJECT_AUGMENTS


def test_build_system_prompt_default():
    prompt = build_system_prompt()
    assert "Keenius" in prompt
    assert len(prompt) > 100


def test_build_system_prompt_with_subject():
    prompt = build_system_prompt(subject="python programming")
    assert "Keenius" in prompt
    assert "编程教学" in prompt


def test_subject_augments():
    assert "programming" in SUBJECT_AUGMENTS
    assert "math" in SUBJECT_AUGMENTS
