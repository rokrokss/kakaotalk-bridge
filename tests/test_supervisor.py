import json
import subprocess
from unittest.mock import patch

from deploy.supervisor import tick


def test_restart_budget_survives_process_restarts(tmp_path):
    state = tmp_path / "budget.json"
    listing = subprocess.CompletedProcess([], 0, stdout='{"State":"exited"}\n')
    with patch("deploy.supervisor.subprocess.run", return_value=listing) as run:
        assert [tick(state) for _ in range(4)] == [
            "restarted",
            "restarted",
            "restarted",
            "restart_limit_reached",
        ]
        starts = [call for call in run.call_args_list if "start" in call.args[0]]
        assert len(starts) == 3
        assert len(json.loads(state.read_text())) == 3


def test_supervisor_does_not_create_or_restart_running_container(tmp_path):
    with patch(
        "deploy.supervisor.subprocess.run",
        return_value=subprocess.CompletedProcess([], 0, stdout='{"State":"running"}'),
    ) as run:
        assert tick(tmp_path / "state.json") == "running"
        assert run.call_count == 1
