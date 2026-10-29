from stata_agent.guard.output_filter import (
    FilterConfig,
    clean_frame_lines,
    extract_markers,
    filter_output,
    last_return_code,
)

LIST_LOG = """\
. summarize price

    Variable |        Obs        Mean    Std. dev.       Min        Max
-------------+---------------------------------------------------------
       price |         74    6165.257    2949.496       3291      15906

. foreach v in make {
  2.     list `v' in 1/2
  3. }

     +-------------+
     | make        |
     |-------------|
  1. | AMC Concord |
  2. | AMC Pacer   |
     +-------------+
"""


def test_list_rows_redacted_but_other_output_kept():
    r = filter_output(LIST_LOG, log_path="C:/p/run.log")
    assert "AMC" not in r.text
    assert "6165.257" in r.text
    assert "[차단됨" in r.text and "run.log" in r.text
    assert r.blocked_any


def test_row_command_block_redacted():
    r = filter_output(". list make\n  some output\n")
    assert "some output" not in r.text
    assert r.events[0].reason.startswith("행 단위")


def _tab(rows, freq=1):
    lines = [". tab id", "         id |      Freq.     Percent        Cum.", "------------+-----------------------------------"]
    for i in range(rows):
        lines.append(f"     A{i:04d} |          {freq}        1.00       {i + 1:.2f}")
    lines.append("------------+-----------------------------------")
    lines.append("      Total |        100      100.00")
    return "\n".join(lines) + "\n"


def test_singleton_frequency_table_redacted():
    r = filter_output(_tab(12))
    assert "A0001" not in r.text
    assert "식별자" in r.events[0].reason


def test_small_frequency_table_kept():
    r = filter_output(_tab(3))
    assert "A0001" in r.text and not r.events


def test_small_cell_masking():
    log = """\
. tab rep78 foreign

    Repair |
    Record |       Car origin
      1978 |  Domestic    Foreign |     Total
-----------+----------------------+----------
         1 |         2          0 |         2
         3 |        27          3 |        30
-----------+----------------------+----------
     Total |        48         21 |        69
"""
    r = filter_output(log, FilterConfig(mask_small_cells=5))
    assert "<5" in r.text
    assert "27" in r.text and "30" in r.text
    assert "Domestic    Foreign" in r.text  # 머리글 유지
    assert r.masked_cells == 3  # 2, 2, 3


def test_frame_lines_removed():
    log = """\
-------------------------------------------------------------------------------
      name:  __stata_mcp_run
       log:  C:/p/.stata-mcp/cache/run_x.log
  log type:  text
 opened on:  29 Oct 2026, 10:00:00

. cd "C:/p"

. do "C:/p/.stata-mcp/cache/selection_x_abc.do"

. summarize price
"""
    out = clean_frame_lines(log)
    assert "__stata_mcp_run" not in out and "opened on" not in out
    assert "selection_" not in out
    assert ". summarize price" in out


def test_truncation():
    r = filter_output("x" * 50 + "\n" + "y" * 50_000, FilterConfig(max_chars=1000))
    assert r.truncated and len(r.text) < 1200 and "중략" in r.text


def test_markers_and_return_code():
    text = '. display "SAT4|N|" r(N)\nSAT4|N|74\nr(198);\n'
    assert extract_markers(text, "SAT4") == [["N", "74"]]
    assert last_return_code(text) == 198
    assert last_return_code("ok") == 0
