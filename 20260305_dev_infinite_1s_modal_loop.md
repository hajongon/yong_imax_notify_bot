# 2026-03-05 Prompt6 개발 로그

## 요청
- 모달 체크를 1초에 1번씩 수행.
- 10회 제한 제거(무한 반복).

## 반영 내용
- `main.py`
  - `import time` 추가.
  - CLI에서 `--max-tries` 제거.
  - `for attempt in range(...)` 제거.
  - `while True` 무한 루프로 변경.
  - 각 사이클에서 모달 닫힘 후 `time.sleep(1.0)` 적용.
  - 예외 발생 후 복구 시도 뒤에도 `time.sleep(1.0)` 적용.
  - 수동 중단 대응으로 `KeyboardInterrupt` 처리 추가(return code 130).

- `README.md`
  - `--max-tries` 관련 실행 예시/옵션 제거.
  - "1초 간격 무제한 반복" 동작을 명시.
