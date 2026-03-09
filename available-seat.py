from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from telegram import Bot

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

START_URL = "https://cgv.co.kr/tme/itgrSrch"
SEARCH_KEYWORD = "프로젝트 헤일메리"
TARGET_THEATER = "용산아이파크몰"
TARGET_DAY_OF_WEEK = "토"
TARGET_DAY_NUMBER = "21"
WATCH_START_TIMES = ["13:20", "16:30"]
TARGET_ROW_START = "F"
TARGET_ROW_END = "O"
TARGET_COL_MIN = 10
TARGET_COL_MAX = 35
POLL_INTERVAL_SEC = 1.0
LOGIN_POPUP_WAIT_SEC = 2
TELEGRAM_CHAT_ID = -1003872445177

DRIVER: Optional[webdriver.Chrome] = None
WAIT: Optional[WebDriverWait] = None


def configure_logging() -> None:
    if load_dotenv:
        load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CGV 예매 + 극장 목록 용산아이파크몰 체크")
    parser.add_argument("--headless", action="store_true", help="헤드리스 모드")
    parser.add_argument("--timeout", type=int, default=10, help="요소 대기 시간(초)")
    parser.add_argument(
        "--driver-path",
        default=None,
        help="chromedriver 경로(미지정 시 Selenium Manager 사용)",
    )
    return parser.parse_args()


def _ctx() -> tuple[webdriver.Chrome, WebDriverWait]:
    if DRIVER is None or WAIT is None:
        raise RuntimeError("Driver/Wait not initialized")
    return DRIVER, WAIT


def build_driver(headless: bool = False, driver_path: Optional[str] = None) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1440,1200")
    options.add_argument("--lang=ko-KR")

    if driver_path:
        service = Service(executable_path=driver_path)
        return webdriver.Chrome(service=service, options=options)
    return webdriver.Chrome(options=options)


def safe_click(driver: webdriver.Chrome, element) -> None:
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
    try:
        element.click()
    except WebDriverException:
        driver.execute_script("arguments[0].click();", element)


def open_page(url: str) -> None:
    driver, wait = _ctx()
    logging.info("[open_page] 이동: %s", url)
    driver.get(url)
    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    logging.info("[open_page] 기본 페이지 로딩 완료")


def search_movie(keyword: str) -> None:
    driver, wait = _ctx()
    logging.info("[search_movie] 포커스된 요소에 텍스트 입력: %s", keyword)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    active = None
    try:
        active = driver.switch_to.active_element
        tag = (active.tag_name or "").lower()
        input_like = tag in {"input", "textarea"} or (
            (active.get_attribute("contenteditable") or "").lower() == "true"
        )
        logging.info(
            "[search_movie] 포커스 요소 확인: tag=%s, input_like=%s",
            tag,
            input_like,
        )
        if not input_like:
            raise NoSuchElementException("포커스된 입력 가능 요소가 아님")
        active.send_keys(Keys.CONTROL, "a")
        active.send_keys(Keys.DELETE)
        active.send_keys(keyword)
    except Exception:
        logging.warning("[search_movie] 포커스 인풋 미확인 -> body 입력 폴백")
        body = driver.find_element(By.TAG_NAME, "body")
        body.send_keys(keyword)


def click_search_button() -> None:
    driver, wait = _ctx()
    logging.info("[click_search_button] 검색 버튼 클릭 시도")

    btn = wait.until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn-sch[title='검색하기']"))
    )
    safe_click(driver, btn)

    def search_loaded(drv: webdriver.Chrome) -> bool:
        keyword_found = len(
            drv.find_elements(By.XPATH, "//*[contains(normalize-space(.),'프로젝트 헤일메리')]")
        ) > 0

        reserve_clickable = len(
            drv.find_elements(
                By.XPATH,
                "//button[contains(@class,'btn') and contains(@class,'btn-md') and contains(@class,'line-main') and normalize-space()='예매하기']",
            )
        ) > 0

        return keyword_found or reserve_clickable

    wait.until(search_loaded)
    logging.info("[click_search_button] 검색 결과 로딩 확인")


def click_reserve_button() -> None:
    driver, wait = _ctx()
    logging.info("[click_reserve_button] 예매하기 버튼 탐색")

    before_url = driver.current_url

    preferred_xpath = (
        "(//*[contains(normalize-space(.), '프로젝트 헤일메리')]"
        "/ancestor::*[self::li or self::article or self::section or self::div][1]"
        "//button[contains(@class,'btn') and contains(@class,'btn-md') and contains(@class,'line-main')"
        " and normalize-space()='예매하기'])[1]"
    )

    fallback_xpath = (
        "(//button[contains(@class,'btn') and contains(@class,'btn-md') and contains(@class,'line-main')"
        " and normalize-space()='예매하기'])[1]"
    )

    clicked = False
    for xpath in [preferred_xpath, fallback_xpath]:
        try:
            for _ in range(3):
                try:
                    btn = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
                    safe_click(driver, btn)
                    clicked = True
                    break
                except StaleElementReferenceException:
                    logging.warning("[click_reserve_button] stale element, 재탐색")
            if clicked:
                break
        except TimeoutException:
            continue

    if not clicked:
        raise TimeoutException("예매하기 버튼을 찾지 못했습니다")

    def booking_ui_ready(drv: webdriver.Chrome) -> bool:
        if drv.current_url != before_url:
            return True

        favorite_btn = drv.find_elements(
            By.XPATH,
            "//button[.//span[contains(@class,'voice-only') and normalize-space()='자주가는 CGV 목록 수정']]",
        )
        modal_related = drv.find_elements(
            By.CSS_SELECTOR,
            "div.cgv-modal.cgv-bot-modal, div.bottom_listCon__8g46z",
        )
        return len(favorite_btn) > 0 or len(modal_related) > 0

    wait.until(booking_ui_ready)
    logging.info("[click_reserve_button] 예매/극장 선택 UI 진입 확인")


def open_modal() -> None:
    driver, wait = _ctx()
    logging.info("[open_modal] 자주가는 CGV 목록 수정 버튼 클릭")
    plus_xpath = (
        "(//button[.//span[contains(@class,'voice-only') and "
        "normalize-space()='자주가는 CGV 목록 수정']])[1]"
    )

    for _ in range(3):
        try:
            btn = wait.until(EC.element_to_be_clickable((By.XPATH, plus_xpath)))
            safe_click(driver, btn)
            return
        except StaleElementReferenceException:
            logging.warning("[open_modal] stale element, 재탐색")

    raise TimeoutException("자주가는 CGV 목록 수정 버튼 클릭 실패")


def wait_modal_open() -> None:
    _, wait = _ctx()
    logging.info("[wait_modal_open] 모달 오픈 대기")
    wait.until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, "div.cgv-modal.cgv-bot-modal.active"))
    )
    wait.until(
        EC.visibility_of_element_located(
            (By.CSS_SELECTOR, "div.cgv-modal.cgv-bot-modal.active div.bottom_listCon__8g46z")
        )
    )


def has_yongsan() -> bool:
    _, wait = _ctx()
    modal = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "div.cgv-modal.cgv-bot-modal.active"))
    )

    target_xpath = (
        f".//div[contains(@class,'bottom_listCon')]//button[p[normalize-space()='{TARGET_THEATER}']]"
    )
    return len(modal.find_elements(By.XPATH, target_xpath)) > 0


def select_target_theater_in_modal() -> None:
    driver, wait = _ctx()
    logging.info("[select_target_theater_in_modal] 모달에서 %s 선택", TARGET_THEATER)
    modal = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "div.cgv-modal.cgv-bot-modal.active"))
    )
    target_xpath = (
        f".//div[contains(@class,'bottom_listCon')]//button[p[normalize-space()='{TARGET_THEATER}']]"
    )
    btn = wait.until(lambda _: modal.find_element(By.XPATH, target_xpath))
    safe_click(driver, btn)


def confirm_theater_selection_in_modal() -> None:
    driver, wait = _ctx()
    logging.info("[confirm_theater_selection_in_modal] 모달에서 '극장선택' 클릭")
    modal = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "div.cgv-modal.cgv-bot-modal.active"))
    )
    confirm_btn = wait.until(
        lambda _: modal.find_element(
            By.XPATH,
            ".//button[normalize-space()='극장선택' or .//span[normalize-space()='극장선택']]",
        )
    )
    safe_click(driver, confirm_btn)


def close_modal() -> None:
    driver, wait = _ctx()
    logging.info("[close_modal] 모달 닫기 버튼 클릭")
    modal = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "div.cgv-modal.cgv-bot-modal.active"))
    )

    candidates = [
        (By.CSS_SELECTOR, "section.bot-modal-container button.btn-close"),
        (By.CSS_SELECTOR, "section.bot-modal-container button.btn-center-close"),
        (
            By.XPATH,
            ".//button[.//span[contains(@class,'voice-only') and normalize-space()='닫기']]",
        ),
    ]

    for by, locator in candidates:
        try:
            for _ in range(3):
                try:
                    elements = modal.find_elements(by, locator)
                    for el in elements:
                        if el.is_displayed() and el.is_enabled():
                            safe_click(driver, el)
                            return
                    break
                except StaleElementReferenceException:
                    modal = wait.until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, "div.cgv-modal.cgv-bot-modal.active")
                        )
                    )
        except Exception:
            continue

    raise NoSuchElementException("닫기 버튼을 찾지 못했습니다")


def wait_modal_close() -> None:
    driver, wait = _ctx()
    logging.info("[wait_modal_close] 모달 닫힘 대기")

    def modal_closed(drv: webdriver.Chrome) -> bool:
        mods = drv.find_elements(By.CSS_SELECTOR, "div.cgv-modal.cgv-bot-modal.active")
        if not mods:
            return True

        modal = mods[0]
        cls = (modal.get_attribute("class") or "").strip()
        style = (modal.get_attribute("style") or "").replace(" ", "").lower()
        aria_hidden = (modal.get_attribute("aria-hidden") or "").lower()

        hidden_style = "display:none" in style or "visibility:hidden" in style
        inactive = "active" not in cls.split()
        hidden_aria = aria_hidden == "true"
        return hidden_style or inactive or hidden_aria

    wait.until(modal_closed)


def click_theater_select_button() -> None:
    driver, wait = _ctx()
    logging.info("[click_theater_select_button] '극장선택' 버튼 클릭")
    btn = wait.until(
        EC.element_to_be_clickable(
            (
                By.XPATH,
                "//button[contains(normalize-space(.), '극장선택')]",
            )
        )
    )
    safe_click(driver, btn)


def select_target_date(day_of_week: str, day_number: str) -> None:
    driver, wait = _ctx()
    logging.info("[select_target_date] 날짜 선택: %s %s", day_of_week, day_number)
    xpath = (
        "//button["
        f".//span[normalize-space()='{day_of_week}'] and "
        f".//span[normalize-space()='{day_number}']"
        "]"
    )
    btn = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
    safe_click(driver, btn)


def click_time_slot(start_time: str) -> None:
    driver, wait = _ctx()
    logging.info("[click_time_slot] 시간대 선택: %s", start_time)
    xpath = (
        "//button["
        f".//span[normalize-space()='{start_time}'] "
        f"or contains(@aria-label, '{start_time}')"
        "]"
    )
    btn = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
    safe_click(driver, btn)
    if handle_login_popup_and_wait():
        logging.info("[click_time_slot] 수동 로그인 완료 후 시간대 재선택: %s", start_time)
        btn = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
        safe_click(driver, btn)

    def time_or_seat_loaded(drv: webdriver.Chrome) -> bool:
        active_time_btn = drv.find_elements(
            By.XPATH,
            (
                "//button[@aria-pressed='true' and "
                f"(.//span[normalize-space()='{start_time}'] or contains(@aria-label, '{start_time}'))]"
            ),
        )
        seat_buttons = drv.find_elements(By.CSS_SELECTOR, "button[data-seatlocno]")
        return len(active_time_btn) > 0 or len(seat_buttons) > 0

    wait.until(time_or_seat_loaded)


def handle_login_popup_and_wait() -> bool:
    driver, _ = _ctx()
    confirm_xpath = (
        "//button["
        "normalize-space()='확인' "
        "or .//span[normalize-space()='확인']"
        "]"
    )
    try:
        btn = WebDriverWait(driver, LOGIN_POPUP_WAIT_SEC).until(
            EC.element_to_be_clickable((By.XPATH, confirm_xpath))
        )
    except TimeoutException:
        return False

    logging.info("[handle_login_popup_and_wait] 로그인 팝업 '확인' 클릭")
    safe_click(driver, btn)
    login_alert = (
        "[로그인 필요]\n"
        f"영화관: {TARGET_THEATER}\n"
        f"날짜: {TARGET_DAY_OF_WEEK} {TARGET_DAY_NUMBER}\n"
        "상태: 시간대 클릭 후 로그인 팝업 확인 버튼 자동 클릭 완료\n"
        "요청: 브라우저에서 로그인 후 자동화 재개"
    )
    send_telegram_message(login_alert)
    print("[manual-login] 브라우저에서 로그인 완료 후 Enter를 눌러주세요.")
    try:
        input()
    except EOFError:
        logging.warning("[handle_login_popup_and_wait] 표준 입력 없음, 15초 대기 후 계속")
        time.sleep(15)
    return True


def _extract_seat_name(seat_button) -> str:
    spans = seat_button.find_elements(By.XPATH, ".//span[normalize-space()]")
    for span in spans:
        txt = span.text.strip().upper()
        if re.fullmatch(r"[A-Z]\d{1,2}", txt):
            return txt

    raw = (seat_button.text or "").strip().upper()
    m = re.search(r"\b([A-Z]\d{1,2})\b", raw)
    if m:
        return m.group(1)

    aria = (seat_button.get_attribute("aria-label") or "").upper()
    m = re.search(r"\b([A-Z]\d{1,2})\b", aria)
    if m:
        return m.group(1)

    return ""


def _build_target_seat_set() -> set[str]:
    seats: set[str] = set()
    for row_ord in range(ord(TARGET_ROW_START), ord(TARGET_ROW_END) + 1):
        row = chr(row_ord)
        for col in range(TARGET_COL_MIN, TARGET_COL_MAX + 1):
            seats.add(f"{row}{col}")
    return seats


def find_available_target_seats() -> list[str]:
    driver, wait = _ctx()
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "button[data-seatlocno]")))
    target_set = _build_target_seat_set()
    found: set[str] = set()
    for btn in driver.find_elements(By.CSS_SELECTOR, "button[data-seatlocno]"):
        if btn.get_attribute("disabled") is not None:
            continue
        seat_name = _extract_seat_name(btn)
        if seat_name in target_set:
            found.add(seat_name)
    return sorted(found, key=lambda s: (s[0], int(s[1:])))


def _run_coro_safely(coro) -> None:
    if sys.platform.startswith("win"):
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except Exception:
            pass

    try:
        asyncio.get_running_loop()
        loop_running = True
    except RuntimeError:
        loop_running = False

    if not loop_running:
        asyncio.run(coro)
        return

    err_holder: dict[str, Exception] = {}

    def _worker() -> None:
        if sys.platform.startswith("win"):
            try:
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            except Exception:
                pass
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(coro)
        except Exception as exc:
            err_holder["error"] = exc
        finally:
            loop.close()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join()
    if "error" in err_holder:
        raise err_holder["error"]


def _build_notify_text(
    theater: str,
    day_of_week: str,
    day_number: str,
    start_time: str,
    seat_names: list[str],
    driver=None,
) -> str:
    try:
        now_kr = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S %Z")
    except ZoneInfoNotFoundError:
        # tzdata가 없는 환경(일부 Windows Python 배포판) 대비 고정 KST(UTC+9) 폴백
        kst = timezone(timedelta(hours=9), name="KST")
        now_kr = datetime.now(kst).strftime("%Y-%m-%d %H:%M:%S %Z")
    current_url = ""
    try:
        if driver is not None:
            current_url = driver.current_url
    except Exception:
        current_url = ""

    lines = [
        "CGV 좌석 알림",
        f"영화명: {SEARCH_KEYWORD}",
        f"영화관: {theater}",
        f"날짜: {day_of_week} {day_number}",
        f"시간대: {start_time}",
        f"발견 좌석: {', '.join(seat_names)}",
        f"발생 시각(Asia/Seoul): {now_kr}",
    ]
    if current_url:
        lines.append(f"현재 URL: {current_url}")
    return "\n".join(lines)


def send_telegram_message(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("[notify] TELEGRAM_BOT_TOKEN 미설정 -> telegram skip")
        return False

    async def _send() -> None:
        bot = Bot(token=token)
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            disable_web_page_preview=True,
        )

    try:
        _run_coro_safely(_send())
        print(f"[notify] telegram sent to {TELEGRAM_CHAT_ID}")
        return True
    except Exception as exc:
        print(f"[notify] telegram send failed: {type(exc).__name__}: {exc}")
        return False


def notify(driver, start_time: str, seat_names: list[str]) -> None:
    title = "CGV 알림"
    message = _build_notify_text(
        theater=TARGET_THEATER,
        day_of_week=TARGET_DAY_OF_WEEK,
        day_number=TARGET_DAY_NUMBER,
        start_time=start_time,
        seat_names=seat_names,
        driver=driver,
    )
    sent = send_telegram_message(message)
    if sent:
        return

    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showinfo(title=title, message=message)
        root.destroy()
    except Exception as exc:
        logging.error("[notify] tkinter 실패: %s", exc)
        try:
            import winsound

            winsound.Beep(1200, 700)
        except Exception as beep_exc:
            logging.error("[notify] winsound 실패: %s", beep_exc)
        print(message)


def main() -> int:
    global DRIVER, WAIT

    configure_logging()
    args = parse_args()

    try:
        DRIVER = build_driver(headless=args.headless, driver_path=args.driver_path)
        WAIT = WebDriverWait(DRIVER, args.timeout)

        open_page(START_URL)
        search_movie(SEARCH_KEYWORD)
        click_search_button()
        click_reserve_button()

        # 기존 플로우 유지: 모달에서 TARGET_THEATER 존재 확인
        find_attempt = 0
        while True:
            find_attempt += 1
            logging.info("[find_theater] 시도 %d", find_attempt)
            try:
                open_modal()
                wait_modal_open()

                if has_yongsan():
                    logging.info("[find_theater] %s 발견", TARGET_THEATER)
                    select_target_theater_in_modal()
                    confirm_theater_selection_in_modal()
                    wait_modal_close()
                    break

                logging.info("[find_theater] %s 없음 -> 재시도", TARGET_THEATER)
                close_modal()
                wait_modal_close()
                time.sleep(POLL_INTERVAL_SEC)
            except (TimeoutException, NoSuchElementException, StaleElementReferenceException) as exc:
                logging.error("[find_theater:%d] 모달 처리 실패: %s", find_attempt, exc)
                try:
                    close_modal()
                    wait_modal_close()
                except Exception:
                    pass
                time.sleep(POLL_INTERVAL_SEC)

        select_target_date(TARGET_DAY_OF_WEEK, TARGET_DAY_NUMBER)

        seat_attempt = 0
        while True:
            try:
                for start_time in WATCH_START_TIMES:
                    seat_attempt += 1
                    logging.info("[seat_loop] 시도 %d, 시간대 %s", seat_attempt, start_time)
                    click_time_slot(start_time)

                    available_seats = find_available_target_seats()
                    if available_seats:
                        logging.info("[seat] 후보 좌석 발견: %s", ", ".join(available_seats))
                        notify(driver=DRIVER, start_time=start_time, seat_names=available_seats)
                        return 0

                    logging.info(
                        "[seat] 후보 좌석 없음 (범위 %s~%s, %d~%d / 시간대 %s)",
                        TARGET_ROW_START,
                        TARGET_ROW_END,
                        TARGET_COL_MIN,
                        TARGET_COL_MAX,
                        start_time,
                    )
                time.sleep(POLL_INTERVAL_SEC)

            except (TimeoutException, NoSuchElementException, StaleElementReferenceException) as exc:
                logging.error("[seat_loop:%d] 처리 실패: %s", seat_attempt, exc)
                try:
                    click_theater_select_button()
                    select_target_date(TARGET_DAY_OF_WEEK, TARGET_DAY_NUMBER)
                except Exception:
                    pass
                time.sleep(POLL_INTERVAL_SEC)

    except TimeoutException as exc:
        logging.error("[main] TimeoutException: %s", exc)
        return 2
    except NoSuchElementException as exc:
        logging.error("[main] NoSuchElementException: %s", exc)
        return 3
    except KeyboardInterrupt:
        logging.warning("[main] 사용자 중단(Ctrl+C)")
        return 130
    except WebDriverException as exc:
        logging.error("[main] WebDriverException: %s", exc)
        return 4
    except Exception as exc:
        logging.exception("[main] Unexpected exception: %s", exc)
        return 9
    finally:
        if DRIVER:
            try:
                DRIVER.save_screenshot("debug_last.png")
                logging.info("[main] debug_last.png 저장 완료")
            except Exception as exc:
                logging.error("[main] 스크린샷 저장 실패: %s", exc)
            DRIVER.quit()


if __name__ == "__main__":
    sys.exit(main())
