from stata_agent.log_compare import compare_logs

A = """\
      name:  _nmlog
 opened on:  29 Oct 2026, 10:00:00
. describe
Contains data from C:/Program Files/Stata18/ado/base/a/auto.dta
 Observations:            74                  1978 automobile data
. summarize price
       price |         74    6165.257    2949.496       3291      15906
"""


def test_equal_ignoring_dates_and_paths():
    b = A.replace("29 Oct 2026, 10:00:00", "30 Oct 2026, 11:11:11").replace("Stata18", "StataNow19")
    res = compare_logs(A, b)
    assert res.equal and res.verdict == "재현 일치"


def test_numeric_difference_detected():
    res = compare_logs(A, A.replace("6165.257", "6165.258"))
    assert not res.equal and res.verdict == "불일치 1건"
    assert res.diffs[0].a[1] == "6165.257"


def test_tolerance():
    assert compare_logs(A, A.replace("6165.257", "6165.2570001"), rel_tol=1e-6).equal
