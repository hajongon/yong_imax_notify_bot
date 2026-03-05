# 2026-03-05 Main 반영 + 로그 파일명 정리

## 요청 반영
1. `main.py`에도 텔레그램 notify 확장 동일 반영
2. 개발 로그 파일명을 핵심 주제 기반으로 변경

## 작업 내용
- `main.py`
  - `test.py` 기준 구현을 이식
  - 타겟 극장 상수는 `TARGET_THEATER = "용산"`으로 조정
  - argparse 설명을 용산 기준으로 수정
  - 텔레그램/시간대 폴백/notify(driver, extra) 구조 동일 적용

- `README.md`
  - `main.py`도 텔레그램 알림 반영 상태로 설명 업데이트

- 로그 파일명 변경(주제형)
  - `20260305_dev.md` -> `20260305_dev_base_implementation.md`
  - `20260305_dev_prompt3.md` -> `20260305_dev_search_reserve_flow.md`
  - `20260305_dev_prompt4.md` -> `20260305_dev_focus_input_without_selector_wait.md`
  - `20260305_dev_prompt5.md` -> `20260305_dev_check_focused_input_first.md`
  - `20260305_dev_prompt6.md` -> `20260305_dev_infinite_1s_modal_loop.md`
  - `20260305_dev_prompt7.md` -> `20260305_dev_create_test_py_wangsimni.md`
  - `20260305_dev_prompt8.md` -> `20260305_dev_telegram_notify_in_test.md`
  - `20260305_dev_prompt9.md` -> `20260305_dev_timezone_tzdata_fallback.md`
