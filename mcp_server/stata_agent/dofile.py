"""do-file·폴더 규약(설계서 §10)과 섹션 단위 편집(stata_write_dofile·stata_patch_dofile·stata_run_section).

헤더 규약
    * ============================================================
    * 04_regress.do | 작성: AI(모델명) / 승인: 연구자 / 계산: Stata
    * 생성일·수정 이력: .stata-agent/history.jsonl 참조
    * ============================================================
    version 19
    set more off
    capture log close _nmlog
    log using "output/logs/04_result.log", text replace name(_nmlog)

섹션 표지: ``*== [S01] 제목 ==*`` (편집·실행 기준 단위)
꼬리: ``log close _nmlog`` — 마지막 섹션 뒤의 ``log close``·빈 줄은 꼬리로 인식
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

LOG_NAME = "_nmlog"
SECTION_RE = re.compile(r"^\*==\s*\[(?P<id>S\d{2,3})\]\s*(?P<title>.*?)\s*==\*\s*$")
FILENAME_RE = re.compile(r"^(?P<nn>\d{2})_[A-Za-z0-9][A-Za-z0-9_-]*\.do$")
_FOOTER_LINE_RE = re.compile(r"^\s*((capture|cap)\s+)?log\s+close\b.*$|^\s*$", re.IGNORECASE)
MASTER_NAME = "00_master.do"
RULE = "* " + "=" * 60


class DoFileError(ValueError):
    pass


@dataclass
class Section:
    id: str
    title: str
    body: list[str] = field(default_factory=list)

    def marker(self) -> str:
        return section_marker(self.id, self.title)

    def code(self) -> str:
        return "\n".join(self.body).strip("\n")


@dataclass
class DoFile:
    header: list[str]
    sections: list[Section]
    footer: list[str]

    # ── 파싱·출력 ──
    @classmethod
    def parse(cls, text: str) -> "DoFile":
        lines = text.replace("\r\n", "\n").split("\n")
        header: list[str] = []
        sections: list[Section] = []
        for line in lines:
            m = SECTION_RE.match(line.strip())
            if m:
                sections.append(Section(m.group("id"), m.group("title")))
                continue
            (sections[-1].body if sections else header).append(line)
        # 꼬리 분리
        target = sections[-1].body if sections else header
        footer: list[str] = []
        while target and _FOOTER_LINE_RE.match(target[-1]):
            footer.insert(0, target.pop())
        ids = [s.id for s in sections]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise DoFileError(f"섹션 번호 중복: {', '.join(sorted(dup))}")
        return cls(header, sections, footer)

    def render(self) -> str:
        out: list[str] = list(self.header)
        while out and not out[-1].strip():
            out.pop()
        for s in self.sections:
            out.append("")
            out.append(s.marker())
            body = list(s.body)
            while body and not body[0].strip():
                body.pop(0)
            while body and not body[-1].strip():
                body.pop()
            out.extend(body)
        footer = [ln for ln in self.footer if ln.strip()]
        if footer:
            out.append("")
            out.extend(footer)
        return "\n".join(out).rstrip("\n") + "\n"

    # ── 조회·편집 ──
    def get(self, section_id: str) -> Section:
        sid = normalize_section_id(section_id)
        for s in self.sections:
            if s.id == sid:
                return s
        raise DoFileError(f"섹션 없음: {sid} (있는 섹션: {', '.join(s.id for s in self.sections) or '없음'})")

    def next_id(self) -> str:
        nums = [int(s.id[1:]) for s in self.sections]
        return f"S{(max(nums) + 1 if nums else 1):02d}"

    def add(self, title: str, code: str, after: str | None = None, section_id: str | None = None) -> Section:
        sid = normalize_section_id(section_id) if section_id else self.next_id()
        if any(s.id == sid for s in self.sections):
            raise DoFileError(f"이미 있는 섹션 번호: {sid}")
        sec = Section(sid, clean_title(title), check_section_code(code).split("\n"))
        if after:
            idx = self.sections.index(self.get(after)) + 1
            self.sections.insert(idx, sec)
        else:
            self.sections.append(sec)
        return sec

    def replace(self, section_id: str, code: str, title: str | None = None) -> Section:
        sec = self.get(section_id)
        sec.body = check_section_code(code).split("\n")
        if title:
            sec.title = clean_title(title)
        return sec

    def delete(self, section_id: str) -> Section:
        sec = self.get(section_id)
        self.sections.remove(sec)
        return sec


def normalize_section_id(section_id: str) -> str:
    s = str(section_id).strip().upper()
    if re.fullmatch(r"\d{1,3}", s):
        s = f"S{int(s):02d}"
    if not re.fullmatch(r"S\d{2,3}", s):
        raise DoFileError(f"섹션 번호 형식 오류: {section_id} (예: S03)")
    return s


def clean_title(title: str) -> str:
    t = re.sub(r"\s+", " ", str(title or "").strip())
    t = t.replace("==*", "").replace("*==", "")
    return t or "섹션"


def section_marker(section_id: str, title: str) -> str:
    return f"*== [{normalize_section_id(section_id)}] {clean_title(title)} ==*"


def check_section_code(code: str) -> str:
    text = str(code or "").replace("\r\n", "\n").strip("\n")
    for line in text.split("\n"):
        if SECTION_RE.match(line.strip()):
            raise DoFileError("섹션 코드 안에 섹션 표지(*== [Sxx] ... ==*)를 넣을 수 없음")
        if re.match(rf"^\s*((capture|cap)\s+)?log\s+(using|close)\b.*\b{LOG_NAME}\b", line, re.IGNORECASE):
            raise DoFileError(f"섹션 코드에서 {LOG_NAME} 로그를 열고 닫을 수 없음(헤더·꼬리가 관리)")
    return text


def validate_filename(filename: str) -> re.Match:
    m = FILENAME_RE.match(filename)
    if not m:
        raise DoFileError(f"파일명 규약 위반: {filename} (예: 04_regress.do — 두 자리 번호_영문명.do)")
    if m.group("nn") == "00":
        raise DoFileError("00_master.do는 자동 관리 대상 → 01 이상 번호 사용")
    return m


def log_relpath(filename: str) -> str:
    nn = FILENAME_RE.match(filename).group("nn")  # type: ignore[union-attr]
    return f"output/logs/{nn}_result.log"


def render_header(filename: str, version_line: str, author: str = "AI") -> list[str]:
    return [
        RULE,
        f"* {filename} | 작성: {author} / 승인: 연구자 / 계산: Stata",
        "* 생성일·수정 이력: .stata-agent/history.jsonl 참조",
        RULE,
        version_line,
        "set more off",
        f"capture log close {LOG_NAME}",
        f'log using "{log_relpath(filename)}", text replace name({LOG_NAME})',
    ]


def new_dofile(filename: str, sections: list[tuple[str, str]], version_line: str, author: str = "AI") -> str:
    validate_filename(filename)
    doc = DoFile(render_header(filename, version_line, author), [], [f"log close {LOG_NAME}"])
    for title, code in sections:
        doc.add(title, code)
    return doc.render()


def render_master(do_files: list[str], version_line: str) -> str:
    lines = [
        RULE,
        f"* {MASTER_NAME} | 전체 재현 진입점(배치 실행 기준) / 계산: Stata",
        "* 아래 do 목록은 stata_write_dofile이 자동 갱신함(수동 추가 가능)",
        RULE,
        version_line,
        "clear all",
        "set more off",
        "",
    ]
    lines += [f'do "{name}"' for name in sorted(set(do_files))]
    return "\n".join(lines) + "\n"


_MASTER_DO_RE = re.compile(r'^\s*do\s+"?(?P<name>\d{2}_[^"\s]+\.do)"?\s*$', re.IGNORECASE)


def master_entries(text: str) -> list[str]:
    return [m.group("name") for line in text.splitlines() if (m := _MASTER_DO_RE.match(line))]


def ensure_master_includes(master_text: str | None, filename: str, version_line: str) -> str:
    """00_master.do에 do 줄 추가(번호순 위치). 이미 있으면 그대로."""
    if master_text is None:
        return render_master([filename], version_line)
    if filename in master_entries(master_text):
        return master_text
    lines = master_text.rstrip("\n").split("\n")
    new_line = f'do "{filename}"'
    insert_at = len(lines)
    last_do = None
    for idx, line in enumerate(lines):
        m = _MASTER_DO_RE.match(line)
        if m:
            last_do = idx
            if m.group("name") > filename:
                insert_at = idx
                break
    else:
        insert_at = (last_do + 1) if last_do is not None else len(lines)
    lines.insert(insert_at, new_line)
    return "\n".join(lines) + "\n"


def backup_file(path: Path, project_root: Path) -> Path | None:
    if not path.is_file():
        return None
    bdir = project_root / ".stata-agent" / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    dest = bdir / f"{path.stem}.{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{path.suffix}"
    shutil.copy2(path, dest)
    return dest


def section_run_code(doc: DoFile, section_id: str, version_line: str | None = None) -> str:
    """섹션 단독 실행용 코드. 버전 선언을 앞에 붙여 대화형 세션에서도 같은 해석 보장."""
    sec = doc.get(section_id)
    head = []
    for line in doc.header:
        if re.match(r"^\s*version\s+\d", line):
            head = [line.strip()]
            break
    if not head and version_line:
        head = [version_line]
    return "\n".join(head + [f"* --- {sec.id} {sec.title} (섹션 단독 실행) ---", sec.code()]) + "\n"
