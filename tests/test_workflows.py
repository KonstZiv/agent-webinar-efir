"""Workflows of the cloud agent, copied from the template repository (commit c6da700).

They run on the pinned runner, take the subscription token only by reference to a secret, and
the review bot may only read the code and comment.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
AGENT, REVIEW = WORKFLOWS / "claude.yml", WORKFLOWS / "claude-code-review.yml"


def load(path: Path) -> dict[str, Any]:
    document: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return document


@pytest.mark.parametrize("path", [AGENT, REVIEW], ids=lambda path: path.name)
def test_workflow_runs_the_action_on_the_pinned_runner(path: Path) -> None:
    [job] = load(path)["jobs"].values()
    action = next(step for step in job["steps"] if "claude-code-action" in step.get("uses", ""))

    assert job["runs-on"] == "ubuntu-24.04"
    assert action["uses"] == "anthropics/claude-code-action@v1"
    assert action["with"]["claude_code_oauth_token"] == "${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}"


def test_review_bot_only_reads_the_code() -> None:
    [job] = load(REVIEW)["jobs"].values()

    assert job["permissions"]["contents"] == "read"


def test_agent_ignores_bots() -> None:
    [job] = load(AGENT)["jobs"].values()

    assert "github.event.sender.type != 'Bot'" in job["if"]
