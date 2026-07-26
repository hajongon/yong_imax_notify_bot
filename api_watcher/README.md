# CGV 좌석 빈자리 24시간 감시 (API 방식, Selenium 불필요)

기존 Selenium 매크로(`main.py`/`test.py`/`available-seat.py`)를 대체하는 **순수 HTTP 감시기**입니다.
브라우저·크롬드라이버·로그인 없이 CGV 예매 API를 직접 폴링해, 지정한 좌석 범위에
예매 가능 좌석이 생기면 텔레그램으로 알립니다.

## 어떻게 Selenium 없이 되나

- CGV 예매 페이지는 내부적으로 `cgv.co.kr/api/v1/booking/...` (BFF) API를 호출합니다.
- 상영 스케줄(`searchSchByMov`)·좌석맵(`searchIfSeatData`) 조회는 **로그인 없이** 됩니다.
- Cloudflare가 일반 `requests`를 TLS 지문으로 차단하지만, `curl_cffi`의 Chrome 지문
  위장(`impersonate="chrome"`)으로 통과합니다.
- 좌석 상태는 각 좌석의 `seatSaleYn == "Y"` 이면 예매 가능입니다.

## 동작/설계

1. `searchSchByMov`(약 84KB)로 매초 폴링 → 대상 상영의 잔여좌석 수(`frSeatCnt`) 확인
2. 잔여수가 **변할 때만** 무거운 좌석맵(`searchIfSeatData`, 약 536KB)을 조회 → 부하 최소화
   (취소표가 나오면 잔여수가 반드시 늘어나므로 놓치지 않음)
3. 좌석맵에서 타겟 행/열 범위 안 예매가능 좌석을 추출
4. **새로** 열린 좌석이 있으면 즉시 알림(같은 좌석 중복 알림은 억제)
5. 안전망: `CGV_FULLSCAN_SEC`마다 잔여수 변화가 없어도 좌석맵 강제 확인
6. 시간당 하트비트(생존 신호), 오류 지속 시 경고, 상영 시각 지나면 자동 종료

## 로컬 실행

```bash
cd api_watcher
pip install -r requirements.txt
cp .env.example .env      # .env 열어 TELEGRAM_BOT_TOKEN 채우기

python3 cgv_seat_watch.py --once     # 지금 한 번만 점검(알림 X, 상태만 출력)
python3 cgv_seat_watch.py            # 24시간 감시 시작 (Ctrl+C 종료)
```

## 서버 배포 (OCI, git pull 방식)

서버에서 (Ubuntu 24.04 기준):

```bash
# 1) 코드 받기
git clone https://github.com/hajongon/yong_imax_notify_bot.git
cd yong_imax_notify_bot/api_watcher

# 2) 가상환경 + 의존성 (Ubuntu 24.04는 PEP 668 때문에 venv 필수)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3) Cloudflare WARP 프록시 (데이터센터 IP 차단 우회 — 위 "Cloudflare" 섹션 참고)
#    설치 후 warp-cli mode proxy / connect 까지 완료해 둘 것

# 4) 설정 (.env 는 서버에서 직접 생성 — git 에 올라가지 않음)
cp .env.example .env
nano .env        # TELEGRAM_BOT_TOKEN 입력, CGV_PROXY=socks5://127.0.0.1:40000

# 5) 먼저 한 번 점검
.venv/bin/python cgv_seat_watch.py --once

# 6) systemd 등록 (유닛 파일의 User/경로가 본인 환경과 맞는지 확인)
sudo cp cgv-seat-watch.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cgv-seat-watch

# 7) 로그 확인
journalctl -u cgv-seat-watch -f
```

코드 업데이트 시: `git pull` 후 `sudo systemctl restart cgv-seat-watch`

## Cloudflare 데이터센터 IP 차단 (중요)

클라우드 서버(OCI 등)의 데이터센터 IP는 TLS 지문을 위장해도 Cloudflare가 **IP 자체로 차단**(정적 403)합니다.
가정용 IP(집/노트북)는 통과하지만 서버는 막힙니다. 해결책은 **Cloudflare WARP 프록시 모드**로
이그레스를 Cloudflare 네트워크로 우회하는 것입니다(무료, 라우팅 안 건드려 SSH 안전).

```bash
# WARP 설치
curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | sudo gpg --yes --dearmor -o /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/cloudflare-client.list
sudo apt update && sudo apt install -y cloudflare-warp

# 등록 -> 프록시 모드(연결 전에 설정) -> 연결
warp-cli --accept-tos registration new
warp-cli --accept-tos mode proxy
warp-cli --accept-tos connect
warp-cli --accept-tos status          # Connected 확인, SOCKS5 = 127.0.0.1:40000
```

그 후 `.env`에 `CGV_PROXY=socks5://127.0.0.1:40000` 설정. (텔레그램 발송은 프록시를 타지 않음)

## 설정 (환경변수 / .env)

전체 항목과 기본값은 [`.env.example`](.env.example) 참고. 주요 항목:

| 변수 | 기본값 | 설명 |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | (필수) | BotFather 토큰. git 에 커밋 금지 |
| `TELEGRAM_CHAT_ID` | `-1003872445177` | 알림 보낼 채널/DM id |
| `CGV_MOVIE` | 스파이더맨-브랜드 뉴 데이 | 영화명(부분일치) |
| `CGV_SITE_NO` / `CGV_SITE_NAME` | `0013` / 용산아이파크몰 | 극장 |
| `CGV_DATE` | `20260801` | 상영일 YYYYMMDD |
| `CGV_START` / `CGV_SCREEN` | `16` / `IMAX` | 상영 시작시(접두) / 상영관 키워드 |
| `CGV_ROW_LO`~`CGV_COL_HI` | F~O / 10~35 | 감시할 좌석 범위 |
| `CGV_POLL_SEC` | `1.0` | 폴링 주기(초). 0.5도 가능 |
| `CGV_ALWAYS_SEATMAP` | `0` | 1이면 매 폴링 좌석맵 조회(최대정확/최대부하) |

## 다른 상영으로 바꾸기

극장 코드는 `siteNo`, 영화·상영관·날짜만 `.env`에서 바꾸면 됩니다.
다른 극장 `siteNo`가 필요하면 아래로 조회:

```bash
curl -s "https://cgv.co.kr/api/v1/content/site/searchAllRegionAndSite?coCd=A420" \
  --tlsv1.2 | python3 -m json.tool   # (Cloudflare 때문에 curl_cffi 권장)
```

## 참고

- 이 도구는 **감시/알림 전용**입니다. 실제 예매(결제)까지 하지 않습니다.
- 좌석 조회는 비로그인으로 가능하지만, 발견 후 실제 예매는 본인이 로그인해 진행하세요.
