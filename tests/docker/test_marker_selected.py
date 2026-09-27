import pytest


@pytest.mark.docker
def test_docker_marker_is_selected():
    assert True
