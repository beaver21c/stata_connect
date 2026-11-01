"""SPSS 내장 Python에서 실행되는 엔진 스크립트(문자열). 서버가 파일로 써서 서브프로세스로 띄움.

동작
- ``spss.StartSPSS()``로 화면 없는 SPSS를 1회 기동 → 표준입력에서 JSON 요청을 한 줄씩 받아 처리
- 응답은 요청이 지정한 파일에 JSON으로 기록하고, 표준출력에는 완료 표지 한 줄만 씀
  (SPSS가 표준출력에 내보내는 잡음과 섞이지 않게 하기 위함)
- 요청 종류: ping / submit(문법 실행 + OMS 텍스트 출력 수집) / dictionary(변수 정보·결측 수) /
  unique(변수별 고유값 수) / exit

근거: spss.StartSPSS·Submit·GetLastErrorLevel·StopSPSS, SPSS 폴더의 Python3 사용 방식은
제3자 구현(spss-mcp-extended 2.0.0) 소스로 확인 [2차 확인]. StartSPSS는 세션이 이미 있으면 동작하지 않음
(IBM 문서 검색 요약 [2차 확인]). 변수 정보 함수(GetVariableName 등)와 Cursor는 IBM 문서 원문 미열람 [미확인].

버전 호환(SPSS 22~): 22·23은 Python 2.7, 24~26은 2.7·3.4, 27부터 3.x만 동봉 [2차 확인: IBM 문서 검색 요약]
→ 이 스크립트는 Python 2.7·3.4에서도 돌도록 작성(f-문자열·open(encoding=)·reconfigure 필수 사용 금지,
표준입력은 readline 반복, 응답은 ASCII JSON 바이트로 기록). tests/test_spss_legacy.py가 금지 문법을 검사하고,
CI(spss-legacy-python)가 python:2.7·3.4 이미지에서 실제로 실행함.
"""

ENGINE_SCRIPT = r'''# -*- coding: utf-8 -*-
import sys, os, json, traceback, locale

SPSS_HOME = sys.argv[1]
PY2 = sys.version_info[0] == 2
try:
    TEXT = unicode  # noqa: F821 (Python 2)
except NameError:
    TEXT = str
_ENC = locale.getpreferredencoding() or "utf-8"

os.environ["PATH"] = SPSS_HOME + os.pathsep + os.environ.get("PATH", "")
# 실행 중인 Python과 같은 계열의 spss 모듈 폴더만 추가(2.7에 3.x 모듈이 섞이지 않게)
_dirs = ("Python", "Python27") if PY2 else ("Python3",)
for _d in _dirs:
    _p = os.path.join(SPSS_HOME, _d, "Lib", "site-packages")
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

try:
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass
_out = os.fdopen(os.dup(1), "wb", 0)


def signal(text):
    if not isinstance(text, bytes):
        text = text.encode("ascii", "backslashreplace")
    _out.write(text + b"\n")
    _out.flush()


def _text(v):
    # SPSS가 돌려준 문자열을 유니코드로(2.7 코드페이지 모드의 바이트 문자열 대비)
    if v is None or isinstance(v, TEXT):
        return v
    if isinstance(v, bytes):
        for enc in ("utf-8", _ENC):
            try:
                return v.decode(enc)
            except Exception:
                pass
        return v.decode("latin-1")
    return v


def _err(e):
    try:
        return _text(TEXT(e))
    except Exception:
        return repr(e)


def _blank(v):
    return v is None or (isinstance(v, (bytes, TEXT)) and not v.strip())


try:
    import spss
    spss.StartSPSS()  # 이미 세션이 있으면 동작 없음
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
        error = _err(e)
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


def _names():
    return [_text(spss.GetVariableName(i)) for i in range(spss.GetVariableCount())]


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
            "name": _text(spss.GetVariableName(i)),
            "label": _text(spss.GetVariableLabel(i)),
            "type": "numeric" if t == 0 else "string(%d)" % t,
            "format": _text(spss.GetVariableFormat(i)),
            "measure": _text(spss.GetVariableMeasurementLevel(i)),
        })
    cases = spss.GetCaseCount()
    if req.get("missing") and n_vars:
        _execute_pending()
        cur = spss.Cursor(list(range(n_vars)), accessType="r")
        try:
            counts = [0] * n_vars
            for row in cur.fetchall():
                for j, v in enumerate(row):
                    if _blank(v):
                        counts[j] += 1
        finally:
            cur.close()
        for j, c in enumerate(counts):
            variables[j]["missing"] = c
    return {"ok": True, "cases": cases, "variables": variables}


def _resolve(tokens):
    names = _names()
    index = dict((n, i) for i, n in enumerate(names))
    lower = dict((n.lower(), n) for n in names)
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
    return [n for n in out if not (n in seen or seen.add(n))], index


def op_unique(req):
    names, index = _resolve(req.get("tokens") or [])
    if not names:
        return {"ok": True, "counts": {}}
    _execute_pending()
    cur = spss.Cursor([index[n] for n in names], accessType="r")
    try:
        rows = cur.fetchall()
    finally:
        cur.close()
    counts = {}
    for j, n in enumerate(names):
        values = [r[j] for r in rows if not _blank(r[j])]
        counts[n] = {"unique": len(set(values)), "nonmissing": len(values)}
    return {"ok": True, "counts": counts}


def _write(path, result):
    data = json.dumps(result, ensure_ascii=True)
    if not isinstance(data, bytes):
        data = data.encode("ascii")
    f = open(path, "wb")
    try:
        f.write(data)
    finally:
        f.close()


OPS = {"ping": lambda req: {"ok": True}, "submit": op_submit, "dictionary": op_dictionary, "unique": op_unique}

while True:
    line = sys.stdin.readline()  # 2.7의 `for line in sys.stdin`은 미리 읽기 버퍼 때문에 요청이 늦게 도착함
    if not line:
        break
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
    try:
        _write(req["resp"], result)
    except Exception as e:
        _write(req["resp"], {"ok": False, "error": "response write failed: " + repr(e)[:500]})
    signal("__SA_DONE__ " + str(req["id"]))

try:
    spss.StopSPSS()
except Exception:
    pass
'''
