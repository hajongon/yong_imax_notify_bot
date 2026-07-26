"""Notifier — 알림 전송(텔레그램). 전송만 담당(메시지 포맷은 워처가 구성).

교체 지점: 다른 채널(Slack/Discord/푸시)이 필요하면 같은 send(text) 인터페이스로 구현체 추가.
텔레그램은 데이터센터 IP에서 직접 도달하므로 프록시를 타지 않음.
"""
from __future__ import annotations

import logging

from curl_cffi import requests

log = logging.getLogger("cgv.notify")


class Notifier:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id

    def send(self, text: str) -> bool:
        if not self.token:
            log.warning("[tg] 토큰 미설정 -> 콘솔 출력\n%s", text)
            return False
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                data={"chat_id": self.chat_id, "text": text, "disable_web_page_preview": "true"},
                impersonate="chrome", timeout=15,
            )
            ok = r.status_code == 200 and r.json().get("ok")
            if not ok:
                log.error("[tg] 발송 실패 HTTP %s %s", r.status_code, r.text[:200])
            return bool(ok)
        except Exception as e:
            log.error("[tg] 발송 예외: %s", e)
            return False
