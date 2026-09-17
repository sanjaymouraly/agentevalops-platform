import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
import pytest
from app.harbor_adapter import is_harbor_available, run_harbor_job


@pytest.mark.skipif(not is_harbor_available(), reason="Harbor CLI not installed (native engine must still work without it)")
def test_harbor_cli_help_via_adapter():
    r = run_harbor_job("--help")
    assert r["available"] is True and r["returncode"] == 0
