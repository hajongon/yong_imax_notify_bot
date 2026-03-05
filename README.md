# CGV 자동화 (Selenium + Telegram)

Windows + Chrome(또는 Chromium) + Selenium 4 기준입니다.

## 현재 테스트 대상
- `test.py`: `왕십리` 존재 여부 체크 + 텔레그램 알림
- `main.py`: `용산` 존재 여부 체크 + 텔레그램 알림

## 동작 흐름 (`test.py`)
1. START_URL 접속
2. 검색어 `프로젝트 헤일메리` 입력 + 검색
3. 예매하기 클릭 후 예매/극장 선택 UI 진입
4. `자주가는 CGV 목록 수정` 모달 오픈
5. 극장 목록 확인
6. 발견 시 `notify()`에서 텔레그램 채널 전송 시도
   - 실패 시 tkinter 팝업/print 폴백

## 1) 가상환경

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

## 2) 설치

```powershell
pip install -r requirements.txt
```

## 3) 텔레그램 토큰 설정

- 채널 chat_id: `-1003872445177`
- 봇 username: `imax_yong_bot`
- 토큰은 코드에 하드코딩하지 않고 환경변수(`TELEGRAM_BOT_TOKEN`)로 사용

PowerShell (현재 세션):

```powershell
$env:TELEGRAM_BOT_TOKEN = "123456789:AA..."
```

영구 설정(사용자 환경변수):

```powershell
setx TELEGRAM_BOT_TOKEN "123456789:AA..."
```

`.env` 파일 사용도 가능:

```env
TELEGRAM_BOT_TOKEN=123456789:AA...
```

## 4) 실행

테스트 스크립트 실행:

```powershell
python test.py
```

헤드리스:

```powershell
python test.py --headless
```

타임아웃 조정:

```powershell
python test.py --timeout 10
```

드라이버 경로 지정:

```powershell
python test.py --driver-path "C:\path\chromedriver.exe"
```

## 5) 옵션

- `--headless`: 헤드리스 실행
- `--timeout`: WebDriverWait 타임아웃 초 (기본 10)
- `--driver-path`: chromedriver 경로 지정 (기본: Selenium Manager)

## 6) 로그/디버그

- 단계명 포함 로그 출력
- 모달 체크는 1초 간격 무한 반복
- 종료 시 `debug_last.png` 저장
- 텔레그램 성공 시: `[notify] telegram sent to -1003872445177`
- 텔레그램 실패 시: 예외 로그 후 tkinter/print 폴백

## 7) 시간대 이슈(Windows)

- 일부 Windows Python 환경은 `Asia/Seoul` zoneinfo DB가 없어 오류가 납니다.
- 이 프로젝트는 `tzdata`를 의존성에 포함했고, 없을 경우 코드에서 KST(UTC+9)로 폴백합니다.
