"""그래프 보기(IMPLEMENTATION_STATUS §15): 등급 판정·graph export 경로 검사·이미지 반환·승인 흐름."""

import json

import pytest

from fakes import FAKE_PNG, FakeBackend
from stata_agent.graphs import AGGREGATE, LABELED, POINTS, UNKNOWN, classify, find_in_project, png_size, scan_code
from stata_agent.guard.command_policy import Action, check
from stata_agent.service import MAX_IMAGE_BYTES, StataAgentService

CODE = """
sysuse auto, clear
histogram price, name(h1)
graph export "output/figures/hist.png", name(h1) replace
twoway (scatter price mpg) (lfit price mpg)
graph export output/figures/sc.png, replace
twoway lfit price mpg || qfit price mpg
graph export "output/figures/fit.png", replace
scatter price mpg, mlabel(make)
graph export "output/figures/lab.png", replace
preserve
collapse (mean) price, by(rep78)
twoway bar price rep78
graph export "output/figures/bar.png", replace
restore
graph bar (mean) price, over(foreign)
graph export "output/figures/gbar.png", replace
graph hbar (asis) price, over(make)
graph export "output/figures/asis.png", replace
graph use "output/figures/old.gph"
graph export "output/figures/old.png", replace
qui tw sc price weight, saving(output/figures/s2, replace)
graph matrix price mpg weight, name(mat)
graph save mat "output/figures/mat.gph"
"""


def test_scan_kinds():
    s = scan_code(CODE)
    kinds = {k: v.kind for k, v in s.files.items()}
    assert kinds == {
        "hist.png": AGGREGATE, "sc.png": POINTS, "fit.png": AGGREGATE, "lab.png": LABELED, "bar.png": AGGREGATE,
        "gbar.png": AGGREGATE, "asis.png": LABELED, "old.png": UNKNOWN, "s2.gph": POINTS, "mat.gph": POINTS,
    }
    assert s.files["gbar.png"].group_vars == ["foreign"]  # 집단 변수는 보기 직전 고유값 점검 대상
    assert s.current.kind == POINTS and s.named["h1"].kind == AGGREGATE
    named = scan_code("histogram y, name(h)\nscatter y x\ngraph save h output/figures/h.gph, replace")
    assert {k: v.kind for k, v in named.files.items()} == {"h.gph": AGGREGATE}  # 이름 지정 그림을 저장


@pytest.mark.parametrize("line,kind", [
    ("kdensity price", AGGREGATE),
    ("marginsplot", AGGREGATE),
    ("graph box price, over(rep78)", AGGREGATE),
    ("lpoly price mpg", POINTS),
    ("lpoly price mpg, noscatter", AGGREGATE),
    ("rvfplot", POINTS),
    ("tsline gdp", POINTS),
    ("sts graph, by(arm)", AGGREGATE),
    ("twoway (scatteri 1 1 2 2)", AGGREGATE),
    ("twoway (myplot y x)", POINTS),  # 모르는 그림 종류는 보수적으로 관측치별
    ("scatter y x, mlab(id) mlabsize(small)", LABELED),
    ("scatter y x, mlabsize(small)", POINTS),  # 글자 크기 옵션만으로는 값 표시 아님
])
def test_classify_table(line, kind):
    from stata_agent.guard.stata_lexer import parse_command

    cmd = parse_command(line)
    assert classify(cmd.name, cmd.args, line).kind == kind


def test_non_graph_statements():
    from stata_agent.guard.stata_lexer import parse_command

    for line in ("regress y x", "graph export x.png", "graph dir", "summarize price"):
        cmd = parse_command(line)
        assert classify(cmd.name, cmd.args, line) is None


def test_guard_graph_paths(tmp_path):
    root = str(tmp_path)
    assert check('graph export "output/figures/a.png", replace', root).action == Action.ALLOW
    out = check('graph export "C:/Users/x/Desktop/a.png", replace', root)
    assert out.blocked and out.findings[0].rule == "G16"
    assert check('graph export "data/a.png"', root).blocked
    assert check("scatter y x, saving(data/s, replace)", root).blocked
    assert check('graph save "data/m.gph", replace', root).blocked
    assert check("graph save mat data/m.gph, replace", root).blocked  # 이름 + 파일 + 옵션 형식
    assert check("graph save mat output/figures/m.gph, replace", root).action == Action.ALLOW
    dyn = check('graph export "output/figures/`v\'.png", replace', root)
    assert dyn.action == Action.WARN and dyn.findings[0].rule == "G16"  # 그림은 자료가 아니므로 경고만


def test_find_in_project(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "05_fig.do").write_text('scatter y x\ngraph export "output/figures/f.png"\n', encoding="utf-8")
    (tmp_path / "data" / "x.do").write_text('histogram y\ngraph export "f.png"\n', encoding="utf-8")
    assert find_in_project(tmp_path, "f.png").kind == POINTS  # data/ 안 파일은 보지 않음
    assert find_in_project(tmp_path, "none.png") is None


def test_png_size():
    assert png_size(FAKE_PNG) == (1400, 1000) and png_size(b"GIF89a") is None


@pytest.fixture
def svc(settings, project):
    s = StataAgentService(settings, backend=FakeBackend(), batch=FakeBackend(persistent=False))
    assert not s.open_session(str(project)).is_error
    return s


def _run(svc, code, name="03_fig.do"):
    assert not svc.write_dofile(name, [{"title": "그림", "code": code}]).is_error
    return svc.run_section(name, "S01")


def test_aggregate_file_returned(svc, project):
    r = _run(svc, 'histogram price\ngraph export "output/figures/h.png", width(1400) replace')
    assert "그래프: output/figures/h.png(집계·분포 그래프)" in r.text and "stata_view_graph" in r.text
    v = svc.view_graph("output/figures/h.png")
    assert not v.is_error and v.images == [(FAKE_PNG, "image/png")] and "1400×1000px" in v.text
    hist = (project / ".stata-agent" / "history.jsonl").read_text(encoding="utf-8")
    rec = [json.loads(x) for x in hist.splitlines() if "stata_view_graph" in x][-1]
    assert rec["graph_kind"] == AGGREGATE and "PNG" not in hist  # 그림 내용은 기록하지 않음


def test_points_need_approval(svc):
    _run(svc, 'scatter price mpg\ngraph export "output/figures/s.png", replace')
    v = svc.view_graph("output/figures/s.png")
    assert v.is_error and not v.images and "연구자 확인 필요" in v.text and "scatter" in v.text
    ok = svc.view_graph("output/figures/s.png", acknowledge_risks=True)
    assert not ok.is_error and ok.images and "연구자 승인" in ok.text


def test_memory_graph_export_and_registry(svc, project):
    _run(svc, "histogram price, name(h1)\nscatter price mpg")
    cur = svc.view_graph()
    assert cur.is_error and "관측치별" in cur.text  # 현재 그래프 = 마지막에 그린 산점도
    named = svc.view_graph(graph_name="h1")
    assert not named.is_error and named.images
    sent = [c[1] for c in svc.backend.calls if c[0] == "code" and "graph export" in c[1]]
    assert sent and "name(h1)" in sent[-1] and ".stata-agent/graphs/view_h1_" in sent[-1]


def test_researcher_graph_from_cmdlog(svc, project):
    (project / ".stata-agent" / "cmdlog.txt").write_text("scatter price weight, mlabel(make)\n", encoding="utf-8")
    v = svc.view_graph()
    assert v.is_error and "글자" in v.text and "Stata 창에서 입력된 명령" in v.text


def test_identifier_group_raises_approval(svc):
    _run(svc, 'graph bar (mean) price, over(make)\ngraph export "output/figures/b.png", replace')
    v = svc.view_graph("output/figures/b.png")
    assert v.is_error and "식별자 성격" in v.text and "make" in v.text  # 가짜 백엔드: make 고유값 100%
    _run(svc, 'graph bar (mean) price, over(foreign)\ngraph export "output/figures/c.png", replace', "04_fig.do")
    assert not svc.view_graph("output/figures/c.png").is_error


def test_unknown_file_and_formats(svc, project):
    figs = project / "output" / "figures"
    figs.mkdir(parents=True, exist_ok=True)
    (figs / "made_by_hand.png").write_bytes(FAKE_PNG)
    v = svc.view_graph("output/figures/made_by_hand.png")
    assert v.is_error and "출처 미확인" in v.text
    (figs / "x.gph").write_bytes(b"x")
    assert "graph use" in svc.view_graph("output/figures/x.gph").text
    (figs / "x.svg").write_text("<svg/>")
    assert "PNG" in svc.view_graph("output/figures/x.svg").text
    (project / "data" / "p.png").write_bytes(FAKE_PNG)
    assert "원자료 폴더" in svc.view_graph("data/p.png").text
    assert svc.view_graph("../x.png").is_error
    big = figs / "big.png"
    big.write_bytes(FAKE_PNG + b"\0" * (MAX_IMAGE_BYTES + 1))
    assert "너무 큼" in svc.view_graph("output/figures/big.png", acknowledge_risks=True).text


def test_batch_mode_needs_file(settings, project):
    s = StataAgentService(settings, backend=FakeBackend(persistent=False), batch=FakeBackend(persistent=False))
    assert not s.open_session(str(project)).is_error
    assert "배치 모드" in s.view_graph().text
