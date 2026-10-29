from stata_agent.guard.stata_lexer import (
    abbrev_match,
    find_top_level_colon,
    iter_statements,
    parse_command,
    split_statements,
)


def texts(code):
    return [t for _, t in split_statements(code)]


def test_comments_removed():
    code = """* 전체 주석
summarize price // 줄 끝 주석
/* 블록
   주석 */ regress price mpg
"""
    assert texts(code) == ["summarize price", "regress price mpg"]


def test_line_continuation_and_line_numbers():
    code = "regress price ///\n    mpg weight\ndisplay 1\n"
    st = split_statements(code)
    assert st[0] == (1, "regress price      mpg weight") or st[0][1].split() == ["regress", "price", "mpg", "weight"]
    assert st[1][0] == 3


def test_double_slash_inside_string_kept():
    assert texts('display "http://x // y"') == ['display "http://x // y"']


def test_delimit_semicolon_mode():
    code = "#delimit ;\nregress price\n  mpg;\nlist make;\n#delimit cr\ndisplay 1\n"
    t = texts(code)
    assert t[0].split() == ["regress", "price", "mpg"]
    assert t[1] == "list make"
    assert t[2] == "display 1"


def test_star_comment_with_continuation():
    code = "* 주석 ///\n  계속되는 주석\nsummarize\n"
    assert texts(code) == ["summarize"]


def test_block_comment_not_nested_is_conservative():
    # 중첩을 허용하지 않는 해석 → 첫 */ 뒤의 list가 코드로 남아 검사 대상이 됨
    code = "/* 바깥 /* 안쪽 */ list */\n"
    assert any("list" in t for t in texts(code))


def test_mata_and_python_blocks():
    code = "mata:\nX = st_data(., .)\nend\npython:\nimport os\nend\nsummarize\n"
    sts = iter_statements(code)
    ctx = [(s.context, s.text) for s in sts]
    assert ("mata", "X = st_data(., .)") in ctx
    assert any(c == "python" for c, _ in ctx)
    assert ("stata", "summarize") in ctx


def test_mata_one_liner():
    sts = iter_statements("mata: st_data(1, 1)")
    assert sts[0].context == "mata"


def test_prefix_stripping():
    assert parse_command("quietly capture noisily list make").name == "list"
    assert parse_command("bysort foreign: list make").name == "list"
    assert parse_command("by foreign, sort: summarize price").name == "summarize"
    assert parse_command("cap n li").name == "li"
    assert parse_command("frame f2: list").name == "list"
    pc = parse_command("local t : type price")
    assert pc.name == "local"


def test_shell_and_macro_commands():
    assert parse_command("!dir").name == "!"
    assert parse_command("`cmd' price").name == "<macro>"
    assert parse_command("$CMD price").name == "<macro>"


def test_abbrev_match():
    assert abbrev_match("l", "list", "l")
    assert abbrev_match("disp", "display", "di")
    assert not abbrev_match("d", "display", "di")
    assert not abbrev_match("label", "list", "l")


def test_find_top_level_colon():
    assert find_top_level_colon('by x (y): list') == 8
    assert find_top_level_colon('display "a:b"') is None
    assert find_top_level_colon("mata x::y") is None
