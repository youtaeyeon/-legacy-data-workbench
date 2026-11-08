import pytest

from hospital_marketing.ai.cli_status import check_all_cli_statuses, check_node_tool_status


@pytest.mark.live
def test_live_cli_install_status():
    statuses = check_all_cli_statuses()
    for cli, status in statuses.items():
        print(f"{cli}: installed={status.installed}, path={status.path}, version={status.version}, error={status.error}")
    print(f"Node.js/npm: {check_node_tool_status()}")
