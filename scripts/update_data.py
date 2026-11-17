#!/usr/bin/env python3
"""광명시 업소 수·인구 자료를 공공데이터포털 API에서 받아 data.json으로 저장합니다.
인증키는 환경변수 DATA_GO_KR_KEY(GitHub Secrets)로만 받으며 어디에도 기록하지 않습니다.
검증에 실패하면 data.json을 바꾸지 않고 오류로 끝납니다."""
import json, os, re, sys, time, datetime, urllib.parse, urllib.request

BASE = os.environ.get("API_BASE", "https://apis.data.go.kr")
RAW_KEY = os.environ.get("DATA_GO_KR_KEY", "").strip()
OUT = os.environ.get("OUT_FILE", "data.json")
DN = ["광명1동","광명2동","광명3동","광명4동","광명5동","광명6동","광명7동","소하1동","소하2동","일직동",
      "철산1동","철산2동","철산3동","철산4동","하안1동","하안2동","하안3동","하안4동","학온동"]
CATS = ["교육","음식","과학기술","수리개인","소매","시설관리임대","부동산","보건의료","숙박","예술스포츠"]

def die(msg):
    print("오류:", msg.replace(RAW_KEY, "***") if RAW_KEY else msg, file=sys.stderr)
    sys.exit(1)

if not RAW_KEY:
    die("DATA_GO_KR_KEY 가 비어 있습니다(저장소 Settings > Secrets 에 등록 필요).")
KEY = urllib.parse.quote(urllib.parse.unquote(RAW_KEY), safe="")

def get(path, params):
    q = "&".join(f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in params.items())
    url = f"{BASE}{path}?serviceKey={KEY}&{q}"
    last = None
    for i in range(3):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                txt = r.read().decode("utf-8", "replace")
            if txt.lstrip().startswith("<"):
                m = re.search(r"<(?:returnAuthMsg|errMsg|resultMsg|cmmMsgHeader)[^>]*>([^<]*)<", txt)
                raise RuntimeError("XML 응답(" + (m.group(1) if m else txt[:120]) + ")")
            return json.loads(txt)
        except Exception as e:  # 재시도
            last = str(e)
            time.sleep(3 * (i + 1))
    die(f"{path} 호출 실패: {last}")

def norm(s):  # 가운뎃점·공백 등 제거
    return re.sub(r"[^가-힣0-9]", "", s or "")

def items_of(j):
    """응답에서 dict 목록을 찾아 돌려줍니다(형식이 조금 달라도 동작)."""
    best = []
    def walk(o):
        nonlocal best
        if isinstance(o, list) and o and all(isinstance(x, dict) for x in o):
            if len(o) > len(best): best = o
        elif isinstance(o, dict):
            for v in o.values(): walk(v)
    walk(j)
    return best

def pick(d, cands):
    for c in cands:
        if c in d and d[c] not in (None, ""): return d[c]
    return None

def to_int(v):
    return int(float(str(v).replace(",", "")))

# ---------- 업소 수 ----------
def fetch_stores():
    rows, page, stdr = [], 1, None
    while True:
        j = get("/B553077/api/open/sdsc2/storeListInDong",
                {"pageNo": page, "numOfRows": 1000, "divId": "signguCd", "key": "41210", "type": "json"})
        hdr = j.get("header", {}) if isinstance(j, dict) else {}
        body = j.get("body", {}) if isinstance(j, dict) else {}
        code = str(hdr.get("resultCode", "00"))
        if code not in ("00", "0", "INFO-000"):
            die(f"상가정보 API 오류 코드 {code}: {hdr.get('resultMsg')}")
        stdr = stdr or hdr.get("stdrYm") or body.get("stdrYm")
        its = items_of(body) if body else items_of(j)
        rows += its
        total = to_int(body.get("totalCount", 0) or 0)
        if not its or page * 1000 >= total: break
        page += 1
    if not rows: die("상가정보가 비어 있습니다.")
    sample = rows[0]
    if "adongNm" not in sample or "indsLclsNm" not in sample:
        die("상가정보 응답 항목 이름이 예상과 다릅니다: " + ",".join(sorted(sample.keys())[:40]))
    ci = {c: i for i, c in enumerate(CATS)}
    RD = {n: [0] * 10 for n in DN}
    skipped = 0
    for r in rows:
        dn = norm(r.get("adongNm")); cat = norm(r.get("indsLclsNm"))
        if dn in RD and cat in ci: RD[dn][ci[cat]] += 1
        else: skipped += 1
    print(f"상가 {len(rows)}건 수집, 제외 {skipped}건, 기준월 {stdr}")
    if not re.fullmatch(r"\d{6}", str(stdr or "")): die(f"상가정보 기준월을 알 수 없습니다({stdr}).")
    return RD, str(stdr)

# ---------- 인구 ----------
def find_month():
    t = datetime.date.today().replace(day=1)
    for back in range(0, 5):
        y, m = t.year, t.month - back
        while m <= 0: m += 12; y -= 1
        yield f"{y}{m:02d}"

def dong_rows(path, ym):
    j = get(path, {"admmCd": "4121000000", "stdgYm": ym, "lv": 3, "regSeCd": 1,
                   "type": "JSON", "numOfRows": 100, "pageNo": 1})
    out = {}
    for r in items_of(j):
        nm = norm(str(pick(r, ["dongNm", "admmNm", "dongName"]) or ""))
        for d in DN:
            if nm.endswith(d): out[d] = r
    return out

def fetch_pop():
    for ym in find_month():
        a = dong_rows("/1741000/admmPpltnHhStus/selectAdmmPpltnHhStus", ym)
        if len(a) < 19: continue
        b = dong_rows("/1741000/admmSexdAgePpltn/selectAdmmSexdAgePpltn", ym)
        if len(b) < 19: continue
        POP = {}
        for d in DN:
            r = a[d]
            tot = pick(r, ["totNmprCnt", "totNmpr"]); hh = pick(r, ["hhCnt"])
            ml = pick(r, ["maleNmprCnt", "maleNmpr"]); fm = pick(r, ["femlNmprCnt", "femlNmpr"])
            if None in (tot, hh, ml, fm):
                die("인구 응답 항목 이름이 예상과 다릅니다: " + ",".join(sorted(r.keys())[:40]))
            bands = [0] * 11
            found = False
            for k, v in b[d].items():
                m = re.fullmatch(r"(?:male|feml)(\d+)AgeNmprCnt", k)
                if m:
                    found = True
                    bands[min(int(m.group(1)) // 10, 10)] += to_int(v)
            if not found:
                die("연령 응답 항목 이름이 예상과 다릅니다: " + ",".join(sorted(b[d].keys())[:60]))
            POP[d] = [to_int(tot), to_int(hh), to_int(ml), to_int(fm)] + bands
        print("인구 기준월", ym)
        return POP, ym
    die("최근 5개월 안에서 인구 자료를 찾지 못했습니다.")

# ---------- 검증·저장 ----------
def validate(RD, POP, old):
    for d in DN:
        p = POP[d]
        if p[2] + p[3] != p[0]: die(f"{d}: 남녀 합계가 총인구와 다릅니다.")
        if sum(p[4:]) != p[0]: die(f"{d}: 연령 합계가 총인구와 다릅니다.")
        if min(p) < 0 or min(RD[d]) < 0: die(f"{d}: 음수 값")
    st = sum(map(sum, RD.values())); pt = sum(POP[d][0] for d in DN)
    if st < 3000 or pt < 100000: die(f"합계가 비정상적으로 작습니다(업소 {st}, 인구 {pt}).")
    if old:
        os_ = sum(map(sum, old["RD"].values())); op = sum(v[0] for v in old["POP"].values())
        if not 0.7 <= st / os_ <= 1.3: die(f"업소 합계가 직전 값과 30% 이상 차이({os_}→{st}). 수동 확인 필요.")
        if not 0.9 <= pt / op <= 1.1: die(f"인구 합계가 직전 값과 10% 이상 차이({op}→{pt}). 수동 확인 필요.")
    print(f"검증 통과: 업소 {st:,}곳, 인구 {pt:,}명")

def main():
    old = None
    if os.path.exists(OUT):
        try: old = json.load(open(OUT, encoding="utf-8"))
        except Exception: old = None
    RD, stdr = fetch_stores()
    POP, ym = fetch_pop()
    validate(RD, POP, old)
    new = {"RD": RD, "POP": POP, "stdr": stdr, "popYm": ym}
    if old and all(old.get(k) == new[k] for k in new):
        print("변경 없음: data.json 그대로 둡니다."); return
    new["generatedAt"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(new, f, ensure_ascii=False, separators=(",", ":"))
    print("data.json 저장 완료")

if __name__ == "__main__":
    main()
