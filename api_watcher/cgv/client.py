"""CgvClient — CGV 예매 API 접근(HTTP·프록시·재시도·Cloudflare). 도메인 로직 없음.

주의: curl_cffi Session 은 스레드-세이프가 아님. 워처(스레드)마다 CgvClient 를 따로 생성할 것.
"""
from __future__ import annotations

import logging
import time

from curl_cffi import requests

log = logging.getLogger("cgv.client")

BFF = "https://cgv.co.kr/api/v1/booking"
CONTENT = "https://cgv.co.kr/api/v1/content"
CO = "A420"
HEADERS = {"Accept": "application/json", "Referer": "https://cgv.co.kr/cnm/movieBook/movie"}
IMPERSONATE = "chrome"


class CgvError(Exception):
    pass


class CgvClient:
    def __init__(self, timeout: float = 15.0, proxy: str = ""):
        self.timeout = timeout
        self.proxies = {"http": proxy, "https": proxy} if proxy else None
        self._new_session()

    def _new_session(self):
        self.s = requests.Session(impersonate=IMPERSONATE, timeout=self.timeout, proxies=self.proxies)

    def _get(self, base: str, path: str, params: dict, tries: int = 3) -> dict:
        last: Exception | None = None
        for i in range(tries):
            try:
                r = self.s.get(f"{base}/{path}", params=params, headers=HEADERS)
                if r.status_code == 200:
                    return r.json()
                if r.status_code in (403, 429, 503):
                    log.warning("%s HTTP %s -> 세션 갱신+백오프", path, r.status_code)
                    self._new_session()
                    last = CgvError(f"{path} HTTP {r.status_code}")
                    time.sleep(1.5 * (i + 1))
                    continue
                last = CgvError(f"{path} HTTP {r.status_code}")
            except Exception as e:
                last = e
                time.sleep(1.0 * (i + 1))
        raise last or CgvError(f"{path} failed")

    # --- 조회 ---
    def movie_list(self) -> list[dict]:
        return self._get(BFF, "searchAtktTopPostrList",
                         {"coCd": CO, "movNm": "", "div": "", "attrCd": ""})["data"]

    def find_movie_no(self, keyword: str) -> tuple[str, str]:
        for m in self.movie_list():
            if keyword in m["movNm"]:
                return m["movNo"], m["movNm"]
        raise CgvError(f"영화 미발견: {keyword}")

    def bookable_dates(self, mov_no: str, site_no: str) -> list[str]:
        """지금 예매가능한 날짜 목록(YYYYMMDD). 오픈 감지 신호."""
        d = self._get(BFF, "searchSiteScnscYmdListByMov",
                      {"coCd": CO, "movNo": mov_no, "siteNo": site_no})
        return [x["scnYmd"] for x in d.get("data", [])]

    def schedule(self, mov_no: str, site_no: str, ymd: str) -> list[dict]:
        return self._get(BFF, "searchSchByMov", {
            "coCd": CO, "siteNo": site_no, "scnYmd": ymd, "movNo": mov_no,
            "scnsNo": "", "scnSseq": "", "prodNo": "", "rtctlScopCd": "08", "custNo": "",
        })["data"]

    def seat_map(self, site_no: str, ymd: str, scns_no: str, scn_sseq: str) -> list[dict]:
        d = self._get(BFF, "searchIfSeatData", {
            "coCd": CO, "siteNo": site_no, "scnYmd": ymd,
            "scnsNo": scns_no, "scnSseq": scn_sseq, "rtctlScopCd": "08",
        })
        return d["data"]["items"][0]["seats"]

    def site_list(self) -> list[dict]:
        """전국 극장 목록 [{siteNo, siteNm, regnGrpCd}, ...] (178곳).

        응답은 {movInfo, kndInfo, regionInfo, siteInfo, rcmSiteInfo} 구조이며
        실제 극장 배열은 siteInfo 에 있다.
        """
        d = self._get(CONTENT, "site/searchAllRegionAndSite", {"coCd": CO})["data"]
        return d.get("siteInfo") or []
