"""워처 — 감시 루프(무중단 설계). BaseWatcher(스레드) + SeatWatcher + OpenWatcher.

무중단 원칙:
- 각 타겟은 독립 스레드. 한 타겟의 오류가 다른 타겟을 죽이지 않음.
- 루프의 모든 반복은 예외를 통째로 잡고 백오프 후 계속. 절대 예외로 스레드가 죽지 않음.
- 최후 방어: _loop 밖으로 예외가 튀어도 run()이 다시 재개.
- 종료는 오직 (a) 공용 stop_event(시그널) 또는 (b) 타겟의 자연 완료(상영시각 경과/오픈 승계 종료).
"""
from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime, timedelta

from .client import CgvClient, CgvError
from .config import Settings, Target, seat_target_from_open
from .model import (KST, available_seat_names, fmt_hhmm, match_showings,
                    now_kst_str, parse_show_dt, sort_seats)

log = logging.getLogger("cgv.watch")


class BaseWatcher(threading.Thread):
    def __init__(self, target: Target, settings: Settings, notifier, stop_event: threading.Event):
        super().__init__(name=target.name, daemon=True)
        self.t = target
        self.settings = settings
        self.notifier = notifier
        self.stop_event = stop_event
        self.cli = CgvClient(proxy=settings.proxy)   # 스레드마다 개별 클라이언트
        self.polls = 0
        self.fails = 0
        self.fail_alerted = False
        self.last_heartbeat = time.time()
        self.mov_no = None
        self.mov_nm = None
        self.done = False

    # --- 공용 유틸 ---
    def stopped(self) -> bool:
        return self.stop_event.is_set()

    def sleep(self, base: float):
        j = base * self.t.jitter
        end = time.time() + max(0.2, base + random.uniform(-j, j))
        while time.time() < end and not self.stopped():
            time.sleep(min(0.5, max(0.0, end - time.time())))

    def notify(self, text: str):
        self.notifier.send(text)

    def heartbeat(self, extra: str):
        if time.time() - self.last_heartbeat >= self.t.heartbeat_sec:
            self.notify(f"💓 [{self.t.name}] 감시 중\n{extra}\n{now_kst_str()}")
            self.last_heartbeat = time.time()
            log.info("[%s] heartbeat polls=%d", self.t.name, self.polls)

    def on_success(self):
        if self.fails:
            self.fails = 0
            self.fail_alerted = False

    def on_fail(self, e: Exception):
        self.fails += 1
        log.warning("[%s] 실패(연속 %d): %s", self.t.name, self.fails, e)
        if self.fails >= self.t.fail_alert_after and not self.fail_alerted:
            self.notify(f"⚠️ [{self.t.name}] 오류 지속(연속 {self.fails}회)\n"
                        f"{type(e).__name__}: {e}\n{now_kst_str()}")
            self.fail_alerted = True
        end = time.time() + min(30, 2 * self.fails)
        while time.time() < end and not self.stopped():
            time.sleep(0.5)

    def resolve_movie(self):
        self.mov_no, self.mov_nm = self.cli.find_movie_no(self.t.movie)

    def resolve_movie_retry(self):
        while not self.stopped() and self.mov_no is None:
            try:
                self.resolve_movie()
            except Exception as e:
                self.on_fail(e)

    def run(self):
        while not self.stopped():
            try:
                self._loop()
                break  # 정상 완료
            except Exception as e:
                log.exception("[%s] 루프 밖 예외, 5s 후 재개: %s", self.t.name, e)
                end = time.time() + 5
                while time.time() < end and not self.stopped():
                    time.sleep(0.5)
        self.done = True
        log.info("[%s] 감시 종료(polls=%d)", self.t.name, self.polls)

    def _loop(self):
        raise NotImplementedError

    def check_once(self) -> str:
        raise NotImplementedError

    def target_label(self) -> str:
        t = self.t
        s = f"{t.site_name} {t.date}"
        if t.start:
            s += f" {t.start}시"
        if t.screen:
            s += f" {t.screen}"
        if t.mode == "seat":
            s += f" · {t.seat.label()}"
        return s


class SeatWatcher(BaseWatcher):
    def _loop(self):
        if self.mov_no is None:
            self.resolve_movie_retry()
        if self.stopped():
            return
        self.monitor_seats(startup_notify=True)

    def monitor_seats(self, startup_notify: bool):
        t = self.t
        self.scns_no = None
        self.scn_sseq = None
        self.known: set[str] = set()
        self.last_free = None
        self.last_full = 0.0
        self.last_target_notify = 0.0

        # 최초 상영 확정(찾을 때까지 재시도)
        sh = None
        while not self.stopped() and sh is None:
            try:
                sh = self._find_showing()
            except Exception as e:
                self.on_fail(e)
        if sh is None:
            return
        show_dt = parse_show_dt(t.date, sh["scnsrtTm"])
        if startup_notify:
            self.notify(f"✅ [{t.name}] 좌석 감시 시작\n{self.target_label()}\n"
                        f"현재 잔여 {sh.get('frSeatCnt')}/{sh.get('stcnt')}석\n{now_kst_str()}")

        while not self.stopped():
            if datetime.now(KST) >= show_dt:
                self.notify(f"⏰ [{t.name}] 상영 시각 도달 → 좌석 감시 종료\n누적 폴링 {self.polls}\n{now_kst_str()}")
                return
            try:
                self._poll_once()
                self.on_success()
            except Exception as e:
                self.on_fail(e)
            self._maybe_renotify()
            self.heartbeat(f"{self.target_label()}\n잔여 {self.last_free}석 · 범위내 {len(self.known)}석 · 폴링 {self.polls}")
            self.sleep(t.poll_sec)

    def _find_showing(self) -> dict:
        sch = self.cli.schedule(self.mov_no, self.t.site_no, self.t.date)
        matches = match_showings(sch, self.t.screen, self.t.start)
        if not matches:
            raise CgvError(f"상영 미발견: {self.t.screen} {self.t.start} ({self.t.date})")
        return matches[0]

    def _poll_once(self):
        sh = self._find_showing()
        self.scns_no, self.scn_sseq = sh["scnsNo"], sh["scnSseq"]
        free = int(sh.get("frSeatCnt", "0") or 0)
        self.polls += 1
        changed = (self.last_free is None) or (free != self.last_free)
        due_full = self.t.always_seatmap or (time.time() - self.last_full) >= self.t.full_scan_sec
        if free > 0 and (changed or due_full):
            self._scan(free, "change" if changed else "safety")
        elif free == 0:
            self.known = set()
        self.last_free = free

    def _scan(self, free: int, reason: str):
        seats = self.cli.seat_map(self.t.site_no, self.t.date, self.scns_no, self.scn_sseq)
        self.last_full = time.time()
        current = set(available_seat_names(seats, self.t.seat))
        new = current - self.known
        if new:
            self._notify_seats(sort_seats(current), sort_seats(new), free)
            self.last_target_notify = time.time()
        self.known = current
        log.info("[%s] scan:%s free=%s target=%d %s", self.t.name, reason, free, len(current), sorted(current))

    def _maybe_renotify(self):
        if not self.known:
            return
        if time.time() - self.last_target_notify < self.t.renotify_sec:
            return
        self._notify_seats(sort_seats(self.known), [], self.last_free or 0, reminder=True)
        self.last_target_notify = time.time()

    def _notify_seats(self, all_t, new, free, reminder=False):
        t = self.t
        head = "🔔 [재알림] 명당 좌석 있음" if reminder else "🎯 명당 좌석 발견!"
        lines = [f"{head}  [{t.name}]", f"영화: {self.mov_nm}", f"상영: {self.target_label()}"]
        if new:
            lines.append(f"🆕 새로: {', '.join(new)}")
        lines.append(f"예매가능(범위내): {', '.join(all_t)}")
        lines.append(f"전체 잔여: {free}석")
        lines.append(now_kst_str())
        lines.append("👉 https://cgv.co.kr/cnm/movieBook/movie")
        self.notify("\n".join(lines))
        log.info("[%s] notify %s new=%s", t.name, "reminder" if reminder else "target", new)

    def check_once(self) -> str:
        self.resolve_movie()
        sh = self._find_showing()
        free = int(sh.get("frSeatCnt", "0") or 0)
        seats = self.cli.seat_map(self.t.site_no, self.t.date, sh["scnsNo"], sh["scnSseq"]) if free > 0 else []
        hits = available_seat_names(seats, self.t.seat)
        return f"[{self.t.name}] seat | 잔여 {free} · 범위내 {len(hits)} {hits}"


class OpenWatcher(BaseWatcher):
    def _loop(self):
        if self.mov_no is None:
            self.resolve_movie_retry()
        if self.stopped():
            return
        t = self.t
        self.notify(f"✅ [{t.name}] 예매 오픈 감시 시작\n"
                    f"대상: {t.site_name} {t.date} {t.screen or '전체'} ({self.mov_nm})\n"
                    f"{'오픈예상 ' + t.expected_open if t.expected_open else '오픈시각 미상 → 상시 감시'}\n{now_kst_str()}")
        while not self.stopped():
            try:
                if self._check_open():
                    return  # 오픈 감지 + 처리 완료(승계 포함)
                self.on_success()
            except Exception as e:
                self.on_fail(e)
            self.heartbeat(f"오픈 대기: {t.site_name} {t.date} {t.screen or ''} · 폴링 {self.polls}")
            self.sleep(self._interval())

    def _check_open(self) -> bool:
        t = self.t
        self.polls += 1
        dates = self.cli.bookable_dates(self.mov_no, t.site_no)
        if t.date not in dates:
            return False
        showings = []
        if t.screen or t.start:
            sch = self.cli.schedule(self.mov_no, t.site_no, t.date)
            showings = match_showings(sch, t.screen, t.start)
            if not showings:
                log.info("[%s] 날짜 %s 열림, %s 회차 아직 없음 → 계속 대기", t.name, t.date, t.screen)
                return False
        self._notify_open(showings)
        if t.on_open == "seat":
            self._handoff_seat()
        return True

    def _notify_open(self, showings):
        t = self.t
        lines = [f"🚨 예매 오픈!  [{t.name}]", f"영화: {self.mov_nm}", f"극장/날짜: {t.site_name} {t.date}"]
        if t.screen:
            lines.append(f"상영관: {t.screen}")
        if showings:
            times = ", ".join(
                f"{s.get('scnsNm','')} {fmt_hhmm(s.get('scnsrtTm',''))}(잔여 {s.get('frSeatCnt')})"
                for s in showings[:8])
            lines.append(f"열린 회차: {times}")
        lines.append(now_kst_str())
        lines.append("👉 https://cgv.co.kr/cnm/movieBook/movie")
        self.notify("\n".join(lines))
        log.info("[%s] OPEN 감지 알림 발송", t.name)

    def _handoff_seat(self):
        seat_t = seat_target_from_open(self.t)
        log.info("[%s] 오픈 → 좌석 감시 승계(%s)", self.t.name, seat_t.name)
        self.notify(f"↪️ [{self.t.name}] 오픈 확인 → 좌석 감시로 자동 전환({seat_t.seat.label()})")
        sw = SeatWatcher(seat_t, self.settings, self.notifier, self.stop_event)
        sw.mov_no, sw.mov_nm = self.mov_no, self.mov_nm
        sw.monitor_seats(startup_notify=False)  # 같은 스레드에서 이어 실행

    def _interval(self) -> float:
        t = self.t
        if t.expected_open:
            try:
                T = datetime.strptime(t.expected_open, "%Y%m%d %H:%M").replace(tzinfo=KST)
                now = datetime.now(KST)
                if T - timedelta(minutes=2) <= now <= T + timedelta(minutes=10):
                    return t.fast_poll_sec
            except Exception:
                pass
        return t.open_poll_sec

    def check_once(self) -> str:
        self.resolve_movie()
        dates = self.cli.bookable_dates(self.mov_no, self.t.site_no)
        opened = self.t.date in dates
        detail = ""
        if opened and (self.t.screen or self.t.start):
            sch = self.cli.schedule(self.mov_no, self.t.site_no, self.t.date)
            n = len(match_showings(sch, self.t.screen, self.t.start))
            detail = f" · {self.t.screen or ''}{self.t.start or ''} 회차 {n}개"
        return (f"[{self.t.name}] open | {self.t.date} "
                f"{'열림 ✅' if opened else '아직 ⏳'} (예매가능일 {len(dates)}개){detail}")


def make_watcher(t: Target, settings: Settings, notifier, stop_event: threading.Event) -> BaseWatcher:
    if t.mode == "seat":
        return SeatWatcher(t, settings, notifier, stop_event)
    if t.mode == "open":
        return OpenWatcher(t, settings, notifier, stop_event)
    raise ValueError(f"알 수 없는 mode: {t.mode}")
