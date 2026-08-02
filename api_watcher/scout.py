#!/usr/bin/env python3
"""지평선 정찰기 — 예매가능 날짜 목록을 주기적으로 기록(관측 원시데이터).

왜 필요한가: "8/22 예매가 언제 열릴지"를 예측하려면 '지평선(예매가능 최대일)이
언제 얼마나 늘어나는지'의 이력이 있어야 한다. 과거 이력은 API로 조회할 수 없으므로
지금부터 관측해 쌓는 수밖에 없다. 관측 공백은 영구 손실이다.

본 감시 서비스(cgv-watch)와 완전히 독립적으로 동작한다. 이 스크립트가 실패해도
감시에는 영향이 없다(별도 프로세스, 별도 타이머).

출력: data/horizon.jsonl — 한 줄 = 한 시점의 한 (영화, 극장) 관측
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

# 정찰 대상: 목표 + "이미 롤링 중인" 비교군.
#
# 핵심 아이디어: 목표(오디세이 8/22)의 지평선이 움직이기를 기다릴 필요가 없다.
# 스파이더맨은 이미 '오늘+9'로 롤링 중이므로, 그 영화에서 **증가 주기와 시각**을
# 먼저 학습한 뒤 오디세이에 적용할 수 있다. 관측 대상이 많을수록 학습이 빨라진다.
# (2026-08-02 실측: 용산 기준 스파이더맨 max=오늘+9, 오디세이 max=8/18 고정(개봉전 배치))
WATCH = [
    ("오디세이", "0013"),                   # 목표 (용산)
    ("오디세이", "0074"),                   # 목표 영화, 다른 대형관 (왕십리) — 동조 여부
    ("오디세이", "0112"),                   # 소형관 (여의도) — 지평선 짧음, 확장 관측 용이
    ("스파이더맨-브랜드 뉴 데이", "0013"),    # ★롤링 중(+9) — 주기/시각 학습용 (용산)
    ("스파이더맨-브랜드 뉴 데이", "0074"),    # ★롤링 중 (왕십리)
    ("호프", "0013"),                      # 롤링 중(+5) 비교군
    ("명탐정 코난", "0013"),                # 개봉예정작 비교군
    ("사랑의 하츄핑", "0013"),               # 비교군
]


def main() -> int:
    cli = CgvClient(proxy=os.environ.get("CGV_PROXY", ""))
    ts = datetime.now(KST).isoformat()
    rows = []
    try:
        movies = cli.movie_list()
    except Exception as e:
        print(f"movie_list 실패: {type(e).__name__}: {e}")
        return 1

    for name, site in WATCH:
        row = {"ts": ts, "movie": name, "site": site}
        try:
            mov_no = next((m["movNo"] for m in movies if name in m["movNm"]), None)
            if not mov_no:
                row["error"] = "movie not found"
            else:
                dates = sorted(cli.bookable_dates(mov_no, site))
                row.update({
                    "movNo": mov_no,
                    "n": len(dates),
                    "min": dates[0] if dates else None,
                    "max": dates[-1] if dates else None,
                    "dates": dates,
                })
        except Exception as e:
            row["error"] = f"{type(e).__name__}: {e}"
        rows.append(row)
        time.sleep(0.3)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    for r in rows:
        if "error" in r:
            print("  {}@{}: ERROR {}".format(r["movie"], r["site"], r["error"]))
        else:
            print("  {}@{}: {}~{} ({}일)".format(
                r["movie"], r["site"], r["min"], r["max"], r["n"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
