import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.integration.conftest import resolve_plugin_cache_dir  # noqa: E402


def test_existing_env_dir_is_reused(tmp_path: Path):
    target = tmp_path / "cache"
    resolved = resolve_plugin_cache_dir(str(target), factory=None)
    assert resolved == target
    assert target.is_dir()


def test_missing_env_uses_the_factory(tmp_path: Path):
    class Factory:
        def mktemp(self, name: str, numbered: bool = True) -> Path:
            assert name == "tf-plugin-cache"
            assert numbered is False
            path = tmp_path / name
            path.mkdir()
            return path

    resolved = resolve_plugin_cache_dir(None, Factory())
    assert resolved == tmp_path / "tf-plugin-cache"
