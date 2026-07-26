#!/usr/bin/env python3
"""CGV 알리미 진입점 — targets.yaml 의 타겟들을 각각 스레드로 무중단 감시.

실행:
  python run.py                 # 상시 감시
  python run.py --once          # 각 타겟 1회 점검 후 종료(테스트용)
  python run.py --targets other.yaml
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from cgv.config import load_settings
from cgv.model import now_kst_str
from cgv.notify import Notifier
from cgv.watch import make_watcher

log = logging.getLogger("cgv.run")


def main() -> int:
    ap = argparse.ArgumentParser(description="CGV 예매/좌석 알리미 (다중 타겟)")
    ap.add_argument("--targets", default=os.path.join(HERE, "targets.yaml"), help="targets.yaml 경로")
    ap.add_argument("--once", action="store_true", help="각 타겟 1회 점검 후 종료")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S",
    )

    try:
        settings = load_settings(args.targets, env_dir=HERE)
    except Exception as e:
        log.error("설정 로드 실패: %s", e)
        return 2

    notifier = Notifier(settings.tg_token, settings.tg_chat)
    stop_event = threading.Event()
    watchers = [make_watcher(t, settings, notifier, stop_event) for t in settings.targets]
    log.info("타겟 %d개: %s", len(watchers), ", ".join(w.t.name for w in watchers))

    # --once: 스레드 없이 각 타겟 1회 점검
    if args.once:
        for w in watchers:
            try:
                print(w.check_once())
            except Exception as e:
                print(f"[{w.t.name}] 점검 실패: {type(e).__name__}: {e}")
        return 0

    def _handle(signum, frame):
        log.info("시그널 %s 수신 → 종료 요청", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)

    lines = [f"✅ CGV 알리미 시작 · 타겟 {len(watchers)}개"]
    for w in watchers:
        lines.append(f"• [{w.t.name}] {w.t.mode} · {w.target_label()}")
    lines.append(now_kst_str())
    notifier.send("\n".join(lines))

    for w in watchers:
        w.start()

    # 무중단: 시그널 전까지 프로세스 유지. 개별 타겟이 완료돼도 프로세스는 살려둠.
    announced_idle = False
    while not stop_event.is_set():
        time.sleep(1)
        if not announced_idle and all(w.done for w in watchers):
            log.info("모든 타겟 완료 → 유휴 대기(프로세스 유지). 새 타겟은 재시작 시 반영.")
            announced_idle = True

    for w in watchers:
        w.join(timeout=10)
    notifier.send(f"🛑 CGV 알리미 종료\n{now_kst_str()}")
    log.info("종료 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
