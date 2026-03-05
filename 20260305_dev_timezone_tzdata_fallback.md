# 2026-03-05 Prompt9 개발 로그

## 발생 이슈
- `notify()` 실행 시 `ZoneInfoNotFoundError: No time zone found with key Asia/Seoul`
- 원인: Windows Python 환경에서 `tzdata` 미탑재.

## 수정 사항
1. `test.py`
   - import 수정:
     - `from datetime import datetime, timedelta, timezone`
     - `from zoneinfo import ZoneInfo, ZoneInfoNotFoundError`
   - `_build_notify_text()` 수정:
     - `Asia/Seoul` 조회 실패 시 KST(UTC+9) 폴백 사용

2. `requirements.txt`
   - `tzdata>=2024.1` 추가

3. `README.md`
   - Windows zoneinfo/tzdata 이슈와 폴백 동작 설명 추가

## 기대 효과
- `Asia/Seoul` DB가 없는 환경에서도 notify가 중단되지 않고 메시지 생성/전송 가능.
