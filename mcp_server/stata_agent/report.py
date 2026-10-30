"""점검 보고서(설계서 §13.2) — 오류 공유용 단일 HTML.

포함: 앱 종류, MCP 서버 버전, Stata 버전·에디션·라이선스 유효 여부, OS, T1~T10 결과
제외: 라이선스 일련번호·등록자, 사용자 자료 경로·변수명·분석 로그 원문
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path

from .selftest import TestResult

_STATUS = {"pass": ("통과", "ok"), "fail": ("실패", "bad"), "skip": ("생략", "muted"), "manual": ("육안 확인", "warn")}


def sanitize(text: str) -> str:
    """홈 폴더 경로를 ~로 치환해 사용자 이름 노출 방지."""
    home = str(Path.home())
    out = str(text).replace(home, "~").replace(home.replace("\\", "/"), "~")
    out = re.sub(r"(?i)[A-Z]:\\Users\\[^\\\s]+", r"~", out)
    return out


def render_report(results: list[TestResult], meta: dict) -> str:
    """meta["software"](기본 "Stata")와 meta["software_info"](없으면 meta["stata"])로 패키지별 표기."""
    rows = []
    for r in results:
        label, cls = _STATUS.get(r.status, (r.status, "muted"))
        rows.append(
            f"<tr><td>{r.id}</td><td>{html.escape(r.name)}</td><td class='{cls}'>{label}</td>"
            f"<td>{html.escape(sanitize(r.detail))}</td><td>{html.escape(r.remedy)}</td></tr>"
        )
    software = meta.get("software") or "Stata"
    stata = meta.get("software_info") or meta.get("stata") or {}
    info = [
        ("작성 시각", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("앱", meta.get("client")),
        ("MCP 서버 버전", meta.get("server_version")),
        ("백엔드", meta.get("backend")),
        (software, f"{stata.get('edition') or ''} {stata.get('version') or '?'}".strip()),
        ("라이선스 유효", {True: "예", False: "아니오", None: "미확인"}.get(stata.get("license_valid"))),
        ("라이선스 만료일", stata.get("expires") or "영구 또는 미확인"),
        ("운영체제", meta.get("os")),
    ]
    info_rows = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(str(v))}</td></tr>" for k, v in info)
    fails = [r.id for r in results if r.status == "fail"]
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(software)} 에이전트 점검 보고서</title>
<style>
:root{{--bg:#fff;--fg:#1d2330;--muted:#5b6474;--line:#d9dee7;--soft:#f4f6f9;--ok:#1d7a46;--warn:#a15c00;--bad:#a11d2f}}
@media (prefers-color-scheme: dark){{:root{{--bg:#14171c;--fg:#e4e8ee;--muted:#9aa3b2;--line:#2c323c;--soft:#1c2027;--ok:#6fcf97;--warn:#f2b45c;--bad:#f08a96}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font-family:"Pretendard","Noto Sans KR","Malgun Gothic",system-ui,sans-serif;line-height:1.6}}
main{{max-width:960px;margin:0 auto;padding:24px 16px}}
table{{width:100%;border-collapse:collapse;margin:12px 0;font-size:14px}}
th,td{{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}}
th{{background:var(--soft)}} .ok{{color:var(--ok)}} .warn{{color:var(--warn)}} .bad{{color:var(--bad)}} .muted{{color:var(--muted)}}
p.note{{color:var(--muted);font-size:13px}}
</style></head><body><main>
<h1>{html.escape(software)} 에이전트 점검 보고서</h1>
<p class="note">오류 보고 시 이 파일만 첨부. 라이선스 일련번호·등록자, 자료 경로·변수명·분석 로그 원문은 포함하지 않음.</p>
<table>{info_rows}</table>
<h2>점검 결과 (T1~T10)</h2>
<p>실패 항목: {", ".join(fails) if fails else "없음"}</p>
<table><tr><th>#</th><th>항목</th><th>결과</th><th>내용</th><th>조치</th></tr>{"".join(rows)}</table>
</main></body></html>
"""


def save_report(results: list[TestResult], meta: dict, report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"점검보고서_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    path.write_text(render_report(results, meta), encoding="utf-8")
    return path
