"""Smoke test for the scaffolding: every planned module imports."""

import importlib

import pytest

MODULES = [
    "bidrig",
    "bidrig.schema",
    "bidrig.bne",
    "bidrig.auction",
    "bidrig.bidders",
    "bidrig.prompts",
    "bidrig.llm",
    "bidrig.runner",
    "bidrig.analysis.metrics",
    "bidrig.analysis.stats",
    "bidrig.analysis.report",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    importlib.import_module(name)
