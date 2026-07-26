# CGV 알리미 — 기술 설계 문서

> 목적: 이 프로덕트를 **온전히 스스로 소유·운영·확장**할 수 있도록, 무엇이 어떻게 설계됐는지를 남긴다.
> 대상 독자: 이 코드를 물려받아 고치고 늘려갈 개발자(=당신).

상태 범례: ✅ 구현·배포됨 · 🟡 설계됨(구현 예정) · 💡 확장 아이디어

---

## 1. 한 문장 요약

CGV 예매 API를 **비로그인·순수 HTTP**로 폴링해서, **"내가 지정한 조건(타겟)"** 에 해당하는
일이 벌어지는 순간 — 좌석이 나거나(빈자리), 예매가 열리거나(오픈) — 텔레그램으로 알린다.
Selenium 없음. Cloudflare는 TLS 지문 위장 + (서버의 경우) WARP 프록시로 통과한다.

## 2. 핵심 설계 원칙: "타겟(Target)"이 재사용 단위다

재사용성의 전부는 이 한 가지에서 나온다: **감시하고 싶은 것을 선언적 데이터(Target)로 표현**하고,
엔진은 그 데이터를 해석해 돌 뿐, 특정 영화/날짜/상영관을 코드에 박지 않는다.

```
Target = 무엇을(movie) · 어디서(site) · 언제(date) · 어느 관에서(screen/time) ·
         무엇을 감시할지(mode: seat|open) · 조건(seat 범위 등) · 어떻게 알릴지(notify)
```

- 영화·날짜·상영관은 **전부 파라미터**다. 코드는 "스파이더맨"도 "용산"도 "IMAX"도 모른다.
- "빈자리 알림"과 "오픈 알림"은 **같은 Target 모델의 mode 값만 다른 것**이다. → 요구사항(빈자리에도 동일 적용) 충족.
- Target을 여러 개 선언하면 여러 감시를 동시에 돌린다(예: 8/1 IMAX 빈자리 + 8/8 오픈 감시).

이 원칙 하나로 "어떤 영화·날짜·상영관이든 재사용 가능"이 자동으로 성립한다.

## 3. 도메인 모델 — CGV 예매의 계층

모든 API가 이 계층을 키로 쓴다. 이걸 이해하면 API 전체가 이해된다.

```
회사(coCd=A420, CGV 한국)
└─ 영화(movNo)              예: 스파이더맨-브랜드 뉴 데이 = 30001192
   └─ 극장(siteNo)          예: 용산아이파크몰 = 0013
      └─ 상영일(scnYmd)     예: 20260801  (YYYYMMDD)
         └─ 상영/회차       상영관(scnsNo/scnsNm 예: IMAX관/018) × 시간(scnSseq/scnsrtTm 예: 1600)
            └─ 좌석          seatRowNm(행) + seatNo(열), 상태 seatSaleYn
```

- `scnsrtTm`은 `"1600"`, 심야는 `"2630"`(=익일 02:30) 형태.
- 좌석 식별은 **행(A~P) + 열(숫자)**. 우리의 "명당 범위"는 행·열 사각형(예: F~O · 10~35).

## 4. 리버스 엔지니어링한 API 레퍼런스 (검증 완료)

BFF 경유. 베이스 `https://cgv.co.kr/api/v1/booking/` (백엔드 `/cnm/atkt/`로 프록시).
**전부 GET · 비로그인 · JSON**. 공통 파라미터 `coCd=A420`.

| 용도 | 엔드포인트 | 핵심 파라미터 | 핵심 응답 |
|---|---|---|---|
| 영화 목록 | `searchAtktTopPostrList` | `movNm=&div=&attrCd=` | `movNo`, `movNm` |
| **예매가능 날짜** | `searchSiteScnscYmdListByMov` | `movNo`, `siteNo` | 예매 열린 `scnYmd` 목록 ← **오픈 감지 신호** |
| 상영 스케줄 | `searchSchByMov` | `siteNo`, `scnYmd`, `movNo`, `rtctlScopCd=08` | 상영별 `scnsNm`·`scnsrtTm`·`scnsNo`·`scnSseq`·`frSeatCnt`·`stcnt` |
| 좌석맵 | `searchIfSeatData` | `siteNo`, `scnYmd`, `scnsNo`, `scnSseq`, `rtctlScopCd=08` | `data.items[0].seats[]` (행/열/`seatSaleYn`) |
| 극장 목록 | `/api/v1/content/site/searchAllRegionAndSite` | `coCd` | `siteNo`, `siteNm` |

### 두 가지 감지 신호 (검증됨)

- **빈자리(seat)**: 좌석의 `seatSaleYn == "Y"` 가 예매가능. Y 개수가 스케줄 `frSeatCnt`와 정확히 일치함을 실측 확인. (`seatStusCd`는 좌석 존재여부일 뿐, 실시간 매진 아님 — 주의)
- **오픈(open)**: `searchSiteScnscYmdListByMov` 의 날짜 목록에 타겟 날짜가 **없다가 생기면** 오픈. 실측: 현재 용산 스파이더맨은 7/29~8/4만 반환, 8/8은 없음. 두 신호용 엔드포인트 모두 `cf-cache-status: DYNAMIC`(CDN 캐시 없음) → **초 단위 실시간 감지 가능**, 응답도 수백 바이트로 가벼움.

## 5. 아키텍처 — 모듈과 책임 ✅

**역할별로 분리**돼 있다(작은 프로덕트이므로 과분할하지 않음).

```
api_watcher/
├─ cgv/
│  ├─ client.py     # CgvClient: HTTP·프록시·재시도·Cloudflare. API 메서드만. 도메인 모름.
│  ├─ model.py      # Showing/Seat 파싱, 타겟 매칭(상영관 필터, 좌석범위), seatSaleYn 해석
│  ├─ notify.py     # Notifier: 텔레그램 발송·메시지 포맷. 인터페이스로 두어 교체 가능(💡 Slack/Discord)
│  ├─ watch.py      # Watcher 베이스 + SeatWatcher + OpenWatcher. 폴링 루프·델타·백오프·하트비트
│  └─ config.py     # Target/Settings 데이터클래스 + 파일 로드 + 검증
├─ run.py           # 진입점: 타겟 로드 → 하나/여럿 실행(asyncio) → 시그널 처리
├─ targets.yaml     # ★ 사용자가 만지는 유일한 파일(감시 선언). git 미포함(개인 설정)
├─ .env             # 비밀값만(텔레그램 토큰, 프록시). git 미포함
└─ docs/            # 이 문서 등
```

**데이터 흐름**: `run.py` 가 `targets.yaml`+`.env`를 읽어 Target 리스트를 만들고,
각 Target을 **독립 스레드**(Seat/Open 워처)로 돌린다. 워처마다 자기 `CgvClient` 를 가진다
(curl_cffi Session 은 스레드-세이프가 아니므로 공유하지 않음).
Watcher는 `client`로 조회 → `model`로 매칭 → 변화 감지 → `notify`로 발송.

> **동시성 선택**: asyncio 대신 **스레드**를 택했다. 타겟 수가 적고(수 개), 기존 동기 클라이언트를
> 그대로 재사용하며, 스레드 격리가 "한 타겟이 죽어도 나머지는 산다"를 단순·견고하게 보장한다.

**의존 방향**: `run → watch → (client, model, notify, config)`. client/model/notify/config는
서로 모름(단방향). 테스트하기 쉽고, 한 조각만 바꿔도 나머지에 안 번진다.

## 6. 설정 모델 — 재사용의 실체 🟡

사용자는 코드가 아니라 `targets.yaml` 한 파일만 만진다.

```yaml
defaults:                      # 공통 기본값(타겟에서 생략 시 상속)
  site_no: "0013"
  site_name: 용산아이파크몰
  poll_sec: 1.0
  proxy: socks5://127.0.0.1:40000   # 서버(데이터센터 IP)에서만 필요

targets:
  # (1) 빈자리 감시 — 이미 열린 회차의 명당 취소표
  - name: spiderman-0801-imax-seat
    mode: seat
    movie: "스파이더맨-브랜드 뉴 데이"
    date: "20260801"
    screen: "IMAX"             # 상영관 키워드(생략 시 전 상영관)
    start: "16"                # 시작시(접두, 생략 가능)
    seat: { row: [F, O], col: [10, 35] }

  # (2) 예매 오픈 감시 — 아직 안 열린 날짜
  - name: spiderman-0808-imax-open
    mode: open
    movie: "스파이더맨-브랜드 뉴 데이"
    date: "20260808"
    screen: "IMAX"            # "IMAX관이 열리면"(생략 시 그 날짜 아무거나 열리면)
    expected_open: "20260802 20:00"   # (선택) 공지된 오픈 시각 → 그 근처 폴링 가속
    on_open: seat             # (선택) 오픈되면 자동으로 좌석 감시로 승계
    seat: { row: [F, O], col: [10, 35] }
```

- **하나만 쓰면 단일 감시, 여럿 쓰면 동시 감시.** "재사용"이 설정 데이터 수준에서 끝난다.
- 다른 영화/극장/상영관은 값만 바꾸면 됨. movNo·siteNo는 엔진이 이름으로 조회해 해석(코드 수정 0).
- 비밀값(토큰)은 `.env`, 감시 선언은 `targets.yaml`로 분리 → 안전 + 명확.

## 7. 감시 모드 상세 ✅

### mode: seat (빈자리) ✅
스케줄로 `frSeatCnt` 폴링 → 변할 때만 좌석맵 조회(저부하) → 타겟 범위 안 `seatSaleYn=Y`
**새 좌석**이 생기면 알림(델타 기반, 중복 억제). 상영 시각 지나면 자동 종료.

### mode: open (오픈) ✅
`searchSiteScnscYmdListByMov`로 예매가능 날짜 폴링 → 타겟 날짜 등장 시,
(상영관 지정됐으면) `searchSchByMov`로 그 관·시간까지 확인 → 알림. 날짜만 열리고
지정 상영관 회차가 아직 없으면 계속 대기.

### on_open: seat — 오픈→빈자리 자동 승계 ✅
오픈 감지 순간 **같은 스레드가 그 날짜/상영관 대상 seat 감시로 이어서 실행**.
"오픈되자마자 명당 잡기"를 끊김 없이 연결. (인기작 단독선예매 대응)

## 8. 폴링 전략 — 적응형 🟡

한 가지 주기로 다 하지 않는다. 모드/상황별로 다르게:

| 상황 | 주기 |
|---|---|
| seat 감시(상시) | 1s (스케줄 폴링, 좌석맵은 변화 시만) — 실측상 안전 |
| open 감시(오픈시각 모름) | 30~60s (언젠가 열리면 잡으면 됨) |
| open 감시(`expected_open` 근처) | T-2분부터 1s로 **가속** → T+10분까지 → 복귀 |

지터(±20%)로 완벽한 주기성 회피. 응답이 가벼워(수백 바이트~수십 KB) 부하 걱정 낮음.

## 9. 신뢰성 설계 ✅(seat 기준 구현·검증)

- **Cloudflare**: `curl_cffi impersonate="chrome"`로 TLS 지문 위장. 데이터센터 IP는 하드 403 → **WARP 프록시 모드**(socks5://127.0.0.1:40000)로 이그레스 우회. 403 시 세션 갱신+백오프.
- **오류 백오프**: 연속 실패 시 지수 백오프, 임계 초과 시 1회 경고 알림(스팸 억제).
- **하트비트**: 시간당 "살아있음" 신호 → 침묵=고장.
- **정상 종료 exit 0**(상영시각 경과/시그널) vs 비정상 exit≠0 → systemd `Restart=on-failure`와 맞물려 재시작 루프 방지.
- **텔레그램**은 서버 IP에서 직접(프록시 불필요).

## 10. 배포·운영 ✅

- OCI(Ubuntu 24.04/ARM64), venv, systemd(`cgv-seat-watch`), WARP(warp-svc, 부팅 자동연결).
- 코드 갱신: `git pull` → `systemctl restart`.
- 비밀/설정은 서버 로컬 파일(`.env`, `targets.yaml`), git 미포함.
- ✅ 다중 타겟: 한 프로세스(스레드) + systemd 서비스 1개(`cgv-watch`). `Restart=always` + `StartLimitIntervalSec=0` 로 무한 재시작. 프로세스는 시그널 전엔 스스로 종료 안 함(무중단).

## 11. 확장 가이드 💡

- **알림 채널 추가**: `notify.py`에 Notifier 구현체 추가(Slack/Discord/푸시). Target의 `notify:`로 선택.
- **극장/영화 추가**: 코드 수정 0. `targets.yaml`에 값만. movNo/siteNo 미상이면 이름으로 조회.
- **새 감시 모드**: `watch.py`에 Watcher 서브클래스 추가(예: 특정 좌석 지정석, 가격대, 특정 등급 관람가). Target `mode:`에 등록.
- **예매 자동화**: 본 설계는 감지·알림 전용. 실제 결제 자동화는 로그인·결제라 별개 스코프(권장하지 않음).

## 12. 현재 상태 요약

- ✅ 모듈 분리(`cgv/` 패키지)·`targets.yaml`·seat/open 모드·다중 타겟·on_open 승계: **구현·테스트 완료**.
- ✅ 단위 테스트(model/config) + 라이브 테스트(seat/open) + 무중단 테스트(고장 타겟 격리) 통과.
- 배포 방식: OCI(Ubuntu/ARM64) + WARP 프록시 + systemd `cgv-watch`(Restart=always). (§10 참고)
- 문서: 본 `ARCHITECTURE.md`(설계) + `README.md`(사용법) + 코드 내 docstring + API 레퍼런스(§4).
