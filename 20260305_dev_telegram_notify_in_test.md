# 2026-03-05 Prompt8 개발 로그

## 목표
- `main.py` 적용 전에 `test.py`에 텔레그램 알림 연동을 먼저 구현.

## 변경 파일
- `test.py`
- `requirements.txt`
- `README.md`

## test.py 변경 요약
1. 텔레그램 연동 상수/환경 로딩
   - `TELEGRAM_CHAT_ID = -1003872445177`
   - `TELEGRAM_BOT_TOKEN`을 환경변수(.env 포함)에서 로딩
   - `python-dotenv`가 있으면 `load_dotenv()` 실행

2. notify 구조 확장
   - 시그니처 변경: `notify(driver=None, extra=None)`
   - 분리 함수 추가:
     - `_build_notify_text(driver=None, extra=None)`
     - `send_telegram_message(text: str)`
     - `_run_coro_safely(coro)`

3. 메시지 포맷
   - 제목/요약: `CGV 알림 - 용산 발견`
   - 영화명: `프로젝트 헤일메리`
   - 발견 사실: `극장 목록에 '용산'이 존재합니다.`
   - 발생 시각: `Asia/Seoul`
   - 가능하면 `driver.current_url` 포함

4. 비동기/윈도우 안정성
   - `python-telegram-bot` async API(`telegram.Bot.send_message`) 사용
   - Windows에서 `WindowsSelectorEventLoopPolicy` 적용 시도
   - 이미 루프가 도는 경우: 별도 스레드+새 이벤트 루프에서 코루틴 실행

5. 실패 폴백
   - 전송 실패/토큰 미설정 시 콘솔 로그 출력
   - 기존 tkinter 팝업 + print 폴백 유지

6. 호출부 변경
   - 발견 시 `notify(driver=DRIVER)` 호출

## requirements.txt
- `selenium>=4.20.0`
- `python-telegram-bot>=21.0`
- `python-dotenv>=1.0.0`

## README.md
- 텔레그램 토큰 설정 방법(환경변수/.env) 추가
- 채널 chat_id(`-1003872445177`) 명시
- `test.py` 실행 예시 기준으로 업데이트
