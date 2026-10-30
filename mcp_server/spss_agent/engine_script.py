"""SPSS 내장 Python에서 실행되는 엔진 스크립트(문자열). 서버가 파일로 써서 서브프로세스로 띄움.

동작
- ``spss.StartSPSS()``로 화면 없는 SPSS를 1회 기동 → 표준입력에서 JSON 요청을 한 줄씩 받아 처리
- 응답은 요청이 지정한 파일에 JSON으로 기록하고, 표준출력에는 완료 표지 한 줄만 씀
  (SPSS가 표준출력에 내보내는 잡음과 섞이지 않게 하기 위함)
- 요청 종류: ping / submit(문법 실행 + OMS 텍스트 출력 수집) / dictionary(변수 정보·결측 수) /
  unique(변수별 고유값 수) / exit

근거: spss.StartSPSS·Submit·GetLastErrorLevel·StopSPSS, SPSS 폴더의 Python3 사용 방식은
제3자 구현(spss-mcp-extended 2.0.0) 소스로 확인 [2차 확인]. 변수 정보 함수(GetVariableName 등)와
Cursor는 IBM 문서 원문 미열람 [미확인] → Windows·SPSS 실기 검증 대상.
"""

ENGINE_SCRIPT = r'''
import sys, os, json, traceback

SPSS_HOME = sys.argv[1]
os.environ["PATH"] = SPSS_HOME + os.pathsep + os.environ.get("PATH", "")
for sub in (("Python3", "Lib", "site-packages"),):
    p = os.path.join(SPSS_HOME, *sub)
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass
_out = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)


def signal(text):
    _out.write(text + "\n")
    _out.flush()


try:
    import spss
    spss.StartSPSS()
    signal("__SA_READY__")
except Exception as e:
    signal("__SA_FAIL__ " + repr(e).replace("\n", " ")[:500])
    sys.exit(1)


def quiet(fn, *a, **k):
    saved = os.dup(1)
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 1)
    os.close(devnull)
    try:
        return fn(*a, **k)
    finally:
        os.dup2(saved, 1)
        os.close(saved)


def op_submit(req):
    tag = "SA" + str(req["id"])
    outfile = req["outfile"].replace("\\", "/")
    wrapped = (
        "OMS /TAG='" + tag + "' /SELECT ALL /DESTINATION FORMAT=TEXT OUTFILE='" + outfile + "'.\n"
        + req["syntax"].rstrip() + "\n"
        + "OMSEND TAG='" + tag + "'.\n"
    )
    error = None
    level = 0
    try:
        quiet(spss.Submit, wrapped)
    except Exception as e:
        error = str(e)
    try:
        level = spss.GetLastErrorLevel()  # 정리 명령보다 먼저 읽어야 실패 수준이 남음
    except Exception:
        pass
    if error is not None:
        try:
            quiet(spss.Submit, "OMSEND TAG='" + tag + "'.")
        except Exception:
            pass
    return {"ok": error is None and level < 3, "err_level": level, "error": error,
            "output_exists": os.path.exists(req["outfile"])}


def _var_index():
    return {spss.GetVariableName(i): i for i in range(spss.GetVariableCount())}


def _execute_pending():
    try:
        quiet(spss.Submit, "EXECUTE.")
    except Exception:
        pass


def op_dictionary(req):
    n_vars = spss.GetVariableCount()
    variables = []
    for i in range(n_vars):
        t = spss.GetVariableType(i)
        variables.append({
            "name": spss.GetVariableName(i),
            "label": spss.GetVariableLabel(i),
            "type": "numeric" if t == 0 else "string(%d)" % t,
            "format": spss.GetVariableFormat(i),
            "measure": spss.GetVariableMeasurementLevel(i),
        })
    cases = spss.GetCaseCount()
    if req.get("missing") and n_vars:
        _execute_pending()
        cur = spss.Cursor(list(range(n_vars)), accessType="r")
        try:
            counts = [0] * n_vars
            for row in cur.fetchall():
                for j, v in enumerate(row):
                    if v is None or (isinstance(v, str) and not v.strip()):
                        counts[j] += 1
        finally:
            cur.close()
        for j, c in enumerate(counts):
            variables[j]["missing"] = c
    return {"ok": True, "cases": cases, "variables": variables}


def _resolve(tokens):
    index = _var_index()
    names = list(index)
    lower = {n.lower(): n for n in names}
    out = []
    toks = [t for t in tokens if t]
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.upper() == "ALL":
            out.extend(names)
        elif i + 2 < len(toks) and toks[i + 1].upper() == "TO":
            a, b = lower.get(t.lower()), lower.get(toks[i + 2].lower())
            if a and b:
                ia, ib = index[a], index[b]
                out.extend(names[min(ia, ib):max(ia, ib) + 1])
            i += 2
        elif t.lower() in lower:
            out.append(lower[t.lower()])
        i += 1
    seen = set()
    return [n for n in out if not (n in seen or seen.add(n))]


def op_unique(req):
    names = _resolve(req.get("tokens") or [])
    if not names:
        return {"ok": True, "counts": {}}
    index = _var_index()
    _execute_pending()
    cur = spss.Cursor([index[n] for n in names], accessType="r")
    try:
        rows = cur.fetchall()
    finally:
        cur.close()
    counts = {}
    for j, n in enumerate(names):
        values = [r[j] for r in rows if r[j] is not None and not (isinstance(r[j], str) and not r[j].strip())]
        counts[n] = {"unique": len(set(values)), "nonmissing": len(values)}
    return {"ok": True, "counts": counts}


OPS = {"ping": lambda req: {"ok": True}, "submit": op_submit, "dictionary": op_dictionary, "unique": op_unique}

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
    except Exception:
        continue
    if req.get("op") == "exit":
        break
    try:
        result = OPS[req["op"]](req)
    except Exception as e:
        result = {"ok": False, "error": repr(e)[:1000], "trace": traceback.format_exc()[-2000:]}
    with open(req["resp"], "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    signal("__SA_DONE__ " + str(req["id"]))

try:
    spss.StopSPSS()
except Exception:
    pass
'''
