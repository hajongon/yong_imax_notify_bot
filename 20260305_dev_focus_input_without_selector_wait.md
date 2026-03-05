# 2026-03-05 Prompt4 개발 로그

## 이슈
- 실행 로그에서 `open_page` 단계 TimeoutException 발생.
- 원인 후보: START_URL 진입 직후 `input#swrd`를 기다리는 조건이 실제 렌더 타이밍과 맞지 않음.

## 사용자 요청 반영
- "start url 접근 시 input 찾지 말고 바로 텍스트 입력" 반영.

## 수정 사항
- `main.py`
  - `open_page(url)`
    - `input#swrd` 대기 제거.
    - `body` 존재만 확인하도록 변경.
  - `search_movie(keyword)`
    - `input#swrd` 직접 탐색 제거.
    - 현재 포커스 요소(`driver.switch_to.active_element`)에 바로 키워드 입력.
    - 실패 시 `body.send_keys(keyword)` 폴백.
    - 입력 전 `Ctrl+A` + `Delete`로 기존 값 제거 시도.

## 기대 효과
- START_URL 진입 직후 검색 input 탐색 실패로 중단되는 문제를 피하고,
  사용자가 요청한 "바로 텍스트 입력" 동작으로 진행 가능.
