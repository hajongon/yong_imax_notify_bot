# 2026-03-06 모달 극장선택 확인 버튼 반영 로그

## 배경
- 기존 분기에서 `has_yongsan()`이 `True`일 때,
  - `용산아이파크몰` 선택 후
  - 모달 닫힘 대기 실패 시 `close_modal()`로 닫는 흐름이 존재.
- 사용자 요구:
  - 이 지점에서 "모달 닫기"가 아니라
  - 모달 내 `극장선택` 버튼(`<button ...>극장선택</button>`)을 반드시 클릭해야 함.

## 변경 사항
- 파일: `test.py`

1. 신규 함수 추가
- `confirm_theater_selection_in_modal()`
- 동작:
  - 활성 모달을 찾고
  - 텍스트 기준으로 `극장선택` 버튼을 탐색
  - `safe_click()`으로 클릭

2. `has_yongsan()` 성공 분기 수정
- 변경 전:
  - `select_target_theater_in_modal()` 후 `wait_modal_close()` 시도
  - 실패 시 `close_modal()` 폴백
- 변경 후:
  - `select_target_theater_in_modal()`
  - `confirm_theater_selection_in_modal()`
  - `wait_modal_close()`
- 결과:
  - 정상 경로에서 모달 닫기 버튼 폴백 없이, 요구한 확인 버튼 경유로 진행.

3. 중복 클릭 제거
- `find_theater` 루프를 빠져나온 직후 실행되던 `click_theater_select_button()` 호출 삭제.
- 이유:
  - 이미 모달 내부 `극장선택` 버튼을 눌러 적용이 끝난 상태이므로 중복/혼선 방지.

## 기대 동작
1. 모달에서 `용산아이파크몰` 선택
2. 같은 모달에서 `극장선택` 버튼 클릭
3. 모달 닫힘 확인 후 날짜/시간/좌석 검사 단계로 진행

## 참고 위치
- `test.py` 내 함수 추가: `confirm_theater_selection_in_modal()`
- `test.py` 내 분기 변경: `if has_yongsan():` 성공 경로
