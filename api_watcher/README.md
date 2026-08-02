# CGV 알리미 — 좌석 빈자리 & 예매 오픈 감시 (API, Selenium 불필요)

기존 Selenium 매크로를 대체하는 **순수 HTTP 감시 엔진**. 브라우저·크롬드라이버·로그인 없이
CGV 예매 API를 폴링해서, 내가 선언한 조건에 해당하는 일이 벌어지면 텔레그램으로 알린다.

- **빈자리(seat)**: 이미 열린 회차의 명당 취소표가 나면 알림
- **예매 오픈(open)**: 아직 안 열린 날짜/상영관이 열리면 알림 (+ 오픈 즉시 좌석 감시로 자동 승계)
- **재사용**: 어떤 영화·날짜·극장·상영관이든 `targets.yaml` 만 바꾸면 됨. 코드 수정 0.
- **다중 타겟·무중단**: 여러 감시를 한 프로세스에서 동시에, 한 타겟이 고장나도 나머지는 계속.

> 설계 상세는 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) 참고 (도메인 모델·API 레퍼런스·모듈 구조).

## 구조

```
api_watcher/
├─ cgv/                 # 엔진
│  ├─ client.py         # CGV API 접근(HTTP·프록시·재시도·Cloudflare)
│  ├─ model.py          # 상영/좌석 파싱·매칭(순수 함수)
│  ├─ notify.py         # 텔레그램 발송
│  ├─ watch.py          # 감시 루프(Seat/Open 워처, 무중단)
│  └─ config.py         # Target/Settings 로드·검증
├─ run.py               # 진입점(다중 타겟 스레드)
├─ targets.example.yaml # 감시 선언 예시 → targets.yaml 로 복사해 사용
├─ .env.example         # 비밀값 예시 → .env 로 복사
└─ cgv-watch.service    # systemd 유닛
```

## 감시 선언: targets.yaml 하나만 만진다

```yaml
defaults:
  site_no: "0013"                  # 용산아이파크몰
  site_name: 용산아이파크몰
  proxy: socks5://127.0.0.1:40000  # 서버(데이터센터 IP)면 WARP. 집이면 "" 로

targets:
  - name: spiderman-0801-imax-seat   # 빈자리 감시
    mode: seat
    movie: "스파이더맨-브랜드 뉴 데이"
    date: "20260801"
    screen: "IMAX"
    seat: { row: [F, O], col: [10, 35] }

  - name: spiderman-0808-imax-open    # 예매 오픈 감시
    mode: open
    movie: "스파이더맨-브랜드 뉴 데이"
    date: "20260808"
    screen: "IMAX"
    on_open: seat                     # 오픈되면 자동으로 좌석 감시로 승계
    seat: { row: [F, O], col: [10, 35] }
```

- `mode: seat|open` 만 바꾸면 빈자리/오픈 감시. 둘 다 같은 Target 모델.
- `screen`/`start` 생략 시 그 날짜 전 상영관/전 시간. 지정 시 그것만.
- `expected_open: "20260802 20:00"` 를 주면 그 시각 근처에 폴링을 1초로 가속(단독선예매 대비).

## 로컬 실행

```bash
cd api_watcher
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env                 # TELEGRAM_BOT_TOKEN 입력
cp targets.example.yaml targets.yaml # 감시 대상 편집

.venv/bin/python run.py --once       # 각 타겟 1회 점검(알림 X, 상태만)
.venv/bin/python run.py              # 상시 감시 (Ctrl+C 종료)
```

집/노트북(가정용 IP)에서 돌릴 땐 `targets.yaml` 의 `proxy: ""` (Cloudflare 통과됨).

## 예매 오픈 시점 예측 (scout + predict)

"8/22 예매가 언제 열릴까?"를 데이터로 추정하는 도구. 감시 서비스와 **독립적으로** 동작한다.

- `scout.py` — 여러 영화·극장의 **예매가능 날짜 목록**을 5분마다 기록 (`data/horizon.jsonl`)
- `predict.py` — 그 이력에서 규칙을 추론해 목표 날짜의 오픈 시점을 예측

### 왜 이런 구조인가

예매 오픈은 API로 **미리 알 수 없다**. 실측 결과 지평선 너머 날짜는 상영 스케줄 자체가 0개다
(= 스케줄 등록과 예매 오픈이 동시에 일어남, 선행지표 없음). 과거 이력도 조회할 수 없다.
따라서 **지금부터 관측해 쌓는 것 말고는 방법이 없다.** 관측 공백은 영구 손실이다.

핵심 아이디어: **목표 영화가 움직이기를 기다릴 필요가 없다.** 이미 지평선이 롤링 중인
다른 영화에서 주기와 시각을 먼저 학습해 목표에 적용한다. 그래서 scout는 목표 외에
비교군 영화들도 함께 관측한다(`scout.py`의 `WATCH`).

### 사용

```bash
# 서버에 타이머 설치 (5분 주기)
sudo cp cgv-scout.service cgv-scout.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now cgv-scout.timer

# 관측 이력 요약 + 목표 예측
.venv/bin/python predict.py
.venv/bin/python predict.py --movie 오디세이 --site 0013 --date 20260822
.venv/bin/python predict.py --report      # 이력 요약만
```

### 예측 로직

1. **이벤트 추출** — 지평선(최대 예매가능일)이 커진 순간들. 5분 관측이므로 발생 시각을 ±5분으로 특정.
2. **추론** — 이벤트 간격에서 주기(며칠마다), 증가폭(며칠씩), 발생 시각(하루 중 몇 시)을 중앙값으로 추정.
3. **예측** — 목표까지 필요한 확장량 ÷ 증가폭 = 남은 이벤트 수 → 마지막 이벤트 + (주기 × 횟수).
4. **폴백** — 이벤트가 2개 미만이면 **편성주 구조모델**로 대체 예측(아래).

### 관측된 구조 (2026-08-02 실측)

- CGV 편성주는 **수요일→화요일**. 지평선이 정확히 화요일에서 끝난다
  (스파이더맨 8/11(화), 오디세이 8/18(화), 7/26 관측 시 8/4(화)).
- 지평선은 **영화별·극장별로 다르다.** 전사 단일 정책이 아니며, 대형관일수록 멀리 본다
  (용산 오디세이 +16일 vs 여의도 +4일).
- **IMAX는 지연되지 않는다.** 예매가능한 모든 날짜에 IMAX 회차가 이미 존재 →
  날짜가 열리면 IMAX도 함께 열린다.
- ⚠️ 7일 간격 관측만으로는 "매일 +1일"과 "매주 +7일"을 **구분할 수 없다**(둘 다 오프셋이 유지됨).
  일 단위 관측이 필요한 이유.

### 운영 방식 (수동 확인)

예측을 폴링에 자동 반영하지 않는다. 예측이 틀려도 사고가 나지 않고, 시스템이 단순하게 유지된다.
확신이 서면 `targets.yaml`의 `expected_open`에 직접 넣으면 그 시각 전후로 폴링이 가속된다.

```yaml
expected_open: "20260812 00:00"
```

`data/horizon.jsonl`은 관측 원시데이터라 git에 올리지 않는다(하루 약 600KB 증가).

## Cloudflare 데이터센터 IP 차단 (서버 배포 시 필수)

클라우드 서버(OCI 등)의 IP는 TLS 지문을 위장해도 Cloudflare가 **IP 자체로 차단**(정적 403)한다.
해결책은 **Cloudflare WARP 프록시 모드**로 이그레스를 Cloudflare 네트워크로 우회(무료, SSH 안전).

```bash
curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | sudo gpg --yes --dearmor -o /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/cloudflare-client.list
sudo apt update && sudo apt install -y cloudflare-warp
warp-cli --accept-tos registration new
warp-cli --accept-tos mode proxy      # 연결 전에 프록시 모드 설정(전체 터널 X → SSH 안전)
warp-cli --accept-tos connect
```

그 후 `.env` 에 `CGV_PROXY=socks5://127.0.0.1:40000` (또는 targets.yaml 의 proxy). 텔레그램은 프록시 안 탐.

## 서버 배포 (OCI/Ubuntu, git pull 방식)

```bash
git clone https://github.com/hajongon/yong_imax_notify_bot.git
cd yong_imax_notify_bot/api_watcher
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# WARP 설치/연결 (위 섹션)
cp .env.example .env                 # 토큰 + CGV_PROXY
cp targets.example.yaml targets.yaml # 감시 대상
.venv/bin/python run.py --once       # 점검
sudo cp cgv-watch.service /etc/systemd/system/   # User/경로 확인 후
sudo systemctl daemon-reload && sudo systemctl enable --now cgv-watch
journalctl -u cgv-watch -f
```

- 무중단: 유닛이 `Restart=always` + `StartLimitIntervalSec=0` 이라 어떤 비정상 종료든 계속 재시작. 프로세스 자체도 시그널 전엔 스스로 안 죽음.
- 코드 업데이트: `git pull` → `sudo systemctl restart cgv-watch`
- 대상 변경: `nano targets.yaml` → `sudo systemctl restart cgv-watch`

## 참고

- 감시/알림 전용. 실제 예매(결제)는 하지 않음(로그인·결제 필요, 별개 스코프).
- 좌석 판정: `seatSaleYn == "Y"` = 예매가능. 오픈 판정: 예매가능 날짜 목록에 대상 날짜 등장.
