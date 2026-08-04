#!/usr/bin/env python3
"""지평선 정찰기 — 예매 "벽(wall)"의 이동을 관측·기록한다.

## 왜 벽인가 (2026-08-04 전수조사로 확립된 모델)

전국 174개 극장의 오디세이 예매가능일을 전수 조회한 결과, **정규 회차가
2026-08-18(화)을 넘는 극장은 0곳**이었다. 개별 극장의 더 짧은 지평선(8/9=69곳,
8/11=39곳 등)은 "예매창이 안 열린 것"이 아니라 **그 극장이 그날까지만 편성한 것**이다.

즉 구조는 이렇다:

    전국 공통 절대 벽(현재 20260818)  ← 아무도 이걸 넘지 못함
      └ 그 아래에서 극장별로 자기 편성만큼만 연다

따라서 목표(오디세이 8/22 @용산)는 **"용산의 지평선이 늘어나는가"가 아니라
"벽이 8/25로 밀리는가"** 의 문제다. 용산은 이미 벽에 붙어 있으므로(8/18),
벽이 밀리면 8/22는 함께 열린다.

## 무엇을 관측하나

벽에 붙어 있는 극장이 가장 민감한 센서다(현재 27곳). 여러 곳을 함께 보면
벽이 움직이는 순간을 놓칠 확률이 줄고, 배치 시각 통계가 빨리 쌓인다.
극장을 3곳만 보던 이전 버전은 관측 창 안에서 실제 일어난 배치들을 놓쳤다.

출력: data/horizon.jsonl — 한 줄 = 한 시점의 한 (영화, 극장) 관측
      data/wall.jsonl    — 한 줄 = 한 시점의 전국 벽 요약
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HERE, ".env"))
except Exception:
    pass

from cgv.client import CgvClient

KST = timezone(timedelta(hours=9))
OUT = os.path.join(HERE, "data", "horizon.jsonl")
WALL_OUT = os.path.join(HERE, "data", "wall.jsonl")

# 목표
TARGET_MOVIE = os.environ.get("SCOUT_MOVIE", "오디세이")
TARGET_SITE = os.environ.get("SCOUT_SITE", "0013")      # 용산아이파크몰
TARGET_DATE = os.environ.get("SCOUT_DATE", "20260822")

# 벽에 붙어 있던 극장들(2026-08-04 전수조사 기준 27곳 중 지역 분산해 선정)
# + 벽 아래에서 확장이 관측된 극장 일부(배치 주기 학습용)
WALL_SITES = [
    ("0013", "용산아이파크몰"),   # 목표
    ("0074", "왕십리"),
    ("0040", "압구정"),
    ("0059", "영등포타임스퀘어"),
    ("0199", "천호"),
    ("0366", "고덕강일"),
    ("0054", "일산"),
    ("0181", "판교"),
    ("0257", "광교"),
    ("0298", "김포한강"),
    ("0113", "의정부"),
    ("0106", "동탄"),
    ("0345", "대구"),
    ("0089", "센텀시티"),
    ("0005", "서면"),
    ("0128", "울산삼산"),
    ("0286", "대전가수원"),
]
# 벽 아래 극장(확장 이벤트가 자주 관측됨 → 배치 시각 학습에 유리)
BELOW_WALL_SITES = [
    ("0112", "여의도"),
    ("0252", "동대문"),
    ("0063", "대학로"),
    ("0229", "건대입구"),
    ("0001", "강변"),
]
# 비교군 영화(같은 벽을 공유하는지 확인)
COMPARE = [("오케이 마담2", "0013"), ("스파이더맨-브랜드 뉴 데이", "0013")]

SLEEP = 0.25   # 429 회피 (전수조사 중 0.1s에서 429 발생 이력)


def _append(path: str, rows: list[dict]) -> None:
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> int:
    cli = CgvClient(proxy=os.environ.get("CGV_PROXY", ""))
    ts = datetime.now(KST).isoformat()
    try:
        movies = cli.movie_list()
    except Exception as e:
        print(f"movie_list 실패: {type(e).__name__}: {e}")
        return 1

    def mov_no(name: str):
        return next((m["movNo"] for m in movies if name in m["movNm"]), None)

    rows: list[dict] = []
    target_no = mov_no(TARGET_MOVIE)

    # 1) 목표 영화 × 여러 극장 (벽 관측)
    if target_no:
        for site, nm in WALL_SITES + BELOW_WALL_SITES:
            row = {"ts": ts, "movie": TARGET_MOVIE, "movNo": target_no,
                   "site": site, "siteNm": nm}
            try:
                dates = sorted(cli.bookable_dates(target_no, site))
                row.update({"n": len(dates),
                            "min": dates[0] if dates else None,
                            "max": dates[-1] if dates else None,
                            "dates": dates})
            except Exception as e:
                row["error"] = f"{type(e).__name__}: {e}"
            rows.append(row)
            time.sleep(SLEEP)
    else:
        rows.append({"ts": ts, "movie": TARGET_MOVIE, "site": TARGET_SITE,
                     "error": "movie not found"})

    # 2) 비교군
    for name, site in COMPARE:
        no = mov_no(name)
        row = {"ts": ts, "movie": name, "movNo": no, "site": site}
        try:
            if not no:
                row["error"] = "movie not found"
            else:
                dates = sorted(cli.bookable_dates(no, site))
                row.update({"n": len(dates),
                            "min": dates[0] if dates else None,
                            "max": dates[-1] if dates else None,
                            "dates": dates})
        except Exception as e:
            row["error"] = f"{type(e).__name__}: {e}"
        rows.append(row)
        time.sleep(SLEEP)

    _append(OUT, rows)

    # 3) 벽 요약: 이번 관측에서 확인된 전국 최대일 + 목표일 개방 여부
    good = [r for r in rows if r.get("max")]
    wall = max((r["max"] for r in good), default=None)
    at_wall = [r["site"] for r in good if r.get("max") == wall]
    target_row = next((r for r in rows
                       if r.get("site") == TARGET_SITE and r.get("movie") == TARGET_MOVIE), None)
    target_open = bool(target_row and TARGET_DATE in (target_row.get("dates") or []))
    wall_row = {"ts": ts, "wall": wall, "at_wall_count": len(at_wall),
                "at_wall_sites": at_wall, "sites_polled": len(good),
                "target": TARGET_DATE, "target_open": target_open,
                "target_site_max": (target_row or {}).get("max")}
    _append(WALL_OUT, [wall_row])

    errs = [r for r in rows if r.get("error")]
    print(f"[{ts[:19]}] 벽={wall} (붙은 극장 {len(at_wall)}/{len(good)}) "
          f"| {TARGET_MOVIE}@{TARGET_SITE} max={(target_row or {}).get('max')} "
          f"| {TARGET_DATE} 열림={'예 ✅' if target_open else '아니오'}"
          + (f" | 오류 {len(errs)}건" if errs else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
