"""그래프 보기(IMPLEMENTATION_STATUS §15) — AI가 그래프 그림을 확인하되 원자료 비전송 원칙(P2)과 충돌하지 않게
그림을 만든 명령을 보고 등급을 나눔.

배경(2026-11-01 사용자 결정): "그래프는 AI가 볼 수 있어야 함". 설계서에는 그래프 항목이 없음 → 설계 확장.
그림은 텍스트 출력 필터(filter_output)를 거칠 수 없는 새 전송 경로이므로 아래 등급으로 관리함.

| 등급 | 예 | 처리 |
|---|---|---|
| aggregate(집계·분포) | histogram·kdensity·graph bar/box/pie/dot·marginsplot·coefplot·적합선만 있는 twoway·collapse 뒤 그림 | 바로 반환 |
| points(관측치별 표시) | scatter·line·graph matrix·잔차 그림·graph bar (asis) | 연구자 승인 후 반환 |
| labeled(관측치 값 글자) | mlabel() — 점마다 변수 값이 글자로 찍힘(식별자면 list와 같음) | 승인(강한 경고) |
| unknown(출처 미확인) | graph use·combine·연구자가 창에서 만든 그림·매크로 명령 | 승인 |

판정은 명령 문자열 기준 정적 추정임(논리적 추론). 집단별 그림(over()·by())은 보기 직전에 집단 변수의
고유값 비율을 점검해 식별자 성격이면 승인으로 올림(tabulate의 G14와 같은 기준). 관측치 1개짜리 집단 등
자료 내용에 따라 개별 값이 드러나는 경우는 정적 판정으로 모두 걸러내지 못함 [한계].
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .guard.stata_lexer import abbrev_match, iter_statements, parse_command, split_first_token, unquote

AGGREGATE, POINTS, LABELED, UNKNOWN = "aggregate", "points", "labeled", "unknown"
KIND_LABEL = {
    AGGREGATE: "집계·분포 그래프",
    POINTS: "관측치별 점·선 그래프",
    LABELED: "관측치 값 글자 표시 그래프",
    UNKNOWN: "출처 미확인 그래프",
}
_RANK = {AGGREGATE: 0, UNKNOWN: 1, POINTS: 2, LABELED: 3}

# 이미지 반환 형식(Claude가 읽는 형식만). 그 밖은 PNG로 다시 내보내도록 안내
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif"}
GRAPH_FILE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".svg", ".pdf", ".eps", ".ps", ".emf",
                       ".wmf", ".gph")

# twoway 그림 종류
_TW_AGGREGATE = {"lfit", "qfit", "lfitci", "qfitci", "fpfit", "fpfitci", "lpoly", "lpolyci", "lowess", "mspline",
                 "mband", "function", "histogram", "kdensity", "scatteri", "pci", "pcarrowi"}
_TW_POINTS = {"scatter", "sc", "line", "connected", "area", "bar", "spike", "dropline", "dot", "rarea", "rbar",
              "rspike", "rcap", "rcapsym", "rscatter", "rline", "rconnected", "pcspike", "pccapsym", "pcarrow",
              "pcbarrow", "pcscatter", "tsline", "tsrline", "contour", "contourline"}
# twoway 밖 그래프 명령
_CMD_AGGREGATE = {"histogram", "hist", "histo", "histog", "histogr", "histogra", "kdensity", "kdens", "marginsplot",
                  "coefplot", "binscatter", "binscatter2", "binsreg", "stcurve", "pnorm", "qnorm", "pchi", "qchi",
                  "quantile", "qqplot", "dotplot", "spikeplot", "symplot", "lroc", "lsens", "rocplot", "roccomp",
                  "ac", "pac", "corrgram", "pergram", "cumul", "catplot", "tabplot", "cibar", "ciplot", "heatplot",
                  "vioplot", "ltable"}
_CMD_POINTS = {"scatter", "sc", "line", "tsline", "tsrline", "avplot", "avplots", "cprplot", "acprplot", "lvr2plot",
               "rvfplot", "rvpplot", "lowess", "xtline", "stripplot", "beeswarm"}
_GRAPH_AGGREGATE_SUB = {"bar", "hbar", "box", "hbox", "dot", "pie"}
_AGGREGATING = (("collapse", "collapse"), ("contract", "contract"), ("statsby", "statsby"))
_RELOAD = (("use", "u"), ("sysuse", "sysuse"), ("webuse", "webuse"), ("restore", "restore"), ("clear", "clear"),
           ("import", "import"), ("insheet", "insheet"), ("infile", "infile"), ("frame", "frame"))

_MLABEL = re.compile(r"\bmla(?:b|be|bel)?\s*\(\s*[^)\s]", re.IGNORECASE)
_NAME_OPT = re.compile(r"\bname\s*\(\s*([A-Za-z_]\w*)", re.IGNORECASE)
_SAVING_OPT = re.compile(r"\bsaving\s*\(\s*(\"[^\"]*\"|`\"[^\"]*\"'|[^,\s)]+)", re.IGNORECASE)
_GROUP_OPT = re.compile(r"\b(?:over|by)\s*\(\s*([A-Za-z_][\w ]*?)\s*[,)]", re.IGNORECASE)
_ASIS = re.compile(r"\(\s*asis\s*\)", re.IGNORECASE)


def is_graph_cmd(name: str) -> bool:
    return abbrev_match(name, "graph", "gr")


@dataclass
class GraphInfo:
    kind: str
    reasons: list[str] = field(default_factory=list)
    command: str = ""          # 판정 근거 명령(앞 80자)
    group_vars: list[str] = field(default_factory=list)
    source: str = "ai"         # ai | researcher | project-file

    @property
    def needs_approval(self) -> bool:
        return self.kind != AGGREGATE

    def label(self) -> str:
        return KIND_LABEL[self.kind]


def stricter(a: GraphInfo | None, b: GraphInfo | None) -> GraphInfo | None:
    if a is None or b is None:
        return a or b
    return a if _RANK[a.kind] >= _RANK[b.kind] else b


def _unknown(why: str, command: str = "", source: str = "ai") -> GraphInfo:
    return GraphInfo(UNKNOWN, [why], command[:80], [], source)


def _twoway_plots(args: str) -> list[str]:
    """twoway 인자에서 그림 종류 목록. ``(scatter y x) (lfit y x)``·``scatter y x || lfit y x`` 모두 처리."""
    plots: list[str] = []
    if args.lstrip().startswith("("):  # 괄호형: 최상위 괄호 묶음마다 그림 1개(뒤의 옵션 괄호는 쉼표 뒤라 제외)
        depth, cur = 0, ""
        for ch in args:
            if depth == 0 and ch == ",":
                break
            if ch == "(":
                depth += 1
                if depth == 1:
                    cur = ""
                    continue
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    plots.append(cur)
                    continue
            if depth >= 1:
                cur += ch
    else:  # || 구분형: 구간마다 첫 낱말
        plots = re.split(r"\|\|", args)
    names = []
    for p in plots:
        m = re.match(r"\s*([A-Za-z_]\w*)", p)
        if m:
            names.append(m.group(1).lower())
    return names


def classify(name: str, args: str, text: str, aggregated: bool = False, source: str = "ai") -> GraphInfo | None:
    """그래프를 그리는 문장이면 GraphInfo, 아니면 None."""
    kind, reasons = None, []
    sub_args = args
    if is_graph_cmd(name):
        sub, rest = (args.split(None, 1) + [""])[:2]
        sub = sub.lower()
        if abbrev_match(sub, "twoway", "tw"):
            name, sub_args = "twoway", rest
        elif sub in _GRAPH_AGGREGATE_SUB:
            if _ASIS.search(rest) and re.search(r"\bover\s*\(", rest, re.IGNORECASE):
                kind, reasons = LABELED, ["(asis)+over() — 관측치 값을 막대·점으로 그리고 범주 이름을 표시"]
            elif _ASIS.search(rest):
                kind, reasons = POINTS, ["(asis) — 관측치 값을 그대로 막대·점으로 그림"]
            else:
                kind = AGGREGATE
        elif abbrev_match(sub, "matrix", "matrix"):
            kind, reasons = POINTS, ["graph matrix — 관측치마다 점"]
        elif sub == "combine":
            return _unknown("graph combine — 합친 그림의 출처 미확인", text, source)
        elif sub == "use":
            return _unknown("graph use — 저장된 그림을 불러옴(만든 명령 미확인)", text, source)
        else:
            return None  # export·save·display·drop·describe 등은 새 그림을 그리지 않음
    if name in {"twoway", "tw", "twowa"}:
        plots = _twoway_plots(sub_args)
        if not plots:
            return _unknown("twoway 그림 종류 해석 불가", text, source)
        unknown_plots = [p for p in plots if p not in _TW_AGGREGATE and p not in _TW_POINTS]
        point_plots = [p for p in plots if p in _TW_POINTS]
        if point_plots or unknown_plots:
            kind = POINTS
            reasons = [f"twoway {', '.join(point_plots + unknown_plots)} — 관측치마다 점·선"]
        else:
            kind = AGGREGATE
    elif kind is None:
        if name in _CMD_AGGREGATE or abbrev_match(name, "kdensity", "kdens"):
            kind = AGGREGATE
        elif name in _CMD_POINTS:
            kind, reasons = POINTS, [f"{name} — 관측치마다 점·선"]
        elif name == "lpoly":
            kind = AGGREGATE if re.search(r"\bnosc(?:atter)?\b", args, re.IGNORECASE) else POINTS
            if kind == POINTS:
                reasons = ["lpoly — 기본으로 관측치 산점도를 함께 그림(noscatter로 끌 수 있음)"]
        elif name == "sts" and re.match(r"^\s*gr(?:aph)?\b", args, re.IGNORECASE):
            kind = AGGREGATE
        else:
            return None
    if kind == POINTS and aggregated:
        kind, reasons = AGGREGATE, ["collapse·contract 뒤의 요약 자료 그림"]
    if _MLABEL.search(text):
        kind, reasons = LABELED, ["mlabel() — 점마다 변수 값을 글자로 표시(식별자면 원자료 행 출력과 같음)"]
    groups: list[str] = []
    for m in _GROUP_OPT.finditer(text):
        groups += [v for v in m.group(1).split() if v.lower() not in {"total", "missing"}]
    return GraphInfo(kind, reasons, text.strip()[:80], groups, source)


@dataclass
class GraphScan:
    files: dict[str, GraphInfo] = field(default_factory=dict)   # 파일 이름(소문자) → 판정
    named: dict[str, GraphInfo] = field(default_factory=dict)   # 그림 이름(소문자) → 판정
    current: GraphInfo | None = None
    drawn: int = 0
    exports: list[str] = field(default_factory=list)           # 내보낸 경로(코드에 쓴 그대로)

    def _put_file(self, target: str, info: GraphInfo) -> None:
        key = Path(target.replace("\\", "/")).name.lower()
        if not key:
            return
        self.files[key] = stricter(self.files.get(key), info) if key in self.files else info


def export_target(args_after_sub: str) -> str:
    """``graph export [using] 파일 [, 옵션]``의 파일(따옴표 포함 원문)."""
    using = re.match(r"^\s*using\b", args_after_sub, re.IGNORECASE)
    target, _ = split_first_token(args_after_sub[using.end():] if using else args_after_sub)
    return target


def save_target(args_after_sub: str) -> tuple[str | None, str]:
    """``graph save [그림이름] 파일 [, 옵션]`` → (그림 이름 또는 None, 파일 원문)."""
    before = args_after_sub.split(",", 1)[0]
    first, more = split_first_token(before)
    second, _ = split_first_token(more)
    return (first, second) if second else (None, first)


def scan_code(code: str, source: str = "ai", scan: GraphScan | None = None) -> GraphScan:
    """코드 안 그래프 명령을 따라가며 그림 이름·내보낸 파일별 등급 기록."""
    scan = scan or GraphScan()
    aggregated = False
    for st in iter_statements(code):
        if st.context != "stata":
            continue
        cmd = parse_command(st.text)
        name, args = cmd.name, cmd.args
        if any(abbrev_match(name, f, m) for f, m in _AGGREGATING):
            aggregated = True
            continue
        if any(abbrev_match(name, f, m) for f, m in _RELOAD):
            aggregated = False
            continue
        if name == "<macro>":
            continue
        if is_graph_cmd(name):
            sub, rest = (args.split(None, 1) + [""])[:2]
            low = sub.lower()
            if low in {"export", "save"}:
                if low == "export":
                    m = _NAME_OPT.search(rest.split(",", 1)[1] if "," in rest else "")
                    gname, target = (m.group(1) if m else None), export_target(rest)
                else:
                    gname, target = save_target(rest)
                target = unquote(target)
                info = scan.named.get(gname.lower()) if gname else scan.current
                info = info or _unknown("내보내기 전에 그린 그림을 이 코드에서 찾지 못함", st.text, source)
                if target:
                    scan._put_file(target, info)
                    scan.exports.append(target)
                continue
            if low == "display":
                m = re.match(r"\s*([A-Za-z_]\w*)", rest)
                if m:
                    scan.current = scan.named.get(m.group(1).lower()) or _unknown(
                        "graph display — 이 코드 밖에서 만든 그림", st.text, source)
                continue
            if low == "use":
                target, _ = split_first_token(rest)
                key = Path(unquote(target).replace("\\", "/")).name.lower()
                scan.current = scan.files.get(key) or scan.files.get(key + ".gph") or _unknown(
                    "graph use — 저장된 그림을 불러옴(만든 명령 미확인)", st.text, source)
                scan.drawn += 1
                continue
        info = classify(name, args, st.text, aggregated, source)
        if info is None:
            continue
        scan.drawn += 1
        scan.current = info
        m = _NAME_OPT.search(st.text)
        scan.named[(m.group(1) if m else "Graph").lower()] = info
        s = _SAVING_OPT.search(st.text)
        if s:
            target = unquote(s.group(1).strip("`'"))
            scan._put_file(target if Path(target).suffix else target + ".gph", info)
    return scan


def find_in_project(root: Path, filename: str, max_files: int = 300) -> GraphInfo | None:
    """프로젝트 do-file에서 이 그림 파일을 내보낸 명령을 찾아 판정(가장 엄격한 것). 원자료 폴더는 보지 않음."""
    key = Path(filename).name.lower()
    best: GraphInfo | None = None
    count = 0
    for path in sorted(Path(root).rglob("*.do")):
        rel = path.relative_to(root).parts
        if rel and (rel[0] in {"data", ".stata-agent", ".spss-agent"} or rel[0].startswith(".")):
            continue
        count += 1
        if count > max_files:
            break
        try:
            text = path.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            continue
        if key not in text.lower():
            continue
        info = scan_code(text, "project-file").files.get(key)
        if info is not None:
            best = stricter(best, info)
    return best


def png_size(data: bytes) -> tuple[int, int] | None:
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24 and data[12:16] == b"IHDR":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return None


__all__ = [
    "AGGREGATE", "POINTS", "LABELED", "UNKNOWN", "KIND_LABEL", "IMAGE_TYPES", "GRAPH_FILE_SUFFIXES",
    "GraphInfo", "GraphScan", "classify", "scan_code", "find_in_project", "png_size", "stricter", "is_graph_cmd",
]
