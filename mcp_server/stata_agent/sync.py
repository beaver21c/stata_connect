"""연구자 조작 감지·이어받기(창 연동 세션) — 사람이 AI가 연 Stata 창에서 직접 작업한 경우 대응.

배경(2026-11-01 사용자 요구): 창 연동 중 연구자가 변수 이름 변경·리코드·clear·다른 자료 use 등을 하면
AI가 알던 상태와 달라짐. 경고 수준으로 알리고, 사람이 친 명령·고친 do-file을 AI가 이어받게 함.

구성
1. 자료 상태 지문: 관측치 수·변수 수·자료 파일·변수별 이름·유형·값 라벨·값 확인값(``datasignature``).
   AI 실행 직후 기록 → 다음 AI 실행 직전에 다시 계산해 비교. r() 결과는 ``_return hold/restore``로 보존
2. 수동 명령: 세션을 열 때 ``cmdlog``(Stata 명령 기록)를 켜 두고, AI 실행 사이에 새로 쌓인 줄을
   "연구자 입력"으로 봄(AI 실행 직후마다 읽은 위치를 끝으로 옮겨 AI 자신의 명령은 제외)
3. do-file 수정: AI가 마지막으로 쓰거나 읽은 내용과 디스크 내용이 다르면 섹션 단위로 바뀐 곳을 알림

지위: Stata 명령(``datasignature``·``_return hold``·``cmdlog``)은 일반 지식 기반 [미확인: 실기 확인 필요].
특히 자동화(COM)로 보낸 명령이 cmdlog에 남는지, Do-file Editor '선택 실행'이 어떻게 남는지 [미확인].
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .guard.output_filter import extract_markers

PER_VAR_SIGNATURE_MAX_K = 300


def state_code(max_cells: int, with_signature: bool = True) -> str:
    sig = ""
    if with_signature:
        sig = f"""\
if c(k) > 0 & c(N) * c(k) <= {int(max_cells)} {{
    if c(k) <= {PER_VAR_SIGNATURE_MAX_K} {{
        foreach __sav of varlist _all {{
            capture quietly datasignature `__sav'
            if !_rc display `"SASIG|`__sav'|`r(datasignature)'"'
        }}
    }}
    else {{
        capture quietly datasignature
        if !_rc display `"SASIG|_all|`r(datasignature)'"'
    }}
}}
"""
    return f"""\
capture _return drop __sast
_return hold __sast
display "SASTATE|N|" c(N)
display "SASTATE|K|" c(k)
display `"SASTATE|F|`c(filename)'"'
if c(k) > 0 {{
    foreach __sav of varlist _all {{
        local __sat : type `__sav'
        local __savl : value label `__sav'
        display `"SAVS|`__sav'|`__sat'|`__savl'"'
    }}
}}
{sig}capture _return restore __sast
"""


@dataclass
class DataState:
    n: int | None = None
    k: int | None = None
    filename: str = ""
    variables: list[tuple[str, str, str]] = field(default_factory=list)  # (이름, 유형, 값 라벨)
    signatures: dict[str, str] = field(default_factory=dict)            # 변수 또는 _all → 확인값

    @property
    def names(self) -> list[str]:
        return [v[0] for v in self.variables]


def parse_state(log_text: str) -> DataState | None:
    st = DataState()
    found = False
    for fields in extract_markers(log_text, "SASTATE"):
        if len(fields) < 2:
            continue
        found = True
        key, value = fields[0], "|".join(fields[1:])
        if key == "N":
            st.n = _int(value)
        elif key == "K":
            st.k = _int(value)
        elif key == "F":
            st.filename = value
    for fields in extract_markers(log_text, "SAVS"):
        if fields:
            st.variables.append((fields[0], fields[1] if len(fields) > 1 else "", fields[2] if len(fields) > 2 else ""))
    for fields in extract_markers(log_text, "SASIG"):
        if len(fields) >= 2 and fields[1]:
            st.signatures[fields[0]] = fields[1]
    return st if found else None


def _int(v: str) -> int | None:
    try:
        return int(float(v))
    except ValueError:
        return None


def diff_states(old: DataState, new: DataState) -> list[str]:
    """사람이 읽을 변경 목록(값 자체는 넣지 않음)."""
    out: list[str] = []
    if Path(old.filename or "").name != Path(new.filename or "").name and (old.filename or new.filename):
        out.append(f"다른 자료로 바뀜: {Path(old.filename).name or '(없음)'} → {Path(new.filename).name or '(없음)'}")
    if new.k == 0 and (old.k or 0) > 0:
        out.append("메모리 자료가 비워짐(clear 등)")
    if old.n != new.n:
        out.append(f"관측치 수 {old.n} → {new.n}")
    old_types = {v[0]: (v[1], v[2]) for v in old.variables}
    new_types = {v[0]: (v[1], v[2]) for v in new.variables}
    removed = [n for n in old.names if n not in new_types]
    added = [n for n in new.names if n not in old_types]
    renames: list[tuple[str, str]] = []
    per_var = bool(old.signatures and new.signatures and "_all" not in old.signatures and "_all" not in new.signatures)
    for name in list(removed):
        i = old.names.index(name)
        if i < len(new.names) and new.names[i] in added and new_types[new.names[i]][0] == old_types[name][0]:
            cand = new.names[i]
            # 이름만 바꾸면 값이 그대로 → 변수별 확인값이 있으면 같을 때만 이름 변경으로 봄(drop 후 새로 만든 경우와 구분)
            if per_var and old.signatures.get(name) != new.signatures.get(cand):
                continue
            renames.append((name, cand))
            added.remove(cand)
            removed.remove(name)
    if renames:
        out.append("변수 이름 변경 추정: " + ", ".join(f"{a} → {b}" for a, b in renames[:10]))
    if added:
        out.append("새 변수: " + ", ".join(added[:15]) + (f" 외 {len(added) - 15}개" if len(added) > 15 else ""))
    if removed:
        out.append("삭제된 변수: " + ", ".join(removed[:15]) + (f" 외 {len(removed) - 15}개" if len(removed) > 15 else ""))
    retyped = [n for n in new.names if n in old_types and old_types[n][0] != new_types[n][0]]
    if retyped:
        out.append("유형 변경: " + ", ".join(f"{n}({old_types[n][0]}→{new_types[n][0]})" for n in retyped[:10]))
    relabeled = [n for n in new.names if n in old_types and old_types[n][1] != new_types[n][1]]
    if relabeled:
        out.append("값 라벨 연결 변경: " + ", ".join(relabeled[:10]))
    rename_map = {b: a for a, b in renames}
    if old.signatures and new.signatures:
        if "_all" in old.signatures or "_all" in new.signatures:
            if old.signatures.get("_all") != new.signatures.get("_all") and not (removed or added or renames):
                out.append("값 변경 감지(리코드·replace 등, 변수가 많아 어느 변수인지는 미특정)")
        else:
            changed = [n for n in new.names
                       if (src := rename_map.get(n, n)) in old.signatures and n in new.signatures
                       and old.signatures[src] != new.signatures[n] and n not in retyped]
            if changed:
                out.append("값 변경 감지(리코드·replace 등): " + ", ".join(changed[:15]))
    return out


class CmdlogReader:
    """Stata cmdlog 파일의 새 줄 읽기. AI 실행 직후 mark_end()로 위치를 끝으로 옮겨 AI 명령을 제외."""

    def __init__(self, path: Path):
        self.path = path
        self.offset = 0
        self.enabled = False

    def mark_end(self) -> None:
        if self.path.is_file():
            self.offset = self.path.stat().st_size

    def read_new(self) -> list[str]:
        if not self.path.is_file():
            return []
        data = self.path.read_bytes()
        if len(data) < self.offset:  # 파일이 새로 만들어짐
            self.offset = 0
        new = data[self.offset:]
        self.offset = len(data)
        lines = []
        for line in new.decode("utf-8", errors="replace").splitlines():
            s = line.strip()
            if not s or s.startswith(("SASTATE", "SAVS", "SASIG")) or "__sast" in s or "__sav" in s:
                continue
            lines.append(s)
        return lines


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class FileWatch:
    """AI가 마지막으로 쓰거나 읽은 내용과 디스크 내용 비교(섹션 단위 변경 보고)."""

    def __init__(self, parse: Callable[[str], object]):
        self.parse = parse
        self.known: dict[str, str] = {}

    def remember(self, path: Path, text: str) -> None:
        self.known[str(path)] = text

    def changes(self, path: Path, current: str) -> list[str]:
        old = self.known.get(str(path))
        self.known[str(path)] = current
        if old is None or _digest(old) == _digest(current):
            return []
        try:
            a, b = self.parse(old), self.parse(current)
        except Exception:  # noqa: BLE001 — 형식이 깨졌으면 파일 단위로만 알림
            return [f"{path.name}: 연구자 수정 감지(섹션 구조 해석 불가)"]
        old_secs = {s.id: s for s in a.sections}
        new_secs = {s.id: s for s in b.sections}
        parts = []
        changed = [sid for sid in new_secs if sid in old_secs and new_secs[sid].code() != old_secs[sid].code()]
        added = [sid for sid in new_secs if sid not in old_secs]
        removed = [sid for sid in old_secs if sid not in new_secs]
        if changed:
            parts.append("변경 " + ", ".join(changed))
        if added:
            parts.append("추가 " + ", ".join(added))
        if removed:
            parts.append("삭제 " + ", ".join(removed))
        if [ln for ln in a.header if ln.strip()] != [ln for ln in b.header if ln.strip()]:
            parts.append("머리말 변경")
        return [f"{path.name}: 연구자 수정 감지(" + ("; ".join(parts) or "섹션 밖 변경") + ") → 디스크 내용 기준으로 이어 감"]
