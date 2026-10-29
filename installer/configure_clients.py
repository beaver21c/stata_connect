"""Claude Code·Claude Desktop·Codex 설정 자동 병합(설계서 §11) — 기존 설정 백업 후 병합.

사용(저장소에서 직접 실행 가능):
    python installer/configure_clients.py --clients claude-code,claude-desktop,codex --dry-run
    python installer/configure_clients.py --command "C:/Users/me/AppData/Local/StataAgent/stata-agent-mcp.exe" \\
        --env STATA_AGENT_STATA_EXE=C:/Stata18/StataSE-64.exe

실제 로직: mcp_server/stata_agent/client_config.py (단위 테스트: tests/test_client_config.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp_server"))

from stata_agent.cli import main  # noqa: E402

if __name__ == "__main__":
    main(["configure", *sys.argv[1:]])
