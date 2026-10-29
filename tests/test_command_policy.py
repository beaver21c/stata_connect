import pytest

from stata_agent.guard.command_policy import Action, check

ROOT = "/proj"


def act(code, known=None, reader=None):
    return check(code, ROOT, known_variables=known, read_file=reader).action


# 설계서 §8.1 차단 대상 전수
BLOCKED = [
    "list", "list in 1/3", "l make", "li", "quietly list price", "bysort foreign: list make",
    "capture noisily list", "browse", "br", "edit", "ed price",
    "display price[1]", "di price[_n]", "display `=price[1]'", "display \"`=price[1]'\"",
    "mata: st_data(., .)", "mata\nX = st_data(.,.)\nend",
    "shell dir", "sh dir", "!del x", "winexec notepad", "xshell ls",
    "erase x.dta", "rm x.dta", "rmdir out",
    "log close _all", "capture log close _all",
    "python:\nimport os\nend", "python script x.py",
    "listtab make using x.tex", "duplicates list make", "type data/raw.csv",
    "exit, clear STATA",
    'export delimited using "C:/Users/x/out.csv"',
    'export excel using "../outside.xlsx"',
    'outsheet using "/tmp/x.csv"',
    'outfile using "/elsewhere/x.raw"',
    'save "/tmp/x.dta", replace',
    'save "data/raw.dta", replace',
    'saveold data/raw2.dta',
    'copy "a.dta" "/tmp/b.dta"',
]

ALLOWED = [
    "summarize price mpg",
    "regress price mpg weight, vce(robust)",
    "display _b[weight]",
    "display _se[weight] / 2",
    "display e(r2)",
    "display r(mean)",
    'display "평균: " %9.2f r(mean)',
    "display M[1,2]",
    "matrix list e(b)",
    "label list origin",
    "return list",
    "generate lag = price[_n-1]",
    'save "output/clean.dta", replace',
    'log using "output/logs/01_result.log", text replace name(_nmlog)',
    "capture log close _nmlog",
    "estat vif",
    "tabstat price, by(foreign)",
    "pwcorr price mpg, sig obs",
    "* list 는 주석",
    "// browse",
]


@pytest.mark.parametrize("code", BLOCKED)
def test_blocked(code):
    assert act(code) == Action.BLOCK, code


@pytest.mark.parametrize("code", ALLOWED)
def test_allowed(code):
    assert act(code) <= Action.ALLOW, code


@pytest.mark.parametrize("code", [
    "cd ..",
    "ssc install estout",
    "`mycmd' price",
    "local first = make[1]",
    'export delimited using "output/x.csv"',
    "save, replace",
    "save \"`out'\"",
    'do "missing.do"',
    "mata: stata(cmd)",
])
def test_needs_approval(code):
    assert act(code) == Action.APPROVE, code


def test_tab_family_warns_and_collects_vars():
    r = check("tab foreign rep78\nlevelsof make, local(m)\ncodebook", ROOT)
    assert r.action == Action.WARN
    assert r.identifier_vars == ["foreign", "rep78", "make", "_all"]


def test_display_bare_variable_blocked_when_known():
    known = {"price", "mpg"}
    assert act("display price", known) == Action.BLOCK
    assert act("di pri", known) == Action.BLOCK  # 변수 약어
    assert act("display round(price, 1)", known) == Action.BLOCK
    assert act("display _b[price]", known) == Action.ALLOW
    assert act("display r(mean)", known) == Action.ALLOW
    assert act('display "price"', known) == Action.ALLOW
    assert act("display _N", known) == Action.ALLOW


def test_mata_stata_literal_recursed():
    assert act('mata: stata("list make")') == Action.BLOCK
    assert act('mata: stata("summarize price")') == Action.ALLOW


def test_include_recursion():
    files = {"/proj/01_a.do": "summarize\ndo 02_b.do\n", "/proj/02_b.do": "list make\n"}
    r = check('do "01_a.do"', ROOT, read_file=files.get)
    assert r.action == Action.BLOCK
    assert any(f.source == "02_b.do" for f in r.findings)


def test_windows_root_paths():
    r = check('save "C:/proj/output/x.dta", replace\nsave "D:/x.dta"', "C:\\proj")
    assert [f.action for f in r.findings] == [Action.BLOCK]
    assert check('save "c:\\PROJ\\output\\y.dta"', "C:\\proj").action == Action.ALLOW


def test_summary_text_lists_rules():
    r = check("list\nbrowse", ROOT)
    s = r.summary()
    assert "G01" in s and "차단" in s
    assert r.to_dict()["action"] == "차단"
