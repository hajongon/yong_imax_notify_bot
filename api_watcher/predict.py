#!/usr/bin/env python3
"""예매 오픈 시점 예측기 — scout.py가 쌓은 관측 이력에서 규칙을 추론한다.

핵심 논리
---------
CGV는 "예매가능 날짜 목록"의 **최대일(지평선)** 을 주기적으로 늘린다.
목표 날짜 D의 예매가 열리는 시점 = 지평선이 D 이상으로 늘어나는 시점.

따라서:
  1) 관측 이력에서 '지평선 증가 이벤트'를 추출한다  (언제, 얼마나 늘었나)
  2) 이벤트들로부터 주기(며칠마다)와 증가폭(며칠씩), 발생 시각(하루 중 몇 시)을 추정한다
  3) 목표 날짜까지 남은 증가량을 계산해 오픈 시점을 예측한다

관측이 부족할 때(이벤트 0~1개)는 **구조 모델**로 대체 예측한다:
CGV 편성주는 수요일→화요일이며, 지평선은 편성주 경계(화요일)에서 끝나는 것이 관측됐다.
→ 지평선이 D를 포함하려면 D가 속한 편성주까지 확장돼야 한다.

사용:
  python predict.py                       # 기본 목표(오디세이 8/22 용산) 예측
  python predict.py --movie 오디세이 --site 0013 --date 20260822
  python predict.py --report              # 관측 이력 요약만
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "data", "horizon.jsonl")
WD = "월화수목금토일"


# ---------------------------------------------------------------- 데이터 로드
def load(path: str = HIST) -> dict[tuple[str, str], list[dict]]:
    """(영화, 극장) → 시간순 관측 리스트."""
    series: dict[tuple[str, str], list[dict]] = defaultdict(list)
    if not os.path.exists(path):
        return series
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("error") or not r.get("max"):
                continue
            r["_t"] = datetime.fromisoformat(r["ts"])
            series[(r["movie"], r["site"])].append(r)
    for k in series:
        series[k].sort(key=lambda x: x["_t"])
    return series


def ymd2date(s: str) -> date:
    return datetime.strptime(s, "%Y%m%d").date()


def fmt(d: date) -> str:
    return f"{d.strftime('%m/%d')}({WD[d.weekday()]})"


# ------------------------------------------------------- 지평선 증가 이벤트 추출
def extract_events(obs: list[dict]) -> list[dict]:
    """지평선이 커진 순간들. 실제 발생은 (이전관측, 현재관측] 사이 어딘가.

    ⚠️ 지평선은 단조증가가 아니다 — 실측(2026-08-04 여의도 오디세이)에서 8/8↔8/7 왕복이
    관측됐다(스케줄이 실시간 편집되는 중으로 추정). 원시값으로 상승만 세면 같은 확장이
    여러 번 계수되어 주기 추정이 오염된다. 따라서 **누적최대(running max)** 기준으로
    이벤트를 뽑고, 하락(flicker)은 별도로 세어 데이터 품질 지표로만 쓴다.
    """
    events = []
    run_max = obs[0]["max"]
    prev_t = obs[0]["_t"]
    for prev, cur in zip(obs, obs[1:]):
        if cur["max"] > run_max:
            events.append({
                "after": cur["_t"],          # 이 시각엔 이미 늘어나 있었음
                "before": prev_t,            # 이 시각엔 아직 아니었음
                "from": run_max,
                "to": cur["max"],
                "gain_days": (ymd2date(cur["max"]) - ymd2date(run_max)).days,
                "uncertainty_sec": (cur["_t"] - prev_t).total_seconds(),
            })
            run_max = cur["max"]
            prev_t = cur["_t"]
        elif cur["max"] >= run_max:
            prev_t = cur["_t"]
    return events


def count_flicker(obs: list[dict]) -> int:
    """지평선이 뒤로 후퇴한 횟수(비단조성 지표)."""
    return sum(1 for a, b in zip(obs, obs[1:]) if b["max"] < a["max"])


def static_hours(obs: list[dict], events: list[dict]) -> float:
    """마지막 지평선 증가 이후 경과 시간(증가가 없으면 전체 관측 기간)."""
    last = events[-1]["after"] if events else obs[0]["_t"]
    return (obs[-1]["_t"] - last).total_seconds() / 3600


def infer(events: list[dict]) -> dict:
    """이벤트에서 주기·증가폭·발생시각 추정."""
    out = {"n_events": len(events), "cadence_days": None, "gain_days": None,
           "hour_hint": None, "confidence": "none"}
    if not events:
        return out
    gains = [e["gain_days"] for e in events]
    out["gain_days"] = statistics.median(gains)
    # 발생 시각: 불확실 구간의 중앙값 시각
    mids = [e["before"] + (e["after"] - e["before"]) / 2 for e in events]
    out["hour_hint"] = statistics.median([m.hour + m.minute / 60 for m in mids])
    if len(events) >= 2:
        gaps = [(b["after"] - a["after"]).total_seconds() / 86400
                for a, b in zip(events, events[1:])]
        out["cadence_days"] = statistics.median(gaps)
        out["confidence"] = "high" if len(events) >= 3 else "medium"
    else:
        out["confidence"] = "low"
    return out


# --------------------------------------------------------------- 구조 모델(사전지식)
def week_end_tue(d: date) -> date:
    """d가 속한 편성주(수→화)의 마지막 날(화요일)."""
    # 화=1 (월0). 수(2)부터 다음 화(1)까지가 한 주.
    days_ahead = (1 - d.weekday()) % 7
    return d + timedelta(days=days_ahead)


def next_wednesdays(today: date, n: int = 4) -> list[date]:
    """다가오는 수요일들(편성주 시작일)."""
    d = today + timedelta(days=((2 - today.weekday()) % 7) or 7)
    return [d + timedelta(days=7 * i) for i in range(n)]


def structural_prediction(current_max: date, target: date, today: date,
                          static_h: float = 0.0) -> dict:
    """관측이 부족할 때의 대체 예측 — 편성주(수→화) 구조 기반.

    관측된 구조적 사실:
      - 지평선은 편성주 경계(화요일)에서 끝난다 (스파이더맨 8/11(화), 오디세이 8/18(화))
      - 한국 영화 개봉일은 수요일 = 편성주 시작

    가설A (매일 +1일 롤링): 지평선이 매일 하루씩 → 목표까지 need일
    가설B (주간 +7일, 수요일 점프): 매주 수요일에 지평선이 한 편성주씩 확장
      - B1: 이번 수요일부터 확장 (현재 리드 유지)
      - B2: 한 주 늦게 확장 (개봉 후 리드가 한 주 줄어드는 경우)
    """
    need = (target - current_max).days
    a = today + timedelta(days=need)
    weds = next_wednesdays(today, 5)
    # 각 수요일마다 +7일씩 확장된다고 볼 때 목표를 덮는 첫 수요일
    b1 = next((w for i, w in enumerate(weds, start=1)
               if current_max + timedelta(days=7 * i) >= target), None)
    b2 = None
    if b1 is not None:
        idx = weds.index(b1)
        b2 = weds[idx + 1] if idx + 1 < len(weds) else b1 + timedelta(days=7)
    # 관측으로 가설A(매일 롤링) 반증: 하루 넘게 지평선이 그대로면 매일 오르는 게 아니다.
    daily_refuted = static_h >= 30
    return {"daily_hypothesis": a, "weekly_hypothesis": b1,
            "weekly_delayed": b2, "need_days": need,
            "upcoming_wednesdays": weds[:3],
            "daily_refuted": daily_refuted, "static_hours": round(static_h, 1)}


# ------------------------------------------------------------------- 예측
def predict(series, movie: str, site: str, target_ymd: str, now: datetime) -> dict:
    key = None
    for (m, s) in series:
        if movie in m and s == site:
            key = (m, s)
            break
    if key is None:
        return {"error": f"관측 이력 없음: {movie}@{site}"}

    obs = series[key]
    cur_max = ymd2date(max(o["max"] for o in obs))   # 누적최대(flicker 무시)
    target = ymd2date(target_ymd)
    today = now.date()
    events = extract_events(obs)
    inf = infer(events)
    stat_h = static_hours(obs, events)

    res = {
        "movie": key[0], "site": site, "target": target_ymd,
        "observations": len(obs),
        "span_hours": (obs[-1]["_t"] - obs[0]["_t"]).total_seconds() / 3600,
        "current_max": cur_max.strftime("%Y%m%d"),
        "already_open": target <= cur_max,
        "flicker": count_flicker(obs), "static_hours": round(stat_h, 1),
        "events": events, "inference": inf,
    }
    if res["already_open"]:
        res["verdict"] = "이미 예매 가능"
        return res

    need = (target - cur_max).days
    res["need_days"] = need

    # 관측 기반 예측(이벤트 2개 이상)
    if inf["cadence_days"] and inf["gain_days"]:
        n = need / inf["gain_days"]
        import math
        n_ev = math.ceil(n)
        last = events[-1]["after"]
        eta = last + timedelta(days=inf["cadence_days"] * n_ev)
        res["predicted_open"] = eta.isoformat()
        res["method"] = (f"관측기반: {inf['cadence_days']:.2f}일마다 +{inf['gain_days']:.0f}일 "
                         f"→ {n_ev}회 필요")
        res["confidence"] = inf["confidence"]
    else:
        st = structural_prediction(cur_max, target, today, stat_h)
        res["structural"] = {
            k: (v.isoformat() if isinstance(v, date) else
                [x.isoformat() for x in v] if isinstance(v, list) else v)
            for k, v in st.items()
        }
        res["predicted_open"] = None
        res["method"] = "구조모델(관측 부족)"
        res["confidence"] = "low"
    return res


# ------------------------------------------------------------------- 출력
def report(series, now: datetime):
    print(f"■ 관측 이력 요약  (현재 {now.strftime('%Y-%m-%d %H:%M')} KST)\n")
    print(f"{'영화@극장':34} {'관측':>4} {'기간h':>6} {'현재지평선':>12} {'증가':>4} {'정체h':>6} {'후퇴':>4}")
    print("-" * 82)
    for (m, s), obs in sorted(series.items()):
        ev = extract_events(obs)
        span = (obs[-1]["_t"] - obs[0]["_t"]).total_seconds() / 3600
        cm = max(o["max"] for o in obs)
        mx = ymd2date(cm)
        print(f"{(m[:22]+'@'+s):34} {len(obs):>4} {span:>6.1f} "
              f"{cm+' '+fmt(mx)[-3:]:>12} {len(ev):>4} "
              f"{static_hours(obs, ev):>6.1f} {count_flicker(obs):>4}")
        for e in ev:
            print(f"      └ {e['before'].strftime('%m/%d %H:%M')}~{e['after'].strftime('%H:%M')} "
                  f"{e['from']}→{e['to']} (+{e['gain_days']}일, ±{e['uncertainty_sec']/60:.0f}분)")
    print("-" * 82)


def show(res: dict, now: datetime):
    if "error" in res:
        print(f"❌ {res['error']}")
        return
    print(f"\n■ 예측: {res['movie']} @{res['site']} — {res['target']} 예매 오픈\n")
    print(f"  관측 {res['observations']}회 / {res['span_hours']:.1f}시간, "
          f"지평선 증가 이벤트 {res['inference']['n_events']}회")
    print(f"  현재 지평선: {res['current_max']} {fmt(ymd2date(res['current_max']))}")
    if res.get("already_open"):
        print("  ✅ 이미 예매 가능")
        return
    print(f"  목표까지 필요한 확장: +{res['need_days']}일\n")
    if res.get("predicted_open"):
        eta = datetime.fromisoformat(res["predicted_open"])
        print(f"  🎯 예상 오픈: {eta.strftime('%Y-%m-%d(%a) %H:%M')} "
              f"(신뢰도 {res['confidence']})")
        print(f"     방법: {res['method']}")
    else:
        st = res["structural"]
        a = date.fromisoformat(st["daily_hypothesis"])
        b1 = date.fromisoformat(st["weekly_hypothesis"]) if st.get("weekly_hypothesis") else None
        b2 = date.fromisoformat(st["weekly_delayed"]) if st.get("weekly_delayed") else None
        refuted = st.get("daily_refuted")
        print("  ⏳ 관측된 지평선 증가 없음 → 구조모델 예측 (신뢰도 low)")
        mark = "  ❌반증됨" if refuted else ""
        print(f"     가설A 매일 +1일 롤링        : {fmt(a)} 경{mark}")
        if refuted:
            print(f"        └ 지평선이 {st['static_hours']:.0f}시간째 그대로 → 매일 오르는 방식이 아님")
        if b1:
            print(f"     가설B1 배치 점프(다음 편성주): {fmt(b1)} 경  ← 수요일")
        if b2:
            print(f"     가설B2 배치 점프(한 주 뒤)  : {fmt(b2)} 경")
        cands = [d for d in ([] if refuted else [a]) + [b1, b2] if d]
        if cands:
            print(f"     → 유력 구간: {fmt(min(cands))} ~ {fmt(max(cands))}")
        if res.get("flicker"):
            print(f"     ⚠️ 지평선 후퇴 {res['flicker']}회 관측(비단조) — 누적최대 기준으로 계산함")


def main() -> int:
    ap = argparse.ArgumentParser(description="예매 오픈 시점 예측")
    ap.add_argument("--movie", default="오디세이")
    ap.add_argument("--site", default="0013")
    ap.add_argument("--date", default="20260822")
    ap.add_argument("--report", action="store_true", help="관측 이력 요약만 출력")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--hist", default=HIST)
    a = ap.parse_args()

    now = datetime.now(KST)
    series = load(a.hist)
    if not series:
        print(f"관측 이력 없음: {a.hist}\nscout.py가 먼저 돌아야 합니다.")
        return 1
    report(series, now)
    if a.report:
        return 0
    res = predict(series, a.movie, a.site, a.date, now)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, default=str, indent=2))
    else:
        show(res, now)
    return 0


if __name__ == "__main__":
    sys.exit(main())
