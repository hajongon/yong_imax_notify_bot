"""설정 모델 — Target(감시 선언)과 Settings(전역). targets.yaml + .env 에서 로드."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Optional

try:
    import yaml
except Exception:  # pyyaml 없으면 명확히 실패시킴(런타임 아님, 시작 시점)
    yaml = None

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None


@dataclass
class SeatRange:
    row_lo: str = "F"
    row_hi: str = "O"
    col_lo: int = 10
    col_hi: int = 35

    @staticmethod
    def from_dict(d: dict) -> "SeatRange":
        row = d.get("row", ["F", "O"])
        col = d.get("col", [10, 35])
        return SeatRange(str(row[0]).upper(), str(row[1]).upper(), int(col[0]), int(col[1]))

    def label(self) -> str:
        return f"{self.row_lo}~{self.row_hi}행·{self.col_lo}~{self.col_hi}번"


@dataclass
class Target:
    name: str
    mode: str                       # 'seat' | 'open'
    movie: str
    date: str                       # YYYYMMDD
    site_no: str = "0013"
    site_name: str = "용산아이파크몰"
    screen: str = ""                # 상영관 키워드(비면 전 상영관)
    start: str = ""                 # 시작시 접두(비면 전 시간)
    seat: SeatRange = field(default_factory=SeatRange)
    # 타이밍
    poll_sec: float = 1.0           # seat 폴링
    open_poll_sec: float = 30.0     # open 평상시 폴링
    fast_poll_sec: float = 1.0      # open 가속 폴링(오픈 예상 시각 근처)
    full_scan_sec: float = 45.0     # seat 안전 강제 스캔
    always_seatmap: bool = False
    renotify_sec: float = 300.0
    heartbeat_sec: float = 3600.0
    fail_alert_after: int = 20
    jitter: float = 0.2
    # open 전용
    expected_open: str = ""         # "YYYYMMDD HH:MM" (선택) → 그 근처 가속
    on_open: str = ""               # '' | 'seat' (오픈 후 좌석감시 자동 승계)

    def validate(self) -> None:
        if self.mode not in ("seat", "open"):
            raise ValueError(f"[{self.name}] mode 는 seat|open 이어야 함: {self.mode}")
        if not (self.date.isdigit() and len(self.date) == 8):
            raise ValueError(f"[{self.name}] date 는 YYYYMMDD: {self.date}")
        if not self.movie:
            raise ValueError(f"[{self.name}] movie 필수")


@dataclass
class Settings:
    tg_token: str
    tg_chat: str
    proxy: str
    targets: list[Target]


_TARGET_FIELDS = {f for f in Target.__dataclass_fields__ if f != "seat"}


def _build_target(raw: dict, defaults: dict) -> Target:
    merged = {**defaults, **raw}
    seat = SeatRange.from_dict(merged.get("seat", {})) if merged.get("seat") else SeatRange()
    kwargs = {k: v for k, v in merged.items() if k in _TARGET_FIELDS}
    if "date" in kwargs:
        kwargs["date"] = str(kwargs["date"])
    t = Target(seat=seat, **kwargs)
    t.validate()
    return t


def load_settings(targets_path: str, env_dir: Optional[str] = None) -> Settings:
    """targets.yaml + .env 로드. 비밀값(토큰/챗/프록시)은 .env(환경변수) 우선."""
    if load_dotenv:
        if env_dir:
            load_dotenv(os.path.join(env_dir, ".env"))
        load_dotenv()
    if yaml is None:
        raise RuntimeError("pyyaml 필요: pip install pyyaml")
    with open(targets_path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}

    defaults = doc.get("defaults", {}) or {}
    raw_targets = doc.get("targets", []) or []
    if not raw_targets:
        raise ValueError(f"{targets_path} 에 targets 가 비어있음")

    targets = [_build_target(rt, defaults) for rt in raw_targets]
    names = [t.name for t in targets]
    if len(names) != len(set(names)):
        raise ValueError(f"타겟 이름 중복: {names}")

    # 비밀값/프록시: 환경변수 우선, 없으면 defaults(yaml)의 값
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", str(defaults.get("tg_chat", "-1003872445177")))
    proxy = os.environ.get("CGV_PROXY", str(defaults.get("proxy", "")))
    return Settings(tg_token=tg_token, tg_chat=tg_chat, proxy=proxy, targets=targets)


def seat_target_from_open(t: Target) -> Target:
    """open 타겟 → 좌석 감시 승계용 seat 타겟(같은 영화/날짜/상영관/좌석범위)."""
    return replace(t, mode="seat", name=f"{t.name}->seat", on_open="", expected_open="")
