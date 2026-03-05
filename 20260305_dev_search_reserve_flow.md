# 2026-03-05 Prompt3 개발 로그

## 변경 목적
- 검색 후 바로 모달 체크가 아니라,
  1) 검색 버튼 클릭
  2) 검색 결과의 예매하기 버튼 클릭
  3) 이후 예매/극장선택 UI에서 모달 체크
  순서로 플로우 확장.

## main.py 수정 사항
- START_URL 유지: `https://cgv.co.kr/cnm/movieBook/movie`
- 필수 함수 분리 반영:
  - `build_driver()`
  - `open_page(url)`
  - `search_movie(keyword)`
  - `click_search_button()`
  - `click_reserve_button()`
  - `open_modal()`
  - `close_modal()`
  - `wait_modal_open()`
  - `wait_modal_close()`
  - `has_yongsan() -> bool`
  - `notify()`
  - `main()`

### 검색 단계
- `input#swrd`를 클릭 가능 상태로 대기 후 `clear()` + `send_keys("프로젝트 헤일메리")`.
- 검색 버튼 CSS 우선 적용:
  - `button.btn-sch[title='검색하기']`
- 클릭 실패 대비 JS click fallback 적용.
- 검색 결과 로딩 대기 조건:
  - `프로젝트 헤일메리` 텍스트 등장 또는
  - `예매하기` 버튼 DOM 출현.

### 예매하기 클릭 단계
- 우선순위:
  1) `프로젝트 헤일메리` 텍스트가 포함된 카드/영역 내부 `예매하기`
  2) fallback으로 첫 번째 clickable `예매하기`
- 클릭 후 다음 화면 대기:
  - URL 변경 또는
  - `자주가는 CGV 목록 수정` 버튼/모달 관련 DOM 등장.

### 모달/용산 체크
- `(+)` 버튼: `voice-only='자주가는 CGV 목록 수정'` 텍스트 기반 XPath.
- 모달 오픈 대기:
  - `div.cgv-modal.cgv-bot-modal.active`
  - `div.bottom_listCon__8g46z` visible
- 용산 체크 XPath:
  - `.//div[contains(@class,'bottom_listCon')]//button[p[normalize-space()='용산']]`
- 닫기 버튼 후보 순서:
  1) `section.bot-modal-container button.btn-close`
  2) `section.bot-modal-container button.btn-center-close`
  3) active 모달 내부 `span.voice-only='닫기'` 포함 button
- 닫힘 대기:
  - active 모달 부재 또는
  - `display:none` / `visibility:hidden` / `aria-hidden=true` / `active` 제거.

### 안정성/예외
- `click()` 실패 시 JS fallback 공통 적용.
- stale element 재탐색 재시도.
- `TimeoutException`, `NoSuchElementException`, `StaleElementReferenceException` 단계 로그.
- 종료 전 `debug_last.png` 저장 보장.

## 문서 수정
- README를 새 플로우(검색 버튼 + 예매하기 클릭 포함) 기준으로 업데이트.
- requirements는 selenium만 유지.
