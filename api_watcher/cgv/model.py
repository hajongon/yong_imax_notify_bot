"""도메인 로직 — 상영/좌석 파싱과 타겟 매칭. 순수 함수(네트워크 없음, 테스트 쉬움)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .config import SeatRange

KST = timezone(timedelta(hours=9), name="KST")


def now_kst_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")


def parse_show_dt(ymd: str, hhmm: str) -> datetime:
    """상영 시작 시각(KST). hhmm 은 '1600' 또는 심야 '2630'(=익일 02:30)."""
    base = datetime(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8]), tzinfo=KST)
    return base + timedelta(hours=int(hhmm[:2]), minutes=int(hhmm[2:]))


def match_showings(schedule: list[dict], screen_kw: str = "", start_hhmm: str = "") -> list[dict]:
    """스케줄에서 상영관 키워드/시작시 접두로 필터. 둘 다 비면 전체."""
    out = []
    for s in schedule:
        if screen_kw and screen_kw not in (s.get("scnsNm") or ""):
            continue
        if start_hhmm and not (s.get("scnsrtTm") or "").startswith(start_hhmm):
            continue
        out.append(s)
    return out


def available_seat_names(seats: list[dict], rng: SeatRange) -> list[str]:
    """예매가능(seatSaleYn='Y') & 타겟 행/열 범위 안 좌석명."""
    out = []
    for s in seats:
        if s.get("seatSaleYn") != "Y":
            continue
        row = (s.get("seatRowNm") or "").strip().upper()
        if len(row) != 1 or not ("A" <= row <= "Z"):
            continue
        try:
            col = int(s["seatNo"])
        except (ValueError, KeyError, TypeError):
            continue
        if rng.row_lo <= row <= rng.row_hi and rng.col_lo <= col <= rng.col_hi:
            out.append(f"{row}{col}")
    return sorted(out, key=lambda x: (x[0], int(x[1:])))


def filter_adjacent(names: list[str], min_size: int) -> list[str]:
    """같은 행에서 좌석번호가 연속(붙은 자리)인 그룹 크기가 min_size 이상인 좌석만 남김.

    min_size <= 1 이면 전체 통과. 통로를 사이에 둔 연속 번호는 구분하지 못함(근사).
    """
    if min_size <= 1:
        return sort_seats(names)
    by_row: dict[str, list[int]] = {}
    for n in names:
        by_row.setdefault(n[0], []).append(int(n[1:]))
    out: list[str] = []
    for row, cols in by_row.items():
        cols.sort()
        run: list[int] = [cols[0]]
        for c in cols[1:]:
            if c == run[-1] + 1:
                run.append(c)
            else:
                if len(run) >= min_size:
                    out += [f"{row}{k}" for k in run]
                run = [c]
        if len(run) >= min_size:
            out += [f"{row}{k}" for k in run]
    return sort_seats(out)


def sort_seats(names) -> list[str]:
    return sorted(names, key=lambda x: (x[0], int(x[1:])))


def fmt_hhmm(hhmm: str) -> str:
    return f"{hhmm[:2]}:{hhmm[2:]}" if len(hhmm) == 4 else hhmm
