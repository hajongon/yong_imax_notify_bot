# 2026-03-06 수정 이력 (단계별)

## 1단계: 타겟 극장명 정정 (용산 -> 용산아이파크몰)
- 목적: 기존 하드코딩된 `용산` 기준을 `용산아이파크몰` 기준으로 통일.
- 변경 파일:
  - `main.py`
  - `test.py`
- 주요 변경:
  - `TARGET_THEATER = "용산아이파크몰"`로 변경
  - argparse 설명 문구의 극장명 변경
  - 알림 제목/본문에서 고정 문자열 `용산`을 제거하고 `TARGET_THEATER` 기반으로 동적 생성

## 2단계: 좌석 감시 로직 1차 추가 (test.py)
- 목적: 요청하신 신규 로직(극장선택/날짜/시간/좌석검사) 반영.
- 변경 파일:
  - `test.py`
- 추가 상수:
  - `TARGET_DAY_OF_WEEK = "토"`
  - `TARGET_DAY_NUMBER = "21"`
  - `WATCH_START_TIMES = ["13:20", "16:30"]`
  - `TARGET_SEAT = "P44"`
  - `POLL_INTERVAL_SEC = 1.0`
- 추가 함수:
  - `click_theater_select_button()`
  - `select_target_date(day_of_week, day_number)`
  - `click_time_slot(start_time)`
  - `_extract_seat_name(seat_button)`
  - `is_seat_available(seat_name)`
- 알림 포맷 변경:
  - 영화관 / 날짜 / 시간대 / 발견 좌석 / 발견 시각 포함

## 3단계: 실행 흐름 보정 (검색부터 용산아이파크몰 확인까지 유지)
- 사용자 피드백:
  - "검색부터 시작해서 용산아이파크몰 찾는 과정까지는 그대로 유지" 요청.
- 반영 내용 (`test.py`):
  - `open_page -> search_movie -> click_search_button -> click_reserve_button` 유지
  - 이후 모달 루프에서 `has_yongsan()`으로 `용산아이파크몰` 확인
  - 확인 이후에만 `극장선택 -> 토21 선택 -> 13:20/16:30 순환 -> P44 검사` 진입

## 4단계: has_yongsan 분기 보정 (찾자마자 닫기 문제 수정)
- 사용자 피드백:
  - "has yongsan의 경우 modal을 바로 닫아 원하는 로직 수행이 안 됨"
- 반영 내용 (`test.py`):
  - 신규 함수 `select_target_theater_in_modal()` 추가
  - `has_yongsan()`이 `True`일 때
    - 즉시 닫지 않고 모달 내 `용산아이파크몰` 버튼을 먼저 클릭
    - 자동 닫힘 대기 (`wait_modal_close()`)
    - 자동으로 안 닫히면 `close_modal()` 폴백 후 진행

## 현재 상태 요약
- `main.py`: 극장명/알림문구만 `용산아이파크몰` 기준으로 정리됨.
- `test.py`: 
  1. 검색/예매 진입
  2. 모달에서 `용산아이파크몰` 확인 및 선택
  3. 극장선택 클릭
  4. `토 21` 선택
  5. `13:20`/`16:30` 번갈아 선택
  6. `P44` 좌석 가능 시 텔레그램 알림

## 미반영 항목 (다음 단계)
- 좌석 범위 감시(`F~O`, `16~30`)에서 "1석 이상 가능 시 알림" 로직은 아직 미적용.
- 현재 버전은 요청하신 중간 단계대로 `P44` 단건 체크에 맞춰져 있음.
