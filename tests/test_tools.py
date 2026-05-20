"""Tests for the tool registry and built-in tools."""

import pytest
from openteacher.tools.registry import registry, ToolDef


def test_registry_has_tools():
    names = registry.tool_names
    assert "create_quiz" in names
    assert "track_progress" in names
    assert "save_note" in names
    assert "give_examples" in names


def test_get_tool_definitions():
    defs = registry.get_tool_definitions()
    assert len(defs) >= 8
    for d in defs:
        assert d["type"] == "function"
        assert "name" in d["function"]
        assert "description" in d["function"]
        assert "parameters" in d["function"]


def test_tool_execution():
    result = registry.execute("track_progress", concept="test", status="mastered")
    assert "test" in result
    assert "mastered" in result


def test_unknown_tool():
    result = registry.execute("nonexistent_tool")
    assert "ERROR" in result or "Unknown" in result
