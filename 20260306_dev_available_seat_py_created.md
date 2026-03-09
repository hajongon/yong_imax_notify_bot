# 2026-03-06 available-seat.py 신규 생성 로그

## 작업 목적
- 신규 파일 `available-seat.py` 생성
- 좌석 후보를 단건(`P44`)이 아니라 범위로 확장:
  - 행: `F ~ O`
  - 열: `16 ~ 30`

## 생성/변경 파일
- 신규: `available-seat.py`
- 방식: `test.py`를 기반으로 복사 후 좌석 탐지 로직만 범위형으로 변경

## 핵심 변경 사항
1. 좌석 타겟 상수 변경
- 삭제: `TARGET_SEAT = "P44"`
- 추가:
  - `TARGET_ROW_START = "F"`
  - `TARGET_ROW_END = "O"`
  - `TARGET_COL_MIN = 16`
  - `TARGET_COL_MAX = 30`

2. 범위 좌석 생성/탐지 함수 추가
- `_build_target_seat_set()`
  - `F16`부터 `O30`까지 전체 후보 set 생성
- `find_available_target_seats()`
  - `button[data-seatlocno]` 중 `disabled` 없는 좌석만 확인
  - 좌석명 추출 후 후보 범위에 포함되는 좌석을 수집
  - `행,열` 기준 정렬하여 반환

3. 메인 루프 좌석 판정 로직 변경
- 기존:
  - `is_seat_available(TARGET_SEAT)`
- 변경:
  - `available_seats = find_available_target_seats()`
  - `available_seats`가 1개 이상이면 텔레그램 알림(`notify(..., seat_names=available_seats)`) 후 종료
  - 없으면 다음 시간대(13:20/16:30)로 반복

## 현재 동작 요약
1. 검색/예매/용산아이파크몰 선택 흐름 유지
2. 시간대 `13:20`, `16:30` 순환
3. 후보 범위 `F16~O30` 중 예매 가능 좌석이 1개라도 발견되면 알림
