""".sps 문법 파일 규약(Stata do-file 규약 §10의 SPSS판).

    * ============================================================.
    * 04_regress.sps | 작성: AI / 승인: 연구자 / 계산: SPSS.
    * 생성일·수정 이력: .spss-agent/history.jsonl 참조.
    * ============================================================.

    *== [S01] 표본 정의 ==.
    GET FILE='data/survey.sav'.

- 섹션 표지 ``*== [S01] 제목 ==.``(마침표로 끝나는 SPSS 주석)이 편집·실행 단위
- 실행 결과는 엔진이 OMS로 수집(파일 안에 로그 명령을 두지 않음) → 전체 실행 시 ``output/logs/NN_result.txt``
- ``00_master.sps``: ``INSERT FILE='NN_이름.sps' SYNTAX=INTERACTIVE ERROR=STOP.`` 목록(INSERT 키워드는 [미확인])
- 파일은 UTF-8(BOM 포함)로 저장 [논리적 추론: SPSS가 인코딩을 인식하도록]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from stata_agent.dofile import DoFileError, backup_file, clean_title, normalize_section_id

SECTION_RE = re.compile(r"^\*==\s*\[(?P<id>S\d{2,3})\]\s*(?P<title>.*?)\s*==\.\s*$")
FILENAME_RE = re.compile(r"^(?P<nn>\d{2})_[A-Za-z0-9][A-Za-z0-9_-]*\.sps$")
MASTER_NAME = "00_master.sps"
RULE = "* " + "=" * 60 + "."
ENCODING = "utf-8-sig"

SyntaxFileError = DoFileError


def section_marker(section_id: str, title: str) -> str:
    return f"*== [{normalize_section_id(section_id)}] {clean_title(title)} ==."


def check_section_code(code: str) -> str:
    text = str(code or "").replace("\r\n", "\n").strip("\n")
    for line in text.split("\n"):
        if SECTION_RE.match(line.strip()):
            raise SyntaxFileError("섹션 코드 안에 섹션 표지(*== [Sxx] ... ==.)를 넣을 수 없음")
    return text


@dataclass
class Section:
    id: str
    title: str
    body: list[str] = field(default_factory=list)

    def code(self) -> str:
        return "\n".join(self.body).strip("\n")


@dataclass
class SyntaxFile:
    header: list[str]
    sections: list[Section]

    @classmethod
    def parse(cls, text: str) -> "SyntaxFile":
        header: list[str] = []
        sections: list[Section] = []
        for line in text.lstrip("﻿").replace("\r\n", "\n").split("\n"):
            m = SECTION_RE.match(line.strip())
            if m:
                sections.append(Section(m.group("id"), m.group("title")))
                continue
            (sections[-1].body if sections else header).append(line)
        ids = [s.id for s in sections]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            raise SyntaxFileError(f"섹션 번호 중복: {', '.join(dup)}")
        return cls(header, sections)

    def render(self) -> str:
        out = list(self.header)
        while out and not out[-1].strip():
            out.pop()
        for s in self.sections:
            body = list(s.body)
            while body and not body[0].strip():
                body.pop(0)
            while body and not body[-1].strip():
                body.pop()
            out += ["", section_marker(s.id, s.title), *body]
        return "\n".join(out).rstrip("\n") + "\n"

    def get(self, section_id: str) -> Section:
        sid = normalize_section_id(section_id)
        for s in self.sections:
            if s.id == sid:
                return s
        raise SyntaxFileError(f"섹션 없음: {sid} (있는 섹션: {', '.join(s.id for s in self.sections) or '없음'})")

    def next_id(self) -> str:
        nums = [int(s.id[1:]) for s in self.sections]
        return f"S{(max(nums) + 1 if nums else 1):02d}"

    def add(self, title: str, code: str, after: str | None = None, section_id: str | None = None) -> Section:
        sid = normalize_section_id(section_id) if section_id else self.next_id()
        if any(s.id == sid for s in self.sections):
            raise SyntaxFileError(f"이미 있는 섹션 번호: {sid}")
        sec = Section(sid, clean_title(title), check_section_code(code).split("\n"))
        if after:
            self.sections.insert(self.sections.index(self.get(after)) + 1, sec)
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


def validate_filename(filename: str) -> re.Match:
    m = FILENAME_RE.match(filename)
    if not m:
        raise SyntaxFileError(f"파일명 규약 위반: {filename} (예: 04_regress.sps — 두 자리 번호_영문명.sps)")
    if m.group("nn") == "00":
        raise SyntaxFileError("00_master.sps는 자동 관리 대상 → 01 이상 번호 사용")
    return m


def result_relpath(filename: str) -> str:
    return f"output/logs/{FILENAME_RE.match(filename).group('nn')}_result.txt"  # type: ignore[union-attr]


def render_header(filename: str, author: str = "AI") -> list[str]:
    return [
        RULE,
        f"* {filename} | 작성: {author} / 승인: 연구자 / 계산: SPSS.",
        "* 생성일·수정 이력: .spss-agent/history.jsonl 참조.",
        RULE,
    ]


def new_syntax(filename: str, sections: list[tuple[str, str]], author: str = "AI") -> str:
    validate_filename(filename)
    doc = SyntaxFile(render_header(filename, author), [])
    for title, code in sections:
        doc.add(title, code)
    return doc.render()


_INSERT_RE = re.compile(r"^\s*INSERT\s+FILE\s*=\s*['\"](?P<name>\d{2}_[^'\"]+\.sps)['\"]", re.IGNORECASE)


def insert_line(filename: str) -> str:
    return f"INSERT FILE='{filename}' SYNTAX=INTERACTIVE ERROR=STOP."


def render_master(files: list[str]) -> str:
    lines = [
        RULE,
        f"* {MASTER_NAME} | 전체 재현 진입점 / 계산: SPSS.",
        "* 아래 INSERT 목록은 spss_write_syntax가 자동 갱신함(수동 추가 가능).",
        RULE,
        "",
    ]
    lines += [insert_line(f) for f in sorted(set(files))]
    return "\n".join(lines) + "\n"


def master_entries(text: str) -> list[str]:
    return [m.group("name") for line in text.lstrip("﻿").splitlines() if (m := _INSERT_RE.match(line))]


def ensure_master_includes(master_text: str | None, filename: str) -> str:
    if master_text is None:
        return render_master([filename])
    entries = master_entries(master_text)
    if filename in entries:
        return master_text
    lines = master_text.lstrip("﻿").rstrip("\n").split("\n")
    insert_at, last = len(lines), None
    for idx, line in enumerate(lines):
        m = _INSERT_RE.match(line)
        if m:
            last = idx
            if m.group("name") > filename:
                insert_at = idx
                break
    else:
        insert_at = (last + 1) if last is not None else len(lines)
    lines.insert(insert_at, insert_line(filename))
    return "\n".join(lines) + "\n"


__all__ = [
    "ENCODING", "MASTER_NAME", "Section", "SyntaxFile", "SyntaxFileError", "backup_file",
    "ensure_master_includes", "master_entries", "new_syntax", "render_master", "result_relpath",
    "section_marker", "validate_filename",
]
