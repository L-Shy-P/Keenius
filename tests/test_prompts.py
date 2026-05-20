"""Tests for the prompt building system."""

from openteacher.tutor.prompts import build_system_prompt, SUBJECT_AUGMENTS


def test_build_system_prompt_default():
    prompt = build_system_prompt()
    assert "OpenTeacher" in prompt
    assert len(prompt) > 100


def test_build_system_prompt_with_subject():
    prompt = build_system_prompt(subject="python programming")
    assert "OpenTeacher" in prompt
    assert "编程教学" in prompt


def test_subject_augments():
    assert "programming" in SUBJECT_AUGMENTS
    assert "math" in SUBJECT_AUGMENTS
