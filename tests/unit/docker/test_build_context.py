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


def test_compose_publishes_loopback_and_persists_only_state():
    import yaml

    data = yaml.safe_load(Path("compose.yaml").read_text())
    services = data["services"]
    assert list(services) == ["iac-agent"]
    service = services["iac-agent"]
    assert "127.0.0.1:8000:8000" in service["ports"]
    environment = service["environment"]
    assert environment["IAC_AGENT_BIND_HOST"] == "0.0.0.0"
    assert environment["IAC_AGENT_STATE_DB"] == "/var/lib/iac-agent/state/state.db"
    assert environment["IAC_AGENT_WORKSPACE_ROOT"] == "/var/lib/iac-agent/workspaces"
    assert environment["IAC_AGENT_TRUSTED_MODULE_ROOT"] == "/opt/iac-agent"
    mounts = service["volumes"]
    assert "iac-agent-state:/var/lib/iac-agent/state" in mounts
    assert "iac-agent-state" in data["volumes"]
    assert all(
        image not in {"postgres", "redis", "localstack"}
        for image in (item.get("image") for item in services.values())
    )
    assert all("/var/run/docker.sock" not in str(mount) for mount in mounts)
    assert service.get("network_mode") != "host"
    assert service.get("privileged") is not True
    assert service.get("stop_grace_period")


def test_api_doc_states_container_bind_is_not_authorization():
    text = Path("docs/api.md").read_text()
    assert "127.0.0.1:8000:8000" in text
    assert (
        "0.0.0.0 inside the container is network binding, "
        "not authentication or authorization."
    ) in text


def test_image_build_compiles_the_ui_and_keeps_one_service():
    dockerfile = Path("Dockerfile").read_text()
    ignore = Path(".dockerignore").read_text()
    compose = Path("compose.yaml").read_text()
    assert "ui/node_modules" in ignore
    assert "ui/dist" in ignore
    assert "AS ui" in dockerfile
    assert "npm run build" in dockerfile
    assert "IAC_AGENT_UI_DIST=/opt/iac-agent/ui" in dockerfile
    assert "COPY --from=ui" in dockerfile
    runtime = dockerfile.split("FROM python:3.12-slim-bookworm@", 2)[2]
    assert "npm" not in runtime
    assert "apt-get install node" not in runtime
    assert "127.0.0.1:8000:8000" in compose
    import yaml

    services = yaml.safe_load(compose)["services"]
    assert list(services) == ["iac-agent"]
