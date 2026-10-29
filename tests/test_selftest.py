from fakes import FakeBackend
from stata_agent.discovery import AboutInfo, ComRegistration, DiscoveryReport, StataInstall
from stata_agent.report import render_report, save_report
from stata_agent.selftest import results_table, run_selftest
from stata_agent.service import StataAgentService


class FakeBatch(FakeBackend):
    name = "fake_batch"

    def __init__(self):
        super().__init__(persistent=False)


def _discovery():
    inst = StataInstall("C:/Stata18/StataSE-64.exe", "SE", 18, "scan")
    inst.about = AboutInfo(product="Stata", edition="SE", version="18.0", perpetual=True, parsed=True,
                           serial="999999", licensed_to=["Secret Person"])
    return DiscoveryReport([inst], inst, ComRegistration(True, inst.exe))


def test_selftest_all_pass_with_fake(settings):
    svc = StataAgentService(settings, backend=FakeBackend(), batch=FakeBatch(), discovery_report=_discovery())
    results, meta = run_selftest(svc, "Claude Desktop", release_lookup=lambda: "v0.1.0")
    status = {r.id: r.status for r in results}
    assert status == {"T1": "pass", "T2": "pass", "T3": "pass", "T4": "pass", "T5": "pass",
                      "T6": "pass", "T7": "manual", "T8": "pass", "T9": "pass", "T10": "pass"}, results_table(results)
    html = render_report(results, meta)
    assert "999999" not in html and "Secret Person" not in html  # §13.2 제외 항목
    assert "SE 18.0" in html


def test_selftest_detects_wrong_values_and_offline(settings):
    def wrong(code, state):
        if "SAT4" in code:
            return "SAT4|N|74\nSAT4|mean|6000\nSAT4|sd|2949.496\nSAT4|r|.946\n"
        from fakes import default_responder
        return default_responder(code, state)

    def offline():
        raise OSError("blocked")

    svc = StataAgentService(settings, backend=FakeBackend(responder=wrong), batch=FakeBatch(),
                            discovery_report=_discovery())
    results, meta = run_selftest(svc, include_batch=False, release_lookup=offline)
    status = {r.id: r.status for r in results}
    assert status["T4"] == "fail" and status["T9"] == "skip" and status["T10"] == "skip"
    path = save_report(results, meta, settings.report_dir)
    assert path.name.startswith("점검보고서_") and path.is_file()
