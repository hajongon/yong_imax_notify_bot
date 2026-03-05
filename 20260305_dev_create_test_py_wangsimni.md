# 2026-03-05 Prompt7 개발 로그

## 요청
- `test.py`를 만들고 `main.py`와 기능을 동일하게 유지.
- 극장 탐색 대상은 `강남` 대신 `왕십리`로 설정.

## 작업 내용
1. `main.py`를 `test.py`로 복제.
2. `test.py`에서 극장 타겟 상수 추가:
   - `TARGET_THEATER = "왕십리"`
3. 아래 로직을 `TARGET_THEATER` 기반으로 변경:
   - `has_yongsan()` XPath 텍스트 조건
   - 발견/미발견 로그 문구
   - `notify()` 팝업 메시지
4. 기능 흐름(페이지 이동/검색/예매하기/모달 재시도/알림/스크린샷)은 `main.py`와 동일 유지.
