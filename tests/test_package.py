"""Baseline smoke tests: the package installs, imports, and is versioned."""

import iac_agent


def test_package_imports():
    assert iac_agent is not None


def test_package_has_version():
    assert isinstance(iac_agent.__version__, str)
    assert iac_agent.__version__
