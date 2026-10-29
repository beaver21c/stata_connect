"""테스트용 가짜 백엔드 — Stata 없이 실행 흐름(guard → 실행 → 필터 → 기록)을 검증.

출력은 Stata 로그 형식을 흉내 낸 합성 텍스트이며 실제 Stata 출력이 아님.
"""

from __future__ import annotations

import re
from pathlib import Path

from stata_agent.backends.base import Backend, RunOutcome
from stata_agent.guard.output_filter import last_return_code

AUTO_VARS = [
    ("make", "str18", "", 0, "Make and model"),
    ("price", "int", "", 0, "Price"),
    ("mpg", "int", "", 0, "Mileage (mpg)"),
    ("rep78", "int", "", 5, "Repair record 1978"),
    ("weight", "int", "", 0, "Weight (lbs.)"),
    ("length", "int", "", 0, "Length (in.)"),
    ("foreign", "byte", "origin", 0, "Car origin"),
]

SUMMARIZE_PRICE = """\
. summarize price

    Variable |        Obs        Mean    Std. dev.       Min        Max
-------------+---------------------------------------------------------
       price |         74    6165.257    2949.496       3291      15906
"""


def echo(code: str) -> str:
    return "\n".join(f". {ln}" for ln in code.splitlines() if ln.strip())


def default_responder(code: str, state: dict) -> str:
    out: list[str] = []
    if "SASCHEMA" in code:
        out.append("SASCHEMA|N|74")
        out.append(f"SASCHEMA|K|{len(AUTO_VARS)}")
        for name, t, vl, miss, lab in AUTO_VARS:
            out.append(f"SAVAR|{name}|{t}|{vl}|{miss}|{lab}")
    if "SAUNIQ" in code:
        m = re.search(r"unab __saul : (.+)", code)
        names = m.group(1).split() if m else []
        if names == ["_all"]:
            names = [v[0] for v in AUTO_VARS]
        for n in names:
            uniq = 74 if n == "make" else 5
            out.append(f"SAUNIQ|{n}|{uniq}|74")
    if "SAT4" in code:
        out.append(SUMMARIZE_PRICE)
        out += ["SAT4|N|74", "SAT4|mean|6165.256756756757", "SAT4|sd|2949.495884768919", "SAT4|r|.946008564"]
    if "display 12345" in code:
        out += [". display 12345", "12345"]
    if "scalar t3 = 1" in code:
        state["t3"] = 1
    if "SAT3" in code:
        out.append(f"SAT3|v|{state.get('t3', '.')}")
    m = re.search(r'putdocx save "([^"]+)"', code)
    if m:
        Path(m.group(1)).parent.mkdir(parents=True, exist_ok=True)
        Path(m.group(1)).write_bytes(b"PK")
    m = re.search(r'export\("([^"]+)", replace\)', code)
    if m and state.get("root"):
        p = Path(state["root"]) / m.group(1)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"PK")
    for name in re.findall(r'display "SARES\|([^|]+)\|"', code):
        value = {"e(r2)": "0.2934", "e(N)": "74", "_b[weight]": "1.746559"}.get(name)
        if value is not None:
            out.append(f"SARES|{name}|{value}")
        else:
            out.append("r(111);")
    if "tab make" in code:
        out.append(". tab make")
        out.append("  Make and model |      Freq.     Percent        Cum.")
        out.append("-----------------+-----------------------------------")
        for i in range(12):
            out.append(f"      Car{i:02d}     |          1        1.35       {1.35 * (i + 1):.2f}")
    if "force_error" in code:
        out.append("variable force_error not found")
        out.append("r(111);")
    if not out:
        out.append(echo(code))
    return "\n".join(out) + "\n"


class FakeBackend(Backend):
    name = "fake"

    def __init__(self, persistent: bool = True, responder=default_responder):
        self.persistent_session = persistent
        self.responder = responder
        self.calls: list[tuple] = []
        self.state: dict = {}

    def available(self) -> tuple[bool, str]:
        return True, ""

    def _outcome(self, code: str) -> RunOutcome:
        text = self.responder(code, self.state)
        rc = last_return_code(text)
        return RunOutcome(rc == 0, rc, text, None, "" if rc == 0 else f"Stata 오류 r({rc})")

    def open_session(self, project_root: Path, session_id: str) -> RunOutcome:
        self.calls.append(("open", session_id))
        self.state["root"] = str(project_root)
        return RunOutcome(True, 0, "stata-agent session ready\nSA_VERSION|18\n")

    def run_code(self, code: str, session_id: str, project_root: Path) -> RunOutcome:
        self.calls.append(("code", code))
        self.state["root"] = str(project_root)
        return self._outcome(code)

    def run_dofile(self, path: Path, session_id: str, project_root: Path) -> RunOutcome:
        self.calls.append(("dofile", str(path)))
        content = Path(path).read_text(encoding="utf-8")
        # do-file이 쓰는 이름 지정 로그를 흉내 냄
        m = re.search(r'log using "([^"]+)"', content)
        out = self._outcome(content)
        if m:
            p = Path(project_root) / m.group(1)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(out.log_text, encoding="utf-8")
        return out

    def show_in_editor(self, path: Path, session_id: str) -> RunOutcome:
        self.calls.append(("editor", str(path)))
        return RunOutcome(True, 0, message="표시 요청 완료")
