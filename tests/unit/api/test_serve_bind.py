import pytest

from iac_agent.api.app import bind_host, bind_port


def test_bind_defaults_are_loopback_8000():
    assert bind_host({}) == "127.0.0.1"
    assert bind_port({}) == 8000


def test_bind_reads_container_overrides():
    env = {"IAC_AGENT_BIND_HOST": "0.0.0.0", "IAC_AGENT_PORT": "8000"}
    assert bind_host(env) == "0.0.0.0"
    assert bind_port(env) == 8000


def test_blank_host_is_rejected():
    with pytest.raises(ValueError):
        bind_host({"IAC_AGENT_BIND_HOST": "  "})


def test_invalid_port_is_rejected():
    with pytest.raises(ValueError):
        bind_port({"IAC_AGENT_PORT": "0"})
    with pytest.raises(ValueError):
        bind_port({"IAC_AGENT_PORT": "abc"})


def test_module_entrypoint_delegates_to_serve():
    import iac_agent.api.__main__ as entry

    assert entry.serve is not None
