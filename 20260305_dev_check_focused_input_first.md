# 2026-03-05 Prompt5 개발 로그

## 요청 사항
- START_URL 접근 이후, 텍스트 입력 전에 포커싱된 인풋 요소 존재 여부를 먼저 체크.

## 수정 내용
- `main.py`의 `search_movie(keyword)` 보강:
  - `driver.switch_to.active_element` 조회 후 아래 조건 확인:
    - tag가 `input` 또는 `textarea`
    - 또는 `contenteditable=true`
  - 체크 결과를 로그로 출력:
    - `tag`, `input_like`
  - 입력 가능 포커스가 아니면 경고 로그 후 `body.send_keys(keyword)` 폴백.

## 기대 효과
- "포커싱된 인풋 먼저 체크" 요구사항을 충족하면서,
  포커스가 비정상인 경우에도 기존 플로우가 중단되지 않음.
