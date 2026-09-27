from pathlib import Path


def test_dockerignore_keeps_modules_and_drops_secrets():
    text = Path(".dockerignore").read_text()
    for required in (".git", ".venv", ".env", "artifacts/", ".pytest_cache"):
        assert required in text
    assert "terraform/modules" not in text.split()


def test_env_example_has_names_and_no_secret_values():
    text = Path(".env.example").read_text()
    for name in (
        "GITHUB_TOKEN",
        "OPENAI_API_KEY",
        "LANGFUSE_SECRET_KEY",
        "IAC_AGENT_BIND_HOST",
        "IAC_AGENT_TRUSTED_MODULE_ROOT",
        "IAC_AGENT_STATE_DB",
    ):
        assert name in text
    assert "sk-" not in text
    assert "ghp_" not in text
