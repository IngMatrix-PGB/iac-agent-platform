import pytest

from iac_agent.git.port import SourceControlError
from iac_agent.git.unavailable import UnavailableSourceControl


def test_publish_change_refuses_without_a_credential():
    port = UnavailableSourceControl()
    with pytest.raises(SourceControlError) as exc:
        port.publish_change(
            request_id="req-1",
            base_branch="main",
            branch_name="iac-agent/req-1",
            files={"main.tf": 'resource "aws_sqs_queue" "this" {}'},
            commit_message="feat",
            pr_title="title",
            pr_body="body",
        )
    text = str(exc.value)
    assert text == "Source-control publishing is not configured."
    assert "aws_sqs_queue" not in text
    assert not hasattr(port, "_token")


def test_publish_change_does_not_open_a_network_connection(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("network")

    monkeypatch.setattr("urllib.request.urlopen", explode)
    port = UnavailableSourceControl()
    with pytest.raises(SourceControlError):
        port.publish_change(
            request_id="req-1",
            base_branch="main",
            branch_name="iac-agent/req-1",
            files={},
            commit_message="feat",
            pr_title="title",
            pr_body="body",
        )
