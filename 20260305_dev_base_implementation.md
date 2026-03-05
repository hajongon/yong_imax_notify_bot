# 2026-03-05 개발 로그

## Prompt 2 작업
- 요청 목표를 아래 순서로 반영:
  1) START_URL 접속
  2) `#swrd`에 `프로젝트 헤일메리` 검색
  3) `자주가는 CGV 목록 수정` 버튼으로 모달 오픈
  4) 모달 리스트에서 `용산` 체크
  5) 없으면 닫고 재시도, 있으면 팝업 알림 후 종료

## 구현 파일
- `main.py`
  - 필수 함수 분리 반영:
    - `open_page()`
    - `search_movie(keyword: str)`
    - `open_modal()`
    - `close_modal()`
    - `wait_modal_open()`
    - `wait_modal_close()`
    - `has_yongsan() -> bool`
    - `notify()`
  - Selenium 4 + WebDriverWait/EC 기반 대기 로직 적용
  - 검색 안정화 로직:
    - URL 변화 or 페이지 로드 완료
    - 키워드 텍스트 등장
    - 결과 컨테이너 표시
    - ENTER 실패 시 검색 버튼 클릭 폴백
  - 모달 안정화 로직:
    - `div.cgv-modal.cgv-bot-modal.active` 대기
    - `div.bottom_listCon__8g46z`(또는 유사 클래스) 대기
  - 닫기 버튼 탐색:
    - `button.btn-close` + SVG 포함 조건(name/local-name)
    - `button.btn-center-close` + `span.voice-only='닫기'`
  - 클릭 안정성:
    - 기본 click 실패 시 JS click fallback
    - stale element 재시도 처리
  - 재시도:
    - `--max-tries` 최대 반복
  - 알림:
    - `tkinter.messagebox.showinfo("CGV 알림", "용산이 목록에 있습니다")`
    - 실패 시 `winsound.Beep + print` 폴백
  - 예외 처리/로그:
    - TimeoutException/WebDriverException 단계 로그
    - 종료 시 `debug_last.png` 저장

- `README.md`
  - venv 생성/설치/실행/옵션 설명 최신화

- `requirements.txt`
  - selenium 명시

## 실행 검증 상태
- 현재 환경에서 `python` 실행 명령이 막혀 있어 런타임 검증은 미실시.
- 코드 정합성은 요구사항 매핑 기준으로 점검 완료.

## 추가 정렬
- 함수 시그니처를 요구사항 표기와 동일하게 조정:
  - `open_page()`
  - `search_movie(keyword: str)`
  - `open_modal()`
  - `close_modal()`
  - `wait_modal_open()`
  - `wait_modal_close()`
  - `has_yongsan() -> bool`
  - `notify()`
