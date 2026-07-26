#!/usr/bin/env python3
"""
CGV 좌석 빈자리 24시간 감시 (Selenium 없이 순수 HTTP).

- Cloudflare 우회: curl_cffi 로 Chrome TLS 지문 위장
- 로그인 불필요 (좌석 조회 API는 비로그인 허용)
- 저부하 설계: 가벼운 스케줄 콜로 매초 폴링, 잔여수 변화 시에만 무거운 좌석맵 조회
- 타겟 범위(행/열) 안에 예매 가능 좌석이 생기면 텔레그램 알림
- 시간당 하트비트로 "살아있음" 신호, 오류 지속 시 경고

설정은 환경변수 또는 같은 폴더의 .env 로 오버라이드 가능. 기본값은 아래 CONFIG 참고.
실행:  python cgv_seat_watch.py          (한 번 점검하고 종료: --once)
"""
from __future__ import annotations

import argparse
import logging
import os
import random
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

from curl_cffi import requests

# ----- optional .env -----
try:
    from dotenv import load_dotenv
except Exception:  # dotenv 없어도 동작
    load_dotenv = None

KST = timezone(timedelta(hours=9), name="KST")
log = logging.getLogger("cgv-watch")


# =========================================================================
# 설정
# =========================================================================
def _env(key: str, default: str) -> str:
    v = os.environ.get(key)
    return v if v is not None and v != "" else default


class Config:
    def __init__(self):
        # --- 대상 ---
        self.movie_keyword = _env("CGV_MOVIE", "스파이더맨-브랜드 뉴 데이")
        self.site_no = _env("CGV_SITE_NO", "0013")          # 용산아이파크몰
        self.site_name = _env("CGV_SITE_NAME", "용산아이파크몰")
        self.scn_ymd = _env("CGV_DATE", "20260801")          # 8/1
        self.start_hhmm = _env("CGV_START", "16")            # 16시
        self.screen_kw = _env("CGV_SCREEN", "IMAX")          # IMAX관
        # --- 좌석 범위 ---
        self.row_lo = _env("CGV_ROW_LO", "F").upper()
        self.row_hi = _env("CGV_ROW_HI", "O").upper()
        self.col_lo = int(_env("CGV_COL_LO", "10"))
        self.col_hi = int(_env("CGV_COL_HI", "35"))
        # --- 폴링/알림 타이밍(초) ---
        self.poll_interval = float(_env("CGV_POLL_SEC", "1.0"))     # 스케줄 폴링 주기
        self.jitter = float(_env("CGV_JITTER", "0.2"))             # ±비율 지터
        self.full_scan_sec = float(_env("CGV_FULLSCAN_SEC", "45")) # 안전용 강제 좌석맵 스캔
        self.always_seatmap = _env("CGV_ALWAYS_SEATMAP", "0") in ("1", "true", "True")
        self.renotify_sec = float(_env("CGV_RENOTIFY_SEC", "300")) # 타겟 잔존 시 재알림 간격
        self.heartbeat_sec = float(_env("CGV_HEARTBEAT_SEC", "3600"))
        self.fail_alert_after = int(_env("CGV_FAIL_ALERT", "20"))  # 연속 실패 N회 시 경고
        # --- 텔레그램 ---
        self.tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.tg_chat = _env("TELEGRAM_CHAT_ID", "-1003872445177")

    def summary(self) -> str:
        return (f"{self.movie_keyword} / {self.site_name} / {self.scn_ymd} "
                f"{self.start_hhmm}시 {self.screen_kw} / "
                f"좌석 {self.row_lo}~{self.row_hi}·{self.col_lo}~{self.col_hi} / "
                f"폴링 {self.poll_interval}s")


# =========================================================================
# CGV API 클라이언트
# =========================================================================
BFF = "https://cgv.co.kr/api/v1/booking"
CO = "A420"
HEADERS = {"Accept": "application/json", "Referer": "https://cgv.co.kr/cnm/movieBook/movie"}
IMPERSONATE = "chrome"


class CgvError(Exception):
    pass


class CgvClient:
    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout
        self._new_session()

    def _new_session(self):
        self.s = requests.Session(impersonate=IMPERSONATE, timeout=self.timeout)

    def _get(self, path: str, params: dict, tries: int = 3) -> dict:
        last = None
        for i in range(tries):
            try:
                r = self.s.get(f"{BFF}/{path}", params=params, headers=HEADERS)
                if r.status_code == 200:
                    return r.json()
                if r.status_code in (403, 429, 503):
                    # Cloudflare/차단 의심 -> 지문 세션 갱신 후 백오프
                    log.warning("%s HTTP %s -> 세션 갱신+백오프", path, r.status_code)
                    self._new_session()
                    last = CgvError(f"{path} HTTP {r.status_code}")
                    time.sleep(1.5 * (i + 1))
                    continue
                last = CgvError(f"{path} HTTP {r.status_code}")
            except Exception as e:
                last = e
                time.sleep(1.0 * (i + 1))
        raise last or CgvError(f"{path} failed")

    def find_movie_no(self, keyword: str) -> tuple[str, str]:
        data = self._get("searchAtktTopPostrList",
                         {"coCd": CO, "movNm": "", "div": "", "attrCd": ""})["data"]
        for m in data:
            if keyword in m["movNm"]:
                return m["movNo"], m["movNm"]
        raise CgvError(f"영화 미발견: {keyword}")

    def schedule(self, mov_no: str, site_no: str, ymd: str) -> list[dict]:
        return self._get("searchSchByMov", {
            "coCd": CO, "siteNo": site_no, "scnYmd": ymd, "movNo": mov_no,
            "scnsNo": "", "scnSseq": "", "prodNo": "", "rtctlScopCd": "08", "custNo": "",
        })["data"]

    def find_showing(self, mov_no: str, site_no: str, ymd: str,
                     start_hhmm: str, screen_kw: str) -> dict:
        for s in self.schedule(mov_no, site_no, ymd):
            if screen_kw in s["scnsNm"] and s["scnsrtTm"].startswith(start_hhmm):
                return s
        raise CgvError(f"상영 미발견: {screen_kw} {start_hhmm}시 ({ymd})")

    def seat_map(self, site_no: str, ymd: str, scns_no: str, scn_sseq: str) -> list[dict]:
        d = self._get("searchIfSeatData", {
            "coCd": CO, "siteNo": site_no, "scnYmd": ymd,
            "scnsNo": scns_no, "scnSseq": scn_sseq, "rtctlScopCd": "08",
        })
        return d["data"]["items"][0]["seats"]


def target_available(seats: list[dict], c: Config) -> list[str]:
    """예매 가능(seatSaleYn='Y') & 타겟 행/열 범위 안의 좌석명 목록."""
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
        if c.row_lo <= row <= c.row_hi and c.col_lo <= col <= c.col_hi:
            out.append(f"{row}{col}")
    return sorted(out, key=lambda x: (x[0], int(x[1:])))


# =========================================================================
# 텔레그램 알림
# =========================================================================
def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")


def send_telegram(cfg: Config, text: str) -> bool:
    if not cfg.tg_token:
        log.warning("[tg] TELEGRAM_BOT_TOKEN 미설정 -> 콘솔 출력\n%s", text)
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{cfg.tg_token}/sendMessage",
            data={"chat_id": cfg.tg_chat, "text": text, "disable_web_page_preview": "true"},
            impersonate=IMPERSONATE, timeout=15,
        )
        ok = r.status_code == 200 and r.json().get("ok")
        if not ok:
            log.error("[tg] 발송 실패 HTTP %s %s", r.status_code, r.text[:200])
        return bool(ok)
    except Exception as e:
        log.error("[tg] 발송 예외: %s", e)
        return False


# =========================================================================
# 감시 루프
# =========================================================================
class Watcher:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.cli = CgvClient()
        self.stop = False
        # 상영 식별자(최초 1회 확정, 이후 스케줄에서 재확인)
        self.mov_no = None
        self.mov_nm = None
        self.scns_no = None
        self.scn_sseq = None
        self.show_dt: datetime | None = None   # 상영 시작 시각(KST)
        # 상태
        self.known_target: set[str] = set()
        self.last_free_cnt: int | None = None
        self.last_full_scan = 0.0
        self.last_target_notify = 0.0
        self.last_heartbeat = time.time()
        self.polls = 0
        self.fails = 0
        self.fail_alerted = False

    # --- 시그널 ---
    def handle_signal(self, signum, frame):
        log.info("시그널 %s 수신 -> 종료", signum)
        self.stop = True

    def resolve(self):
        self.mov_no, self.mov_nm = self.cli.find_movie_no(self.cfg.movie_keyword)
        sh = self.cli.find_showing(self.mov_no, self.cfg.site_no, self.cfg.scn_ymd,
                                   self.cfg.start_hhmm, self.cfg.screen_kw)
        self.scns_no, self.scn_sseq = sh["scnsNo"], sh["scnSseq"]
        # 상영 시작 시각(KST). scnsrtTm 은 "1600" 또는 심야 "2630"(=익일 02:30) 형태.
        ymd = self.cfg.scn_ymd
        tm = sh.get("scnsrtTm", "0000")
        base = datetime(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8]), tzinfo=KST)
        self.show_dt = base + timedelta(hours=int(tm[:2]), minutes=int(tm[2:]))
        return sh

    def showtime_passed(self) -> bool:
        return self.show_dt is not None and datetime.now(KST) >= self.show_dt

    def _sleep(self):
        j = self.cfg.poll_interval * self.cfg.jitter
        time.sleep(max(0.2, self.cfg.poll_interval + random.uniform(-j, j)))

    def scan_seats_and_notify(self, free_cnt: int, reason: str):
        seats = self.cli.seat_map(self.cfg.site_no, self.cfg.scn_ymd, self.scns_no, self.scn_sseq)
        self.last_full_scan = time.time()
        current = set(target_available(seats, self.cfg))
        new = current - self.known_target

        if new:
            names = sorted(current, key=lambda x: (x[0], int(x[1:])))
            self._notify_target(names, sorted(new, key=lambda x: (x[0], int(x[1:]))), free_cnt)
            self.last_target_notify = time.time()

        self.known_target = current
        log.info("[scan:%s] free=%s target=%d %s", reason, free_cnt, len(current), sorted(current))

    def maybe_renotify(self):
        """재알림: 좌석맵 스캔과 무관하게, 타겟이 남아있고 재알림 간격이 지났으면 캐시 상태로 재알림."""
        if not self.known_target:
            return
        if (time.time() - self.last_target_notify) < self.cfg.renotify_sec:
            return
        names = sorted(self.known_target, key=lambda x: (x[0], int(x[1:])))
        self._notify_target(names, [], self.last_free_cnt or 0, reminder=True)
        self.last_target_notify = time.time()

    def _notify_target(self, all_target: list[str], new: list[str], free_cnt: int, reminder=False):
        cfg = self.cfg
        head = "🔔 [재알림] 명당 좌석 여전히 있음" if reminder else "🎯 명당 좌석 발견!"
        lines = [
            head,
            f"영화: {self.mov_nm}",
            f"상영: {cfg.site_name} {cfg.scn_ymd} {cfg.start_hhmm}시 {cfg.screen_kw}",
            f"범위: {cfg.row_lo}~{cfg.row_hi}행 · {cfg.col_lo}~{cfg.col_hi}번",
        ]
        if new:
            lines.append(f"🆕 새로 열림: {', '.join(new)}")
        lines.append(f"현재 예매가능(범위내): {', '.join(all_target)}")
        lines.append(f"상영 전체 잔여: {free_cnt}석")
        lines.append(f"시각: {now_kst()}")
        lines.append("👉 https://cgv.co.kr/cnm/movieBook/movie")
        ok = send_telegram(cfg, "\n".join(lines))
        log.info("[notify] %s sent=%s new=%s", "reminder" if reminder else "target", ok, new)

    def poll_once(self):
        """스케줄 1회 폴링 + 조건부 좌석맵 스캔. 예외는 상위에서 처리."""
        sh = self.cli.find_showing(self.mov_no, self.cfg.site_no, self.cfg.scn_ymd,
                                   self.cfg.start_hhmm, self.cfg.screen_kw)
        # scnsNo/sseq가 바뀌었으면 갱신
        self.scns_no, self.scn_sseq = sh["scnsNo"], sh["scnSseq"]
        free_cnt = int(sh.get("frSeatCnt", "0") or 0)
        self.polls += 1

        changed = (self.last_free_cnt is None) or (free_cnt != self.last_free_cnt)
        due_full = self.cfg.always_seatmap or (time.time() - self.last_full_scan) >= self.cfg.full_scan_sec

        if free_cnt > 0 and (changed or due_full):
            reason = "change" if changed else "safety"
            self.scan_seats_and_notify(free_cnt, reason)
        elif free_cnt == 0:
            # 전 좌석 매진 -> 좌석맵 불필요, 타겟 상태 리셋
            if self.known_target:
                self.known_target = set()
        self.last_free_cnt = free_cnt

    def maybe_heartbeat(self):
        if (time.time() - self.last_heartbeat) >= self.cfg.heartbeat_sec:
            msg = (f"💓 감시 중 (정상)\n대상: {self.cfg.site_name} {self.cfg.scn_ymd} "
                   f"{self.cfg.start_hhmm}시 {self.cfg.screen_kw}\n"
                   f"누적 폴링: {self.polls}회 · 현재 잔여: {self.last_free_cnt}석 · "
                   f"범위내 가능: {len(self.known_target)}석\n{now_kst()}")
            send_telegram(self.cfg, msg)
            self.last_heartbeat = time.time()
            log.info("[heartbeat] sent polls=%d", self.polls)

    def run(self, once=False):
        cfg = self.cfg
        # 시작 시 상영 확정(일시적 오류 대비 재시도)
        sh = None
        for attempt in range(6):
            try:
                sh = self.resolve()
                break
            except Exception as e:
                log.warning("[resolve] 실패(%d/6): %s", attempt + 1, e)
                if once or attempt == 5:
                    raise
                time.sleep(min(20, 3 * (attempt + 1)))
        log.info("확정: %s / scnsNo=%s sseq=%s 잔여=%s/%s / 상영시각=%s",
                 self.mov_nm, self.scns_no, self.scn_sseq, sh.get("frSeatCnt"), sh.get("stcnt"),
                 self.show_dt.strftime("%m-%d %H:%M") if self.show_dt else "?")
        if not once:
            send_telegram(cfg, f"✅ CGV 빈자리 감시 시작\n대상: {cfg.summary()}\n"
                               f"현재 잔여: {sh.get('frSeatCnt')}/{sh.get('stcnt')}석\n{now_kst()}")
        # 최초 1회 즉시 스캔
        self.poll_once()
        if once:
            hits = sorted(self.known_target, key=lambda x: (x[0], int(x[1:])))
            print(f"[once] 잔여={self.last_free_cnt} 범위내가능={len(hits)} {hits}")
            return

        while not self.stop:
            if self.showtime_passed():
                send_telegram(cfg, f"⏰ 상영 시작 시각 도달 → 감시 자동 종료\n"
                                   f"대상: {cfg.site_name} {cfg.scn_ymd} {cfg.start_hhmm}시 {cfg.screen_kw}\n"
                                   f"누적 폴링 {self.polls}회\n{now_kst()}")
                log.info("상영 시각 경과 → 정상 종료")
                return
            try:
                self.poll_once()
                if self.fails:
                    self.fails = 0
                    self.fail_alerted = False
            except Exception as e:
                self.fails += 1
                log.warning("[poll:%d] 실패(연속 %d): %s", self.polls, self.fails, e)
                if self.fails >= cfg.fail_alert_after and not self.fail_alerted:
                    send_telegram(cfg, f"⚠️ CGV 감시 오류 지속 (연속 {self.fails}회)\n"
                                       f"최근: {type(e).__name__}: {e}\n{now_kst()}")
                    self.fail_alerted = True
                time.sleep(min(30, 2 * self.fails))  # 오류 백오프
            self.maybe_renotify()
            self.maybe_heartbeat()
            self._sleep()

        send_telegram(cfg, f"🛑 CGV 빈자리 감시 종료\n누적 폴링 {self.polls}회\n{now_kst()}")
        log.info("종료. polls=%d", self.polls)


# =========================================================================
def main() -> int:
    if load_dotenv:
        load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
        load_dotenv()  # cwd .env 도 시도
    ap = argparse.ArgumentParser(description="CGV 좌석 빈자리 감시 (API)")
    ap.add_argument("--once", action="store_true", help="한 번만 점검하고 종료")
    ap.add_argument("--verbose", action="store_true", help="디버그 로그")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S",
    )
    cfg = Config()
    log.info("설정: %s", cfg.summary())
    w = Watcher(cfg)
    signal.signal(signal.SIGINT, w.handle_signal)
    signal.signal(signal.SIGTERM, w.handle_signal)
    try:
        w.run(once=args.once)
        return 0
    except CgvError as e:
        log.error("치명적: %s", e)
        send_telegram(cfg, f"❌ CGV 감시 시작 실패: {e}\n{now_kst()}")
        return 2
    except Exception as e:
        log.exception("예상치 못한 오류: %s", e)
        return 9


if __name__ == "__main__":
    sys.exit(main())
