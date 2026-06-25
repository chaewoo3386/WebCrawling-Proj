import sys
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
 
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, StaleElementReferenceException, NoSuchElementException
)
import requests
import time
import random
import pickle
import pandas as pd
import csv
import os
import threading
import re
import string
from concurrent.futures import ThreadPoolExecutor, as_completed
 
# =====================================================================
# 설정값
# =====================================================================
EMAIL = "Geddong0318@gmail.com"
PASSWORD = "aibo0318!!"
 
# 수집할 총 책 개수 (코멘트가 있는 책 기준 — 코멘트 없는 책은 카운트 안 됨)
MAX_BOOKS = 50000

# 시간 제한 (시간 단위)
TIME_LIMIT_HOURS = 168  # 7일
 
# 병렬 워커 수 — 같은 계정 쿠키 공유, rate limit 때문에 1이 안정적
N_WORKERS = 1
 
# API 호출 간 딜레이 (초) — 페이지 넘길 때마다
API_DELAY_MIN = 0.4
API_DELAY_MAX = 0.7
 
# 책 간 딜레이 (초)
BOOK_DELAY_MIN = 1.0
BOOK_DELAY_MAX = 2.0
 
# 책당 최대 코멘트 수 (0 = 무제한)
MAX_COMMENTS_PER_BOOK = 0

# 코멘트 수 최소 기준 — 이보다 적은 책은 메타 조회 1회로 바로 건너뜀 (0 = 비활성)
MIN_COMMENTS_PER_BOOK = 10
 
# 코멘트 품질 필터
MIN_COMMENT_LENGTH = 15        # 이 글자 수 미만은 제외 (NLP 학습 시 권장: 15~30)
MAX_COMMENT_LENGTH = 5000      # 비정상적으로 긴 것 제외
FILTER_URL_COMMENTS = True     # http/www 포함 코멘트 제외
FILTER_DATE_ONLY_COMMENTS = True  # "2026.5.2.토~" 같이 날짜만 적힌 메모성 제외
 
# 연속 요청 N개마다 선제적으로 쉬기 (429 방지)
RATE_LIMIT_BURST = 30       # N번 요청 후
RATE_LIMIT_REST  = 15.0     # 이만큼 쉼 (초)

# API 검색 소스 설정
API_SEARCH_PAGE_SIZE = 50   # 검색 1회 당 결과 수
API_SEARCH_MAX_PAGES = 100  # 키워드당 최대 페이지 (0 = 무제한)
 
# -----------------------------------------------------------------------
# 책 덱 URL 목록
# 카테고리 구분용 라벨(예: "소설", "에세이" 등)을 함께 적어두면 CSV에 함께 저장됨
# 사용자가 원하는 덱 URL을 추가/교체해서 쓰면 됨
# -----------------------------------------------------------------------
BOOK_DECK_SOURCES = [
    # (카테고리_라벨, 덱_URL, 설명)
    # ═══════════════════════════════════════════════
    # 확실한 책 덱들
    # ═══════════════════════════════════════════════
    ("일반",     "https://pedia.watcha.com/decks/gcd9qVAPmk",        "등록한 책 (눈에 띄는 도서 & 신간)"),
    ("일반",     "https://pedia.watcha.com/decks/gcdbYE1Gyb",        "2019 책 by 국밥이"),
    ("일반",     "https://pedia.watcha.com/decks/gcdNAVYEg9",        "짧은 책 by 배차"),
    ("일반",     "https://pedia.watcha.com/decks/gcdNxYXmp9",        "ISBN 등록한 책 (신간 위주)"),
    ("일반",     "https://pedia.watcha.com/decks/gcd9EX7JwN",        "ㅇ by 류우영 (책)"),
    ("일반",     "https://pedia.watcha.com/decks/gcdbYd7ajk",        "ㅇ by 지연김 (책)"),
    ("일반",     "https://pedia.watcha.com/decks/gcd9lx2LG9",        ". by 박현욱 (책)"),
    ("일반",     "https://pedia.watcha.com/decks/gcdNJQ71Bb",        "읽을거리 by karakku"),
    ("일반",     "https://pedia.watcha.com/decks/gcdN4xA8dN",        "책 모음 by 공동사용"),
    ("일반",     "https://pedia.watcha.com/en-US/decks/c5W2BSumNI2Y", "소장 서적 by 차정인"),
    ("일반",     "https://pedia.watcha.com/decks/gcdNje8O6b",        "일본소설 by 권규민"),
    ("일반",     "https://pedia.watcha.com/ko-KR/decks/M67GUbSih4WN", "책과 관련된 책"),
 
    # ─── 장르별 ───
    ("판타지",   "https://pedia.watcha.com/decks/gcdbZnYYzb",        "판타지 소설"),
    ("판타지",   "https://pedia.watcha.com/decks/gcdkXm1rmb",        "읽은 외국 판타지 소설"),
    ("판타지",   "https://pedia.watcha.com/decks/gcd982p05b",        "모노가타리 시리즈"),
    ("SF",       "https://pedia.watcha.com/decks/gcdNDgByEb",        "SF 명작소설 모음집"),
    ("소설",     "https://pedia.watcha.com/ko-KR/decks/gcd9grVGQN",  "정신 피폐해지는 소설"),
    ("소설",     "https://pedia.watcha.com/decks/gcd9rB1EM9",        "디스토피아 소설"),
 
    # ─── 추천 도서 ───
    ("추천도서", "https://pedia.watcha.com/ko-KR/decks/gcdbRZGDrb",  "아이유 추천 및 언급 도서"),
    ("추천도서", "https://pedia.watcha.com/ko-KR/decks/gcd9zYY5xN",  "북유럽 추천 도서 (KBS)"),
    ("추천도서", "https://pedia.watcha.com/ko-KR/decks/gcdNDY0el9",  "박찬욱 감독 추천 도서"),
    ("추천도서", "https://pedia.watcha.com/ko/decks/gcdNJKXL39",     "배우 홍경 추천 책"),
 
    # ─── 자기계발/에세이 ───
    ("자기계발", "https://pedia.watcha.com/ko-KR/decks/gcdNj0rVyk",  "자기계발/에세이"),
 
    # ═══════════════════════════════════════════════
    # 일반 컬렉션 — 영화/드라마 섞일 수 있지만 API 검증으로 책만 필터됨
    # ═══════════════════════════════════════════════
    ("컬렉션",   "https://pedia.watcha.com/decks/gcd9Mjxoyk",        "내 컬렉션 (21세기)"),
    ("컬렉션",   "https://pedia.watcha.com/decks/gcd9z0aVwb",        "컬렉션 by 임송이"),
    ("컬렉션",   "https://pedia.watcha.com/decks/gcdN1GM2Ok",        "컬렉션 생성 by 이호민"),
    ("컬렉션",   "https://pedia.watcha.com/decks/gcd9dxBnl9",        "컬렉션 by 이시은"),
    ("컬렉션",   "https://pedia.watcha.com/ko/decks/gcdkyY7lxk",     "WatchaPedia 컬렉션"),
    ("컬렉션",   "https://pedia.watcha.com/decks/gcdbpyR42N",        "추천 by Jong-gu Kim"),
    ("컬렉션",   "https://pedia.watcha.com/decks/gcdbRZaYKb",        "W. by 권혁"),
    ("컬렉션",   "https://pedia.watcha.com/decks/gcdbZlnxB9",        "베스트 작품 by 시네마천국"),
    ("컬렉션",   "https://pedia.watcha.com/decks/gcdbp4or3b",        "시리즈 by 김민서"),
    ("컬렉션",   "https://pedia.watcha.com/decks/gcdN403Z2N",        "역작 명작 대작"),
    ("컬렉션",   "https://pedia.watcha.com/ko-KR/decks/gcd9qV0egk",  "💯 by WatchaPedia"),
 
    # 만화/웹툰 컬렉션 — 책으로 분류된 그래픽노블 포함 가능성
    ("만화",     "https://pedia.watcha.com/ko-KR/decks/gcdkypjAq9",  "GL 만화&웹툰 컬렉션"),
    ("만화",     "https://pedia.watcha.com/decks/1yXpapphkVSe",      "만화 by 이재학"),
]
 
# 덱 URL이 부족하거나 비어있을 때, 책 도메인 페이지들을 fallback 으로 사용
# 메인/탐색 페이지는 카드 링크가 /contents/{code} 형태(book_* 접미사 없음)로
# 들어오므로, 아래 _load_all_from_deck 에서 API로 책 여부를 검증해 걸러냄.
BOOK_FALLBACK_URLS = [
    "https://pedia.watcha.com/ko?domain=book",
    "https://pedia.watcha.com/ko/explore?domain=book",
    "https://pedia.watcha.com/ko/browse/books",
    "https://pedia.watcha.com/ko/search?query=%EC%86%8C%EC%84%A4&domain=book",      # 소설
    "https://pedia.watcha.com/ko/search?query=%EC%97%90%EC%84%B8%EC%9D%B4&domain=book",  # 에세이
    "https://pedia.watcha.com/ko/search?query=%EC%9E%90%EA%B8%B0%EA%B3%84%EB%B0%9C&domain=book",  # 자기계발
    "https://pedia.watcha.com/ko/search?query=%EA%B2%BD%EC%A0%9C&domain=book",      # 경제
    "https://pedia.watcha.com/ko/search?query=%EC%97%AD%EC%82%AC&domain=book",      # 역사
    "https://pedia.watcha.com/ko/search?query=%EC%B2%A0%ED%95%99&domain=book",      # 철학
    "https://pedia.watcha.com/ko/search?query=%EA%B3%BC%ED%95%99&domain=book",      # 과학
    "https://pedia.watcha.com/ko/search?query=%EC%8B%9C&domain=book",                # 시
    "https://pedia.watcha.com/ko/search?query=%EB%A1%9C%EB%A7%8C%EC%8A%A4&domain=book",  # 로맨스
    "https://pedia.watcha.com/ko/search?query=%EC%B6%94%EB%A6%AC&domain=book",      # 추리
    "https://pedia.watcha.com/ko/search?query=SF&domain=book",                       # SF
    "https://pedia.watcha.com/ko/search?query=%EC%97%AC%ED%96%89&domain=book",      # 여행
    "https://pedia.watcha.com/ko/search?query=%EC%9A%94%EB%A6%AC&domain=book",      # 요리
    "https://pedia.watcha.com/ko/search?query=%EC%8B%AC%EB%A6%AC%ED%95%99&domain=book",  # 심리학
    "https://pedia.watcha.com/ko/search?query=%EC%98%88%EC%88%A0&domain=book",      # 예술
]
 
COOKIE_FILE = "watcha_session.pkl"
VISITED_FILE = "visited_book_urls.txt"
OUTPUT_FILE = "watcha_book_comments.csv"
 
# API 기본 URL
API_BASE = "https://pedia.watcha.com"
 
stop_flag = False
csv_lock = threading.Lock()
visited_lock = threading.Lock()
progress_lock = threading.Lock()
 
completed_count = 0
total_comment_count = 0
total_books_count = 0
crawl_start_time = 0
worker_status = {}
 
 
# =====================================================================
# 진행 현황 출력
# =====================================================================
def fmt_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
 
 
def print_progress():
    with progress_lock:
        elapsed = time.time() - crawl_start_time if crawl_start_time else 0
        total = total_books_count or 1
        done = completed_count
 
        eta_str = fmt_time((elapsed / done) * (total - done)) if done > 0 else "--:--:--"
        pct = done / total * 100
        bar_len = 28
        filled = int(bar_len * done / total)
        bar = "█" * filled + "░" * (bar_len - filled)
 
        lines = [
            "┌" + "─" * 53 + "┐",
            f"│  진행  [{bar}] {done}/{total} ({pct:.0f}%)  │",
            f"│  시간  경과 {fmt_time(elapsed)}  │  잔여 예상 {eta_str}  │",
            f"│  코멘트 누적 {total_comment_count:,}개{' ' * max(0, 36 - len(str(total_comment_count)))}│",
        ]
        for wid, status in sorted(worker_status.items()):
            line = f"│  W{wid}  {status}"
            lines.append(line[:55].ljust(55) + "│")
        lines.append("└" + "─" * 53 + "┘")
        print("\n" + "\n".join(lines))
 
 
# =====================================================================
# 엔터 키 중단
# =====================================================================
def listen_for_stop():
    global stop_flag
    try:
        input("\n[엔터 키를 누르면 수집을 중단합니다]\n")
        stop_flag = True
        print("\n중단 신호 감지! 현재 작업 완료 후 종료합니다...")
    except EOFError:
        pass  # 비대화형 환경(파이프/리다이렉션)에서는 무시
 
 
# =====================================================================
# 크롬 드라이버 초기화 (URL 수집 전용)
# =====================================================================
_ua_pool = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]
 
def init_driver(worker_id=0):
    options = webdriver.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(f"--user-agent={_ua_pool[worker_id % len(_ua_pool)]}")
    options.add_argument("--window-size=1366,900")
    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.managed_default_content_settings.fonts": 2,
        "profile.managed_default_content_settings.media_stream": 2,
    }
    options.add_experimental_option("prefs", prefs)
    driver = webdriver.Chrome(options=options)
    driver.implicitly_wait(3)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return driver
 
 
# =====================================================================
# 쿠키 저장 / 불러오기
# =====================================================================
def save_cookies(driver):
    pickle.dump(driver.get_cookies(), open(COOKIE_FILE, "wb"))
    print(f"쿠키 저장 완료 → {COOKIE_FILE}")
 
 
def load_cookies(driver):
    if not os.path.exists(COOKIE_FILE):
        return False
    driver.get("https://pedia.watcha.com/ko-KR")
    time.sleep(1.5)
    for cookie in pickle.load(open(COOKIE_FILE, "rb")):
        try:
            driver.add_cookie(cookie)
        except Exception:
            pass
    driver.refresh()
    time.sleep(2)
    return True
 
 
def is_logged_in(driver):
    try:
        driver.find_element(
            By.XPATH,
            "//a[contains(@href, '/ko/profile') or contains(@href, '/ko-KR/profile')]"
        )
        return True
    except NoSuchElementException:
        pass
    try:
        driver.find_element(By.XPATH, "//li[contains(@class,'SignIn') or .//a[contains(@href,'sign_in')]]")
        return False
    except NoSuchElementException:
        return True
 
 
def is_login_page(driver):
    url = driver.current_url
    return "sign_in" in url or "login" in url.lower()
 
 
# =====================================================================
# 로그인
# =====================================================================
def login(driver):
    print("로그인 중...")
    driver.get("https://pedia.watcha.com/ko-KR")
    time.sleep(2)
    try:
        login_btn = driver.find_element(
            By.XPATH, "/html/body/div[1]/header[1]/nav/section/ul/li[8]"
        )
        login_btn.click()
        time.sleep(1.5)
 
        email_login_btn = driver.find_element(
            By.XPATH, "/html/body/div[1]/main/div/div/section/div[1]/div[6]"
        )
        email_login_btn.click()
        time.sleep(1.5)
 
        driver.find_element(By.NAME, "email").send_keys(EMAIL)
        driver.find_element(By.XPATH, "//button[@type='submit']").click()
        time.sleep(1)
 
        driver.find_element(By.NAME, "password").send_keys(PASSWORD)
        driver.find_element(By.XPATH, "//button[@type='submit']").click()
        time.sleep(3)
 
        print("로그인 완료!")
        return True
    except Exception as e:
        print(f"로그인 실패: {e}")
        return False
 
 
# =====================================================================
# 방문 URL 관리
# =====================================================================
def load_visited_urls():
    if os.path.exists(VISITED_FILE):
        with open(VISITED_FILE, "r", encoding="utf-8") as f:
            return set(f.read().splitlines())
    return set()
 
 
def save_visited_url(url):
    with visited_lock:
        with open(VISITED_FILE, "a", encoding="utf-8") as f:
            f.write(url + "\n")
 
 
# =====================================================================
# CSV 저장 (스레드 안전)
# =====================================================================
def load_existing_data():
    if os.path.exists(OUTPUT_FILE) and os.path.getsize(OUTPUT_FILE) > 0:
        try:
            df = pd.read_csv(OUTPUT_FILE, encoding="utf-8-sig", escapechar="\\",
                             on_bad_lines="skip")
            print(f"기존 저장된 코멘트: {len(df):,}개")
            changed = False
 
            # ─── 1) 잘못된 제목 행 제거 ───
            # "제목 없음", 빈 문자열, NaN 등을 모두 제거
            if "book_title" in df.columns:
                before = len(df)
                # book_title을 문자열로 통일하고 양옆 공백 제거
                df["book_title"] = df["book_title"].astype(str).str.strip()
                # 잘못된 값들 제거
                invalid_titles = ("제목 없음", "제목없음", "", "nan", "None", "NaN")
                mask_valid = ~df["book_title"].isin(invalid_titles) & df["book_title"].notna()
                df = df[mask_valid].reset_index(drop=True)
                removed_bad = before - len(df)
                if removed_bad > 0:
                    print(f"  → 잘못된 제목 행 {removed_bad:,}개 제거 → {len(df):,}개")
                    changed = True
 
            # ─── 2) 중복 제거 ───
            if "book_title" in df.columns and "comment" in df.columns:
                before = len(df)
                df = df.drop_duplicates(
                    subset=["book_title", "comment"], keep="first"
                ).reset_index(drop=True)
                removed_dup = before - len(df)
                if removed_dup > 0:
                    print(f"  → 중복 {removed_dup:,}개 제거 → {len(df):,}개")
                    changed = True
 
            # 변경사항이 있으면 다시 저장
            if changed:
                df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig",
                          quoting=csv.QUOTE_ALL, escapechar="\\")
                print(f"  → CSV 정리 완료: {len(df):,}개")
 
            return df
        except Exception as e:
            print(f"CSV 읽기 실패 ({e}) — 새로 시작합니다")
    return pd.DataFrame()
 
 
def append_to_csv(new_rows):
    """CSV에 새 행 추가. mode='a'로 기존 데이터를 절대 덮어쓰지 않음."""
    with csv_lock:
        if not new_rows:
            return
        df_new = pd.DataFrame(new_rows)
        write_header = (not os.path.exists(OUTPUT_FILE)
                        or os.path.getsize(OUTPUT_FILE) == 0)
        df_new.to_csv(
            OUTPUT_FILE, mode="a", index=False, encoding="utf-8-sig",
            header=write_header, quoting=csv.QUOTE_ALL, escapechar="\\",
        )
 
 
# =====================================================================
# API 세션 (requests 기반, 코멘트 수집 전용)
# =====================================================================
def _gen_device_id():
    """브라우저가 생성하는 방식의 device identifier 생성."""
    chars = string.ascii_letters + string.digits
    rand = "".join(random.choices(chars, k=30))
    return f"web-{rand}"
 
 
def make_api_session(worker_id=0):
    """쿠키 + frograms 헤더가 설정된 requests.Session 반환."""
    session = requests.Session()
 
    if os.path.exists(COOKIE_FILE):
        for c in pickle.load(open(COOKIE_FILE, "rb")):
            session.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))
 
    session.headers.update({
        "accept": "application/vnd.frograms+json;version=2.1.0",
        "x-frograms-app-code": "Galaxy",
        "x-frograms-client": "Galaxy-Web-App",
        "x-frograms-client-version": "2.1.0",
        "x-frograms-device-identifier": _gen_device_id(),
        "x-frograms-galaxy-language": "ko",
        "x-frograms-version": "2.1.0",
        "User-Agent": _ua_pool[worker_id % len(_ua_pool)],
    })
    return session
 
 
def _extract_book_code(book_url):
    """
    URL에서 책 코드 추출.
    예) .../ko/contents/boglKdl/book_contents       → boglKdl
        .../ko/contents/boglKdl/book_description    → boglKdl
        .../ko/contents/boglKdl                     → boglKdl
    영화는 코드가 path 마지막이지만, 책은 보통 코드 뒤에
    'book_contents' 또는 'book_description'이 붙어있음.
    """
    parts = [p for p in book_url.rstrip("/").split("/") if p]
    # contents 다음에 오는 segment가 책 코드
    if "contents" in parts:
        idx = parts.index("contents")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    # fallback: 마지막 또는 끝에서 두 번째
    last = parts[-1]
    if last in ("book_contents", "book_description", "comments"):
        return parts[-2]
    return last
 
 
_book_meta_debugged = False  # 메타 응답 구조 한 번만 디버그 출력
 
 
# 날짜만 적힌 메모성 코멘트 패턴
# 예: "2026.5.2.토~", "23/04/15 ~ 23/05/01", "2024-12-31 완독"
_DATE_ONLY_RE = re.compile(
    r"^[\s\d\.\-\/\~()월일년주차완독시작끝~\[\]요\s월화수목금토일,:]+$"
)
 
# 한글/영문 글자 추출용 (실제 의미있는 문자 수 카운트)
_MEANINGFUL_CHAR_RE = re.compile(r"[가-힣a-zA-Z]")
 
 
def _is_quality_comment(text):
    """
    수집할 가치가 있는 코멘트인지 판별.
    True 면 통과, False 면 제외.
    """
    if not text:
        return False
 
    # 1) 길이 필터
    if len(text) < MIN_COMMENT_LENGTH:
        return False
    if len(text) > MAX_COMMENT_LENGTH:
        return False
 
    # 2) URL 포함 제외
    if FILTER_URL_COMMENTS:
        lower = text.lower()
        if "http" in lower or "www." in lower or ".com" in lower:
            return False
 
    # 3) 날짜/메모성 제외
    if FILTER_DATE_ONLY_COMMENTS and _DATE_ONLY_RE.match(text):
        return False
 
    # 4) 실제 의미있는 문자(한글/영문)가 너무 적으면 제외
    #    숫자나 기호만 잔뜩 있는 경우 거름
    meaningful = len(_MEANINGFUL_CHAR_RE.findall(text))
    if meaningful < MIN_COMMENT_LENGTH * 0.5:
        return False
 
    return True
 
 
def _extract_authors(result):
    """
    API 응답에서 작가/저자 정보를 추출.
    왓챠피디아 책 메타의 가능한 필드명을 폭넓게 시도.
    """
    # 1) 평면 필드들 우선
    flat_candidates = [
        result.get("authors"),
        result.get("author"),
        result.get("writer"),
        result.get("writers"),
        result.get("author_name"),
        result.get("author_names"),
        result.get("staff"),
    ]
 
    for cand in flat_candidates:
        if not cand:
            continue
        if isinstance(cand, str) and cand.strip():
            return cand.strip()
        if isinstance(cand, list) and cand:
            names = []
            for a in cand:
                if isinstance(a, dict):
                    # name, full_name, original_name 등
                    nm = (a.get("name") or a.get("full_name")
                          or a.get("original_name") or "")
                    if nm:
                        names.append(nm)
                elif a:
                    names.append(str(a))
            if names:
                return ", ".join(names)
 
    # 2) 중첩 구조 — 영화의 'people'/'credits' 같은 형태 대응
    for nested_key in ("people", "credits", "book_authors"):
        people = result.get(nested_key)
        if not people:
            continue
        if isinstance(people, list):
            names = []
            for p in people:
                if not isinstance(p, dict):
                    continue
                # 역할 키워드로 작가만 필터 (있으면)
                role = str(p.get("role") or p.get("type") or p.get("job") or "").lower()
                if role and not any(k in role for k in ("author", "writer", "글", "지음", "저")):
                    continue
                nm = (p.get("name") or p.get("full_name") or "")
                if nm:
                    names.append(nm)
            if names:
                return ", ".join(names)
 
    return ""
 
 
def get_book_title_api(session, book_code, worker_id=0):
    """
    API로 책 제목 + 출판연도 + 작가 조회.
    재시도 로직 포함:
      - 429 (rate limit) → 30초 후 재시도
      - 기타 오류/timeout → 5초 후 재시도
      - 최대 2회 재시도, 그래도 실패하면 None 반환
    반환:
      성공: (display_title, year_str, authors_str)
      실패: None  (호출자가 이 책을 건너뛸 수 있도록)
    """
    global _book_meta_debugged
 
    max_retries = 4
    for attempt in range(max_retries + 1):
        try:
            url = f"{API_BASE}/api/contents/{book_code}"
            r = session.get(
                url,
                headers={"Referer": f"{API_BASE}/ko/contents/{book_code}/book_contents"},
                timeout=10,
            )

            # 429 → 지수 대기 후 재시도 (최대 4회)
            if r.status_code == 429:
                if attempt < max_retries:
                    wait = 45 + random.uniform(0, 15) + attempt * 30
                    print(f"  [W{worker_id}] 메타 조회 429 → {wait:.0f}초 대기 후 재시도 ({attempt+1}/{max_retries})")
                    time.sleep(wait)
                    continue
                else:
                    print(f"  [W{worker_id}] 메타 조회 429 재시도 실패 → 건너뜀: {book_code}")
                    return None
 
            if r.status_code != 200:
                # 4xx (404 등) 은 재시도 의미 없음 — 즉시 None
                if 400 <= r.status_code < 500 and r.status_code != 429:
                    print(f"  [W{worker_id}] 메타 조회 {r.status_code} → 건너뜀: {book_code}")
                    return None
                # 5xx 등은 재시도
                if attempt < max_retries:
                    time.sleep(5 + attempt * 5)
                    continue
                else:
                    print(f"  [W{worker_id}] 메타 조회 {r.status_code} 재시도 실패 → 건너뜀: {book_code}")
                    return None
 
            # 정상 응답
            result = r.json().get("result", {})
 
            # 첫 호출 시 응답 키 목록을 한 번만 출력
            if not _book_meta_debugged:
                _book_meta_debugged = True
                print(f"  DEBUG 책 메타 응답 키: {list(result.keys())}")
 
            title = result.get("title", "").strip()

            # 제목이 빈 문자열이면 데이터 자체에 문제 있음 → 건너뜀
            if not title:
                print(f"  [W{worker_id}] 메타 응답에 제목 없음 → 건너뜀: {book_code}")
                return None

            year = (
                result.get("year")
                or result.get("published_year")
                or result.get("publication_year")
                or ""
            )
            authors = _extract_authors(result)
            # display_comments_count는 "20+" 같은 문자열일 수 있음 → "+" 제거 후 파싱
            _raw_cnt = result.get("display_comments_count") or result.get("comments_count") or 0
            try:
                comments_count = int(str(_raw_cnt).rstrip("+").strip() or 0)
            except (ValueError, TypeError):
                comments_count = 0

            display = f"{title} ({year})" if year else title
            _book_meta_cache[book_code] = result  # 중복 API 호출 방지
            return display, str(year), authors, comments_count, result
 
        except requests.exceptions.RequestException as e:
            # 네트워크 오류 — 재시도
            if attempt < max_retries:
                print(f"  [W{worker_id}] 메타 조회 네트워크 오류 → 5초 대기 후 재시도: {e}")
                time.sleep(5 + attempt * 5)
                continue
            else:
                print(f"  [W{worker_id}] 메타 조회 네트워크 오류 재시도 실패 → 건너뜀: {book_code}")
                return None
        except Exception as e:
            # 파싱 오류 등 — 재시도 의미 없음
            print(f"  [W{worker_id}] 메타 조회 예외 → 건너뜀: {book_code} ({e})")
            return None
 
    return None
 
 
def get_comments_via_api(session, book_url, worker_id=0, book_title=""):
    """
    API로 책 전체 코멘트 수집.
    반환: [{"book_title": ..., "comment": ..., "author": ...}, ...]
    """
    global _comment_struct_debug_done
    book_code = _extract_book_code(book_url)
    referer = f"{API_BASE}/ko/contents/{book_code}/comments"
 
    # 제목이 없으면 API로 한 번만 조회
    api_year = ""
    api_authors = ""
    if not book_title:
        title_result = get_book_title_api(session, book_code, worker_id)
        if title_result is None:
            # 메타 조회 실패 → 이 책은 건너뜀 (빈 리스트 반환)
            return []
        book_title, api_year, api_authors, book_comments_count, _ = title_result
        # 코멘트 수 최소 기준 미달 → 바로 건너뜀 (추가 API 호출 없음)
        if MIN_COMMENTS_PER_BOOK > 0 and book_comments_count < MIN_COMMENTS_PER_BOOK:
            print(f"  [W{worker_id}] {book_title} 코멘트 {book_comments_count}개 < {MIN_COMMENTS_PER_BOOK} → 건너뜀")
            return []
    title = book_title
    print(f"  [W{worker_id}] {title} 코멘트 수집 중...")
 
    comments = []
    # 영화와 동일한 comments API 엔드포인트 — 왓챠피디아는 영화/책/시리즈를
    # 모두 같은 'contents' 네임스페이스로 다루므로 같은 패턴이 동작함
    next_uri = f"/api/contents/{book_code}/comments?filter=all&order=popular&size=30"
    page = 0
    retry_count = 0
    req_count = 0          # 연속 요청 카운터 (선제적 속도 제한용)
 
    while next_uri and not stop_flag:
        # 최대 코멘트 도달 시 조기 종료
        if MAX_COMMENTS_PER_BOOK and len(comments) >= MAX_COMMENTS_PER_BOOK:
            break
 
        # 선제적 속도 제한: RATE_LIMIT_BURST번마다 미리 쉬어서 429 방지
        if req_count > 0 and req_count % RATE_LIMIT_BURST == 0:
            rest = RATE_LIMIT_REST + random.uniform(0, 5)
            print(f"  [W{worker_id}] 선제 대기 {rest:.0f}s (요청 {req_count}번 완료)")
            time.sleep(rest)
 
        url = API_BASE + next_uri
        if "size=" not in next_uri:
            url += "&size=30"
        try:
            r = session.get(url, headers={"Referer": referer}, timeout=15)
        except requests.exceptions.RequestException as e:
            print(f"  [W{worker_id}] 요청 오류: {e}")
            break
 
        if r.status_code == 429:
            retry_count += 1
            wait = min(30 * retry_count, 90) + random.uniform(0, 15)
            print(f"  [W{worker_id}] 429 → {wait:.0f}s 대기 (시도 {retry_count})")
            time.sleep(wait)
            req_count = 0   # 429 후 카운터 리셋
            continue
 
        retry_count = 0
        req_count += 1
 
        if r.status_code != 200:
            print(f"  [W{worker_id}] API 오류 {r.status_code} — 중단")
            break
 
        try:
            data = r.json()
            result = data["result"]
            page_comments = result.get("result", [])
            next_uri = result.get("next_uri")
        except Exception as e:
            print(f"  [W{worker_id}] 응답 파싱 오류: {e}")
            break
 
        # 첫 페이지에서 첫 책만 응답 구조 디버그 출력 (전역으로 한 번만)
        if page == 0 and page_comments and not _comment_struct_debug_done:
            _comment_struct_debug_done = True
            sample_keys = list(page_comments[0].keys())
            print(f"  [W{worker_id}] DEBUG 첫 코멘트 필드: {sample_keys}")
 
        for item in page_comments:
            # 책 코멘트의 텍스트 필드명이 영화와 다를 수 있음 → 여러 후보 시도
            text = (
                item.get("text")
                or item.get("content")
                or item.get("body")
                or ""
            ).strip()
            if not _is_quality_comment(text):
                continue
            comments.append({
                "book_title": title,
                "author": api_authors,
                "comment": text,
            })
 
        page += 1
        time.sleep(random.uniform(API_DELAY_MIN, API_DELAY_MAX))
 
    print(f"  [W{worker_id}] {title} — {len(comments)}개 ({page}페이지)")
    return comments
 
 
# =====================================================================
# 책 덱/카테고리 페이지에서 책 URL 수집 (Selenium)
# =====================================================================
def _is_contents_url(href):
    """
    href가 왓챠피디아 콘텐츠 페이지 URL인지 판별.
    영화/책/시리즈/웹툰 모두 /contents/{code} 형태이며,
    여기서는 일단 모든 contents URL을 통과시킨 뒤
    뒤에서 API로 책인지 확인함.
    """
    if not href:
        return False
    if "/contents/" not in href:
        return False
    # 외부 링크나 정적 자원 제외
    if any(x in href for x in (".jpg", ".png", ".webp", ".svg", "/api/")):
        return False
    return True
 
 
def _looks_like_book_code(code):
    """
    URL 패턴만으로 추정해보는 1차 필터.
    왓챠피디아 콘텐츠 코드 첫 글자 규칙(관찰값):
      영화:    m...
      시리즈:  t... (TV)
      책:      b...
      웹툰:    c... 또는 w... (정확하지 않음)
    확실히 책이 아닌 것만 빠르게 거르고, 애매하면 통과.
    """
    if not code or len(code) < 4:
        return False
    first = code[0].lower()
    # 명백히 영화/시리즈인 것만 제외
    if first in ("m", "t"):
        return False
    return True
 
 
# 책 여부 검증용 API 결과 캐시 (같은 코드 재조회 방지)
_book_check_cache = {}

# 책 메타 응답 캐시 — get_book_title_api 결과 저장 → get_related_book_codes/작가 검색 중복 호출 방지
_book_meta_cache = {}
 
 
# 확실히 책이 아닌 content_type 값들 (디버그로 확인된 실제 API 값)
_NON_BOOK_CONTENT_TYPES = {
    "movies", "movie",
    "tv_seasons", "tv_season", "tvseries", "tv",
    "dramas", "drama",
    "series", "episode", "episodes",
    "animations", "animation",
    "webtoons", "webtoon",
    "shows", "show",
}

_verify_debug_done = False
_comment_struct_debug_done = False


def _verify_is_book(session, code):
    """
    API로 해당 코드가 책 콘텐츠인지 확인.
    content_type 필드를 우선 사용하고, 없으면 책 특유 필드로 판단.
    """
    global _verify_debug_done

    if code in _book_check_cache:
        return _book_check_cache[code]

    try:
        url = f"{API_BASE}/api/contents/{code}"
        r = session.get(
            url,
            headers={"Referer": f"{API_BASE}/ko/contents/{code}/book_contents"},
            timeout=10,
        )
        if r.status_code != 200:
            _book_check_cache[code] = False
            return False

        result = r.json().get("result", {})
        if not isinstance(result, dict):
            _book_check_cache[code] = False
            return False

        ct = str(result.get("content_type", "")).lower().strip()

        # 디버그: 첫 5회는 content_type 출력
        if not _verify_debug_done:
            _verify_debug_done = True
            print(f"  [DEBUG] 첫 검증: code={code}, content_type={ct!r}, "
                  f"title={result.get('title', '')!r}")

        # content_type이 있으면 바로 판정
        if ct:
            if "book" in ct:
                _book_check_cache[code] = True
                return True
            if ct in _NON_BOOK_CONTENT_TYPES:
                _book_check_cache[code] = False
                return False
            # 알 수 없는 content_type → 아래 필드 검사로 fallback

        # content_type 없거나 알 수 없을 때: 책 특유 필드 확인
        book_fields = ("authors", "author", "writer", "isbn", "publisher",
                       "page_count", "pages", "published_year", "publication_year",
                       "book_type", "translator")
        if any(result.get(f) for f in book_fields):
            _book_check_cache[code] = True
            return True

        # 영화/TV 특유 필드가 있으면 제외
        # (director_names, credits, videos 등 실제 응답 키 사용)
        if result.get("director_names") or result.get("credits"):
            _book_check_cache[code] = False
            return False

        # 판단 불가 → 제목이 있으면 통과 (보수적 허용)
        has_title = bool(result.get("title", "").strip())
        _book_check_cache[code] = has_title
        return has_title

    except Exception:
        _book_check_cache[code] = False
        return False

 
 
def _normalize_book_url(code):
    """책 코드를 정식 book_contents 페이지 URL로 정규화."""
    return f"{API_BASE}/ko/contents/{code}/book_contents"
 
 
# 관련 책 첫 호출에서만 응답 구조 상세 디버그
_related_debug_count = 0
_related_debug_max = 3   # 첫 3개 책에 대해서만 상세 출력
 
 
def _extract_codes_from_obj(obj, codes_set, depth=0, max_depth=6):
    """
    임의의 JSON 객체에서 'code' 패턴의 문자열을 재귀적으로 추출.
    """
    if depth > max_depth or obj is None:
        return
    if isinstance(obj, dict):
        # 직접 'code' 키
        c = obj.get("code")
        if isinstance(c, str) and 4 <= len(c) <= 20:
            codes_set.add(c)
        # 중첩 탐색
        for v in obj.values():
            _extract_codes_from_obj(v, codes_set, depth + 1, max_depth)
    elif isinstance(obj, list):
        for item in obj:
            _extract_codes_from_obj(item, codes_set, depth + 1, max_depth)
 
 
def _try_endpoint(session, endpoint, book_code, debug=False, worker_id=0):
    """
    엔드포인트 하나 호출하고 (status_code, codes_set) 반환.
    debug=True면 상태와 응답 키를 자세히 출력.
    """
    try:
        url = API_BASE + endpoint
        r = session.get(
            url,
            headers={"Referer": f"{API_BASE}/ko/contents/{book_code}/book_contents"},
            timeout=10,
        )
        status = r.status_code
 
        if status != 200:
            if debug:
                print(f"  [W{worker_id}]   {endpoint} → {status}")
            return status, set()
 
        data = r.json()
        codes = set()
        _extract_codes_from_obj(data, codes)
        # 자기 자신 제거
        codes.discard(book_code)
 
        if debug:
            # 응답 구조 요약
            result = data.get("result") if isinstance(data, dict) else None
            if isinstance(result, dict):
                summary = f"dict, 키={list(result.keys())[:10]}"
            elif isinstance(result, list):
                summary = f"list, 길이={len(result)}"
            else:
                summary = type(result).__name__
            print(f"  [W{worker_id}]   {endpoint} → 200, result={summary}, 추출 코드={len(codes)}개")
 
        return status, codes
    except Exception as e:
        if debug:
            print(f"  [W{worker_id}]   {endpoint} → 예외: {e}")
        return -1, set()
 
 
# =====================================================================
# API 기반 책 검색 / 탐색 (Selenium 없이, 대규모 수집용)
# =====================================================================

_working_search_endpoint = None
_working_browse_endpoint = None

API_SEARCH_KEYWORDS = [
    "소설", "에세이", "시", "자기계발", "경제", "역사", "철학", "과학",
    "심리학", "사회", "예술", "음악", "여행", "요리", "건강",
    "추리", "SF", "로맨스", "판타지", "스릴러", "미스터리",
    "한국", "일본", "영미", "프랑스", "러시아",
    "사랑", "이별", "가족", "성장", "치유", "죽음", "전쟁",
    "청소년", "어린이", "육아",
    "베스트셀러", "독서", "노벨", "부커",
    "무라카미", "김훈", "박경리", "황석영", "김영하", "정유정",
    "도스토옙스키", "톨스토이", "헤밍웨이", "카프카", "카뮈",
    "단편", "장편", "산문", "수필", "회고록",
    "디스토피아", "사이버펑크", "공상과학",
    "연애", "우정", "고독", "인생", "위로", "용기",
    "경영", "투자", "재테크", "창업", "리더십",
    "심리", "정신건강", "감정", "관계",
    "철학자", "종교", "불교", "기독교",
    "물리학", "생물학", "수학", "인공지능", "우주",
    "세계사", "한국사", "근현대사", "고대사",
    "영어", "언어", "글쓰기", "독서법",
    "명작", "고전", "문학상", "추천",
]


def _try_api_search(session, url, worker_id=0):
    """API URL 한 번 호출. 반환: (codes: set, next_uri: str|None, status_code: int)"""
    try:
        r = session.get(url, timeout=15)
        if r.status_code == 429:
            wait = 60 + random.uniform(0, 20)
            print(f"  [W{worker_id}] API 검색 429 → {wait:.0f}s 대기")
            time.sleep(wait)
            r = session.get(url, timeout=15)
        if r.status_code != 200:
            return set(), None, r.status_code
        data = r.json()
        codes = set()
        _extract_codes_from_obj(data, codes)
        result = data.get("result", {})
        next_uri = result.get("next_uri") if isinstance(result, dict) else None
        return codes, next_uri, 200
    except Exception:
        return set(), None, -1


def api_search_books(session, keyword, next_uri=None, worker_id=0):
    """
    Watcha API 키워드 검색으로 책 코드 목록 반환.
    반환: (codes: set, next_uri: str|None)
    """
    global _working_search_endpoint

    if next_uri:
        codes, nxt, status = _try_api_search(session, API_BASE + next_uri, worker_id)
        return (codes, nxt) if status == 200 else (set(), None)

    encoded = requests.utils.quote(keyword)
    size = API_SEARCH_PAGE_SIZE
    candidates = [
        f"/api/search?query={encoded}&domain=book&size={size}",
        f"/api/search/contents?query={encoded}&domain=book&size={size}",
        f"/api/contents/search?query={encoded}&domain=book&size={size}",
        f"/api/search?q={encoded}&domain=book&size={size}",
        f"/api/search?query={encoded}&content_type=book&size={size}",
    ]

    if _working_search_endpoint:
        url = API_BASE + _working_search_endpoint.replace("{query}", encoded)
        codes, nxt, status = _try_api_search(session, url, worker_id)
        if status == 200 and codes:
            return codes, nxt

    for ep in candidates:
        codes, nxt, status = _try_api_search(session, API_BASE + ep, worker_id)
        if status == 200 and codes:
            _working_search_endpoint = ep.replace(encoded, "{query}")
            print(f"  [API 검색] 작동 엔드포인트: {_working_search_endpoint}")
            return codes, nxt
        time.sleep(0.2)

    return set(), None


def api_browse_books(session, order="popular", next_uri=None, worker_id=0):
    """
    Watcha API 탐색 (순위/최신 기반). 반환: (codes: set, next_uri: str|None)
    """
    global _working_browse_endpoint

    if next_uri:
        codes, nxt, status = _try_api_search(session, API_BASE + next_uri, worker_id)
        return (codes, nxt) if status == 200 else (set(), None)

    size = API_SEARCH_PAGE_SIZE
    candidates = [
        f"/api/contents?domain=book&order={order}&size={size}",
        f"/api/books?order={order}&size={size}",
        f"/api/contents/list?domain=book&order={order}&size={size}",
        f"/api/browse/books?order={order}&size={size}",
        f"/api/contents?content_type=book&order={order}&size={size}",
    ]

    if _working_browse_endpoint:
        url = API_BASE + _working_browse_endpoint.replace("{order}", order)
        codes, nxt, status = _try_api_search(session, url, worker_id)
        if status == 200 and codes:
            return codes, nxt

    for ep in candidates:
        codes, nxt, status = _try_api_search(session, API_BASE + ep, worker_id)
        if status == 200 and codes:
            _working_browse_endpoint = ep.replace(order, "{order}")
            print(f"  [API 탐색] 작동 엔드포인트: {_working_browse_endpoint}")
            return codes, nxt
        time.sleep(0.2)

    return set(), None


def api_get_author_books(session, author_code, worker_id=0):
    """특정 작가의 다른 책 코드들을 API로 조회. 반환: set of codes"""
    if not author_code:
        return set()
    candidates = [
        f"/api/contents?author_code={author_code}&domain=book",
        f"/api/authors/{author_code}/contents?domain=book",
        f"/api/people/{author_code}/contents?domain=book",
        f"/api/people/{author_code}/works?domain=book",
    ]
    for ep in candidates:
        codes, _, status = _try_api_search(session, API_BASE + ep, worker_id)
        if status == 200 and codes:
            return codes
        time.sleep(0.15)
    return set()


_working_deck_endpoint = None
_deck_api_debug_done = False


def _extract_codes_from_list(items):
    """덱 아이템 목록에서 코드 추출 + content_type 알고 있으면 _book_check_cache에 미리 저장.
    Watcha 덱 항목 구조: {"description": ..., "content": {"code": "b9JjXpw", "content_type": "books", ...}}
    """
    codes = set()
    if not isinstance(items, list):
        return codes
    for item in items:
        if not isinstance(item, dict):
            continue
        # 직접 code 필드 (content_type 없는 경우)
        c = item.get("code")
        ct_raw = item.get("content_type", "")
        if isinstance(c, str) and 4 <= len(c) <= 20:
            codes.add(c)
            ct = str(ct_raw).lower().strip() if ct_raw else ""
            if ct:
                if "book" in ct:
                    _book_check_cache[c] = True
                elif ct in _NON_BOOK_CONTENT_TYPES:
                    _book_check_cache[c] = False
        # 중첩 content/item/book 필드 (Watcha 덱 표준 구조)
        for sub_key in ("content", "item", "book", "subject"):
            sub = item.get(sub_key)
            if isinstance(sub, dict):
                c2 = sub.get("code")
                ct2_raw = sub.get("content_type", "")
                if isinstance(c2, str) and 4 <= len(c2) <= 20:
                    codes.add(c2)
                    ct2 = str(ct2_raw).lower().strip() if ct2_raw else ""
                    if ct2:
                        if "book" in ct2:
                            _book_check_cache[c2] = True
                        elif ct2 in _NON_BOOK_CONTENT_TYPES:
                            _book_check_cache[c2] = False
    return codes


def _fetch_deck_page(session, url):
    """덱 API 단일 페이지 조회. 반환: (items_list, next_uri) or (None, None)"""
    try:
        r = session.get(url, timeout=12)
        if r.status_code == 429:
            time.sleep(65)
            r = session.get(url, timeout=12)
        if r.status_code != 200:
            return None, None
        data = r.json()
        result = data.get("result", {}) if isinstance(data, dict) else {}
        if not isinstance(result, dict):
            return None, None
        return result, None  # caller extracts items depending on page type
    except Exception:
        return None, None


def api_get_deck_contents(session, deck_url, worker_id=0, max_items=1000):
    """
    왓챠 덱 URL에서 실제 덱 아이템 코드 전체 수집 (페이지네이션 포함).
    구조: /api/decks/{code} → result.items.result (9개) + result.items.next_uri
          /api/decks/{code}/items?page=N → result.result (N개) + result.next_uri
    반환: set of codes (비어있으면 Selenium fallback 필요)
    """
    global _working_deck_endpoint

    parts = [p for p in deck_url.rstrip("/").split("/") if p]
    deck_code = parts[-1]
    if not deck_code or len(deck_code) < 5:
        return set()

    # 1) 첫 페이지: /api/decks/{code}
    first_url = API_BASE + f"/api/decks/{deck_code}"
    try:
        r = session.get(first_url, timeout=12)
        if r.status_code == 429:
            time.sleep(65)
            r = session.get(first_url, timeout=12)
        if r.status_code != 200:
            return set()
        data = r.json()
        result = data.get("result", {}) if isinstance(data, dict) else {}
        if not isinstance(result, dict):
            return set()
    except Exception:
        return set()

    # items는 페이지네이션 객체: {"prev_uri":..., "next_uri":..., "result": [...]}
    items_page = result.get("items")
    if not isinstance(items_page, dict):
        return set()

    first_items = items_page.get("result", [])
    if not isinstance(first_items, list):
        return set()

    all_codes = _extract_codes_from_list(first_items)
    if all_codes:
        if _working_deck_endpoint != "/api/decks/{code}":
            _working_deck_endpoint = "/api/decks/{code}"
            print(f"    [덱 API] 작동 엔드포인트: /api/decks/{{code}} (items.result 구조)")

    # 2) 페이지네이션: next_uri 추적
    next_uri = items_page.get("next_uri")
    page_count = 1
    while next_uri and len(all_codes) < max_items:
        try:
            # size를 100으로 키워서 더 빠르게 수집
            page_url = API_BASE + next_uri
            if "size=" in next_uri:
                page_url = re.sub(r"size=\d+", "size=100", page_url)
            r2 = session.get(page_url, timeout=12)
            if r2.status_code == 429:
                time.sleep(65)
                r2 = session.get(page_url, timeout=12)
            if r2.status_code != 200:
                break
            d2 = r2.json()
            res2 = d2.get("result", {}) if isinstance(d2, dict) else {}
            if not isinstance(res2, dict):
                break
            page_items = res2.get("result", [])
            if not isinstance(page_items, list) or not page_items:
                break
            all_codes |= _extract_codes_from_list(page_items)
            next_uri = res2.get("next_uri")
            page_count += 1
            time.sleep(0.2)
        except Exception:
            break

    if all_codes and page_count > 1:
        print(f"    [덱 API] {page_count}페이지, 총 {len(all_codes)}개 코드 수집")

    return all_codes


def get_related_book_codes(session, book_code, worker_id=0):
    """
    한 책의 '관련 책' 코드들을 API로 조회.
    여러 endpoint 후보를 광범위하게 시도하고, 처음 몇 번은 상세 디버그 출력.
    반환: set of codes (검증 전)
    """
    global _related_debug_count
    debug = _related_debug_count < _related_debug_max
    if debug:
        _related_debug_count += 1
        print(f"\n  [W{worker_id}] ━━━ 관련 책 탐색: {book_code} ━━━")
 
    all_codes = set()

    # ─── Endpoint 후보 ───
    # 왓챠 책 API: 개별 endpoint는 모두 404, similars는 메인 응답에서 처리
    endpoint_candidates = []
 
    successful_endpoints = []
    for endpoint in endpoint_candidates:
        status, codes = _try_endpoint(session, endpoint, book_code, debug=debug, worker_id=worker_id)
        if status == 200 and codes:
            successful_endpoints.append((endpoint, len(codes)))
            all_codes.update(codes)
        # rate limit 보호
        time.sleep(random.uniform(0.1, 0.2))
 
    # ─── 메인 콘텐츠 API의 응답에서도 추출 (캐시 우선) ───
    main_codes = set()
    try:
        result = _book_meta_cache.get(book_code)
        if result is None:
            url = f"{API_BASE}/api/contents/{book_code}"
            r = session.get(
                url,
                headers={"Referer": f"{API_BASE}/ko/contents/{book_code}/book_contents"},
                timeout=10,
            )
            if r.status_code == 200:
                result = r.json().get("result", {})
                _book_meta_cache[book_code] = result
        if result is not None:
 
            if debug:
                # 메인 응답의 모든 키 출력 (어디에 관련 책이 있는지 찾기 위해)
                all_keys = list(result.keys()) if isinstance(result, dict) else []
                print(f"  [W{worker_id}]   /api/contents/{book_code} → 메인 응답 전체 키:")
                print(f"       {all_keys}")
 
            # 관련 책이 들어있을 가능성 있는 모든 키 탐색
            # similars: 왓챠 책 API에 있는 유사 콘텐츠 (페이지네이션 dict)
            for key in ("similars", "related_contents", "similar_contents", "recommendations",
                        "related", "similar", "associated_decks",
                        "author_contents", "series_contents",
                        "users_also_liked", "connections", "more_contents",
                        "related_works", "recommended_contents"):
                if key in result:
                    if debug:
                        print(f"  [W{worker_id}]   ✓ 메인 응답에서 '{key}' 키 발견")
                    raw_val = result[key]
                    # Watcha 페이지네이션 패턴: {"prev_uri":..., "next_uri":..., "result":[...]}
                    if isinstance(raw_val, dict) and "result" in raw_val:
                        items = raw_val["result"]
                        if isinstance(items, list):
                            main_codes |= _extract_codes_from_list(items)
                    else:
                        _extract_codes_from_obj(raw_val, main_codes)
 
            main_codes.discard(book_code)
            all_codes.update(main_codes)
    except Exception as e:
        if debug:
            print(f"  [W{worker_id}]   메인 응답 처리 오류: {e}")
 
    if debug:
        print(f"  [W{worker_id}] ━━━ 결과: 작동 endpoint {len(successful_endpoints)}개, "
              f"메인 응답 추가 {len(main_codes)}개, 총 코드 {len(all_codes)}개 ━━━")
        for ep, cnt in successful_endpoints:
            print(f"       ✓ {ep}: {cnt}개")
        if not all_codes and _related_debug_count >= _related_debug_max:
            print(f"  [W{worker_id}] (이후 책은 디버그 생략)")
 
    return all_codes
 
 
def _load_all_from_deck(driver, deck_url, wanted, already_collected, visited_urls,
                        verify_session=None):
    print(f"    덱 페이지 접속: {deck_url}")
    driver.get(deck_url)
    time.sleep(2.5)
 
    if is_login_page(driver):
        print(f"    로그인 페이지 리다이렉트 → 세션 만료")
        return []
 
    # 무한 스크롤 + 더보기 버튼 — 책 페이지도 영화와 동일한 패턴 사용
    click_count = 0
    last_height = driver.execute_script("return document.body.scrollHeight")
    scroll_idle = 0
 
    while True:
        # 1) 더보기 버튼이 보이면 클릭
        more_btn = None
        try:
            candidates = driver.find_elements(
                By.XPATH,
                "//button[contains(text(),'더보기') or contains(text(),'더 보기')]"
                " | //a[contains(text(),'더보기') or contains(text(),'더 보기')]"
            )
            for c in candidates:
                if c.is_displayed() and c.is_enabled():
                    more_btn = c
                    break
        except Exception:
            pass
 
        if more_btn is not None:
            try:
                driver.execute_script("arguments[0].scrollIntoView(true);", more_btn)
                time.sleep(0.3)
                driver.execute_script("arguments[0].click();", more_btn)
                click_count += 1
                time.sleep(1.2)
                continue
            except Exception:
                pass
 
        # 2) 더보기가 없으면 스크롤로 lazy-load 트리거
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.0)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            scroll_idle += 1
            if scroll_idle >= 3:
                break
        else:
            scroll_idle = 0
            last_height = new_height
 
        if click_count > 50:
            break
 
    if click_count > 0:
        print(f"    더보기 {click_count}회 클릭 → 전체 로드 완료")
 
    # =========================================================
    # 1단계: 페이지에서 모든 /contents/ 링크 수집
    # =========================================================
    candidate_pairs = []   # [(code, normalized_url, title)]
    all_taken = set(visited_urls) | set(already_collected)
    seen_codes = set()
    raw_link_count = 0
    book_url_hint_count = 0
 
    try:
        links = driver.find_elements(By.XPATH, "//a[contains(@href, '/contents/')]")
        for link in links:
            try:
                href = link.get_attribute("href")
            except StaleElementReferenceException:
                continue
            if not _is_contents_url(href):
                continue
            raw_link_count += 1
 
            # URL에 책 힌트가 있으면 별도 카운트 (확실한 책)
            href_has_book_hint = ("book_contents" in href or "book_description" in href)
            if href_has_book_hint:
                book_url_hint_count += 1
 
            code = _extract_book_code(href)
            if not code or code in seen_codes:
                continue
 
            # 1차 필터: 명백히 책이 아닌 코드만 제외 (book_hint 없으면 API로 검증)
            # _looks_like_book_code 대신 모든 코드를 후보로 넣고 API 검증에서 걸러냄
            if not code or len(code) < 4:
                continue
 
            seen_codes.add(code)
            normalized = _normalize_book_url(code)
            if normalized in all_taken:
                continue
 
            try:
                title = link.text.strip().split("\n")[0] or ""
            except Exception:
                title = ""
 
            candidate_pairs.append((code, normalized, title, href_has_book_hint))
    except Exception as e:
        print(f"    링크 추출 오류: {e}")
 
    print(f"    /contents/ 링크 {raw_link_count}개 발견 "
          f"(URL에 book 힌트 있음 {book_url_hint_count}개, 1차 필터 통과 {len(candidate_pairs)}개)")
 
    # =========================================================
    # 2단계: API로 책 여부 확정 (URL 힌트가 있는 건 검증 생략)
    # =========================================================
    url_title_pairs = []
    api_checked = 0
    api_confirmed = 0
 
    for code, normalized, title, has_hint in candidate_pairs:
        if len(url_title_pairs) >= wanted:
            break
 
        if has_hint:
            # 이미 URL에 book_contents/book_description 이 있으면 확실히 책
            url_title_pairs.append((normalized, title))
            continue
 
        # URL 힌트가 없는 후보는 API로 검증
        if verify_session is None:
            # 검증 세션이 없으면 패턴만으로 통과시킴 (best-effort)
            url_title_pairs.append((normalized, title))
            continue
 
        api_checked += 1
        if _verify_is_book(verify_session, code):
            api_confirmed += 1
            url_title_pairs.append((normalized, title))
        # API rate limit 보호: 검증 호출 사이에 짧은 딜레이
        time.sleep(random.uniform(0.15, 0.3))
 
    if api_checked > 0:
        print(f"    API 검증: {api_checked}개 중 {api_confirmed}개 책 확인")
    print(f"    최종 {len(url_title_pairs)}개 책 URL 추출")
    return url_title_pairs
 
 
class BookUrlPool:
    """
    책 URL을 풀(pool)에 쌓아두고 필요할 때마다 꺼내 쓰는 매니저.
    소스 타입:
      - "deck"       : Selenium으로 왓챠 덱 페이지 스크롤
      - "fallback"   : Selenium으로 검색/탐색 페이지 스크롤
      - "api_search" : Watcha API 검색 (키워드 + next_uri 페이지네이션)
      - "api_browse" : Watcha API 탐색 (순위/최신 + next_uri 페이지네이션)
    스레드 안전.
    """

    def __init__(self, driver, visited_urls):
        self.driver = driver
        self.visited_urls = visited_urls
        self.verify_session = make_api_session(worker_id=0)

        self.pool = []
        self.already = set()
        self._lock = threading.RLock()  # RLock: prefetch/next_url + _codes_to_pool 둘다 획득
        self._driver_lock = threading.Lock()

        self.source_queue = []

        # 1) Selenium 덱 소스 — 실제 동작 확인된 방식
        for category, deck_url, desc in BOOK_DECK_SOURCES:
            self.source_queue.append(("deck", category, deck_url, desc))

        # 2) Selenium 검색/탐색 fallback
        for fb_url in BOOK_FALLBACK_URLS:
            self.source_queue.append(("fallback", "기타", fb_url, fb_url))

        # 3) API 검색 소스 — Selenium 이후 보조 수단
        for kw in API_SEARCH_KEYWORDS:
            self.source_queue.append((
                "api_search", "API검색",
                {"keyword": kw, "next_uri": None, "page": 1},
                f"API 검색: {kw}",
            ))

        # 4) API 탐색 소스
        for order in ["popular", "new", "rating"]:
            self.source_queue.append((
                "api_browse", "API탐색",
                {"order": order, "next_uri": None},
                f"API 탐색: {order}",
            ))

        self.related_added_total = 0
        self.related_verified_total = 0

    def _codes_to_pool(self, codes, category):
        """코드 집합을 API 검증 후 풀에 추가. 추가 개수 반환."""
        added = 0
        for code in codes:
            if not code or len(code) < 4:
                continue
            normalized = _normalize_book_url(code)
            if normalized in self.already or normalized in self.visited_urls:
                continue
            was_cached = code in _book_check_cache
            if not _verify_is_book(self.verify_session, code):
                if not was_cached:
                    time.sleep(0.1)  # API 호출 후에만 딜레이
                continue
            with self._lock:
                if normalized in self.already:
                    continue
                self.pool.append((normalized, category, ""))
                self.already.add(normalized)
                added += 1
            if not was_cached:
                time.sleep(0.12)  # API 호출 후에만 rate-limit 딜레이
        return added

    def add_related_books(self, source_code, related_codes, source_category="관련"):
        """한 책에서 나온 관련 책 코드들을 검증해서 풀에 추가."""
        if not related_codes:
            return 0
        added = self._codes_to_pool(related_codes, source_category)
        if added > 0:
            self.related_added_total += added
            print(f"  [관련 책] {source_code} → {len(related_codes)}개 후보, "
                  f"{added}개 추가 (누적: {self.related_added_total})")
        return added

    def add_author_books(self, author_code, related_codes):
        """작가의 다른 책 코드들을 풀에 추가."""
        if not related_codes:
            return 0
        added = self._codes_to_pool(related_codes, "작가")
        if added > 0:
            print(f"  [작가 책] {author_code} → {added}개 추가")
        return added

    def _consume_one_source(self, want=200):
        """소스 큐에서 하나 꺼내 풀에 추가. 추가된 개수 반환."""
        if not self.source_queue:
            return 0
        kind, category, payload, desc = self.source_queue.pop(0)

        if kind in ("deck", "fallback"):
            tag = "Deck" if kind == "deck" else "Fallback"
            print(f"\n  [{tag}|{category}] {desc}")

            # 덱 소스는 API로 먼저 시도 (빠르고 정확함)
            if kind == "deck":
                deck_codes = api_get_deck_contents(self.verify_session, payload, worker_id=0)
                if deck_codes:
                    added = self._codes_to_pool(deck_codes, category)
                    print(f"    → [API] {len(deck_codes)}개 후보, {added}개 추가 "
                          f"(풀 크기: {len(self.pool)}, 남은 소스: {len(self.source_queue)}개)")
                    return added
                # API 실패 시 Selenium으로 fallback
                print(f"    → 덱 API 없음, Selenium으로 전환")

            with self._driver_lock:
                pairs = _load_all_from_deck(
                    self.driver, payload, want,
                    list(self.already), self.visited_urls,
                    verify_session=self.verify_session,
                )
            added = 0
            for url, title in pairs:
                if url in self.already or url in self.visited_urls:
                    continue
                with self._lock:
                    self.pool.append((url, category, title))
                    self.already.add(url)
                added += 1
            print(f"    → 풀에 {added}개 추가 (풀 크기: {len(self.pool)}, "
                  f"남은 소스: {len(self.source_queue)}개)")
            return added

        elif kind == "api_search":
            keyword = payload["keyword"]
            next_uri = payload["next_uri"]
            page = payload["page"]
            if API_SEARCH_MAX_PAGES and page > API_SEARCH_MAX_PAGES:
                return 0
            print(f"\n  [API검색] \"{keyword}\" 페이지 {page}")
            codes, new_next = api_search_books(
                self.verify_session, keyword, next_uri=next_uri, worker_id=0
            )
            added = self._codes_to_pool(codes, f"검색:{keyword[:6]}")
            if new_next:
                self.source_queue.insert(0, (
                    "api_search", "API검색",
                    {"keyword": keyword, "next_uri": new_next, "page": page + 1},
                    f"API 검색: {keyword} (p{page + 1})",
                ))
            print(f"    → {len(codes)}개 후보, {added}개 추가 "
                  f"(남은 소스: {len(self.source_queue)}개)")
            return added

        elif kind == "api_browse":
            order = payload["order"]
            next_uri = payload["next_uri"]
            print(f"\n  [API탐색] order={order}")
            codes, new_next = api_browse_books(
                self.verify_session, order=order, next_uri=next_uri, worker_id=0
            )
            added = self._codes_to_pool(codes, f"탐색:{order}")
            if new_next:
                self.source_queue.insert(0, (
                    "api_browse", "API탐색",
                    {"order": order, "next_uri": new_next},
                    f"API 탐색: {order} (계속)",
                ))
            print(f"    → {len(codes)}개 후보, {added}개 추가 "
                  f"(남은 소스: {len(self.source_queue)}개)")
            return added

        return 0

    def next_url(self):
        """풀에서 다음 URL 1개 반환. 없으면 소스에서 보충. 그래도 없으면 None."""
        with self._lock:
            while not self.pool and self.source_queue:
                self._consume_one_source()
            if not self.pool:
                return None
            return self.pool.pop(0)

    def prefetch(self, count):
        """풀에 최소 count개가 있도록 미리 채움."""
        with self._lock:
            while len(self.pool) < count and self.source_queue:
                self._consume_one_source(want=max(count, 100))

    def has_more(self):
        with self._lock:
            return bool(self.pool) or bool(self.source_queue)
 
 
def get_book_url_pool(driver, visited_urls):
    """URL 풀 매니저 반환 — 시작 시 일부 미리 로드."""
    print(f"\n책 URL 풀 초기화")
    pool = BookUrlPool(driver, visited_urls)
    # 시작 시 최소 5개는 확보 (너무 많이 선로딩하면 시간 낭비)
    pool.prefetch(5)
    return pool
 
 
# =====================================================================
# 워커 함수 (requests API 기반)
# =====================================================================
def _set_worker_status(worker_id, status):
    worker_status[worker_id] = status
 
 
def worker_run(url_pool, worker_id, start_time, time_limit_seconds, target_books):
    """
    URL 풀에서 책을 한 권씩 꺼내 처리.
    코멘트 0개면 건너뛰고 다음 책을 가져옴 — 'target_books 권 채우기' 까지 반복.
    """
    global completed_count, total_comment_count

    # 워커 시작 시점 분산 (동시 burst 방지)
    time.sleep(worker_id * 3)

    session = make_api_session(worker_id)
    _set_worker_status(worker_id, "준비 완료")

    attempted = 0
    succeeded = 0
    skipped_no_comment = 0
    consecutive_empty = 0   # 연속으로 코멘트 0 또는 API 실패한 횟수 (세션 만료 감지용)
 
    while True:
        if stop_flag:
            break
        if time.time() - start_time >= time_limit_seconds:
            _set_worker_status(worker_id, "시간 제한 도달")
            break
 
        # 목표 달성 시 종료
        with progress_lock:
            if completed_count >= target_books:
                _set_worker_status(worker_id, "목표 달성")
                break
 
        # 풀에서 다음 URL — 더 없으면 종료
        entry = url_pool.next_url()
        if entry is None:
            print(f"  [W{worker_id}] 모든 소스 소진 — 종료 "
                  f"(시도 {attempted}, 성공 {succeeded}, 건너뜀 {skipped_no_comment})")
            _set_worker_status(worker_id, "소스 소진")
            break
 
        url, category, deck_title = entry
        attempted += 1
 
        label = deck_title or _extract_book_code(url)
        # 진행 라벨에는 "현재 완료 / 목표" 를 표시
        with progress_lock:
            done_now = completed_count
        _set_worker_status(worker_id,
                           f"[{done_now}/{target_books}] {label[:20]} (시도 {attempted})")
 
        comments = get_comments_via_api(session, url, worker_id, book_title=deck_title)
 
        if comments:
            for c in comments:
                c["category"] = category
            append_to_csv(comments)
            save_visited_url(url)
 
            with progress_lock:
                completed_count += 1
                total_comment_count += len(comments)
 
            succeeded += 1
            title_short = comments[0]["book_title"][:20]
            _set_worker_status(
                worker_id,
                f"[{completed_count}/{target_books}] ✓ {title_short} ({len(comments)}개)"
            )
            print_progress()
 
            # ─── 관련 책 & 작가 책 발견 ───
            with progress_lock:
                done_now = completed_count
                need_more = (target_books - done_now)
            if need_more > 0:
                book_code = _extract_book_code(url)
                # 관련 책 (기존 방식)
                try:
                    related = get_related_book_codes(session, book_code, worker_id)
                    if related:
                        url_pool.add_related_books(
                            book_code, related, source_category="관련"
                        )
                except Exception as e:
                    print(f"  [W{worker_id}] 관련 책 조회 실패: {e}")
                # 작가의 다른 책 발견 — 캐시에서 메타 읽기 (중복 API 호출 방지)
                try:
                    result_meta = _book_meta_cache.get(book_code)
                    if result_meta is None:
                        meta = get_book_title_api(session, book_code, worker_id)
                        result_meta = meta[4] if meta else None
                    if result_meta:
                        author_codes = set()
                        for key in ("authors", "author", "people", "credits"):
                            people = result_meta.get(key)
                            if isinstance(people, list):
                                for p in people:
                                    if isinstance(p, dict):
                                        c = p.get("code") or p.get("id")
                                        if c:
                                            author_codes.add(str(c))
                        for ac in author_codes:
                            author_book_codes = api_get_author_books(
                                session, ac, worker_id
                            )
                            if author_book_codes:
                                url_pool.add_author_books(ac, author_book_codes)
                except Exception as e:
                    print(f"  [W{worker_id}] 작가 책 조회 실패: {e}")
        else:
            # 코멘트 0개 — completed_count 증가시키지 않고 건너뜀
            skipped_no_comment += 1
            consecutive_empty += 1
            save_visited_url(url)
            _set_worker_status(
                worker_id,
                f"[{done_now}/{target_books}] ✗ {label[:20]} 코멘트 없음 (건너뜀 {skipped_no_comment})"
            )

            # 연속 20회 코멘트 없음 → 세션 만료 가능성, 쿠키 갱신 시도
            if consecutive_empty >= 20:
                print(f"  [W{worker_id}] 연속 {consecutive_empty}회 빈 응답 → 세션 갱신 시도")
                session = make_api_session(worker_id)
                consecutive_empty = 0
                time.sleep(10)

            time.sleep(random.uniform(0.3, 0.6))
            continue

        consecutive_empty = 0
        time.sleep(random.uniform(BOOK_DELAY_MIN, BOOK_DELAY_MAX))
 
    _set_worker_status(worker_id, "완료")
    print(f"\n[W{worker_id}] 최종: 시도 {attempted}권, 성공 {succeeded}권, "
          f"코멘트 없어 건너뜀 {skipped_no_comment}권")
 
 
# =====================================================================
# 주기적 현황 출력 스레드
# =====================================================================
def periodic_status_printer():
    while not stop_flag:
        time.sleep(60)
        if not stop_flag and completed_count < total_books_count:
            print_progress()
 
 
# =====================================================================
# 메인
# =====================================================================
def main():
    global stop_flag, total_books_count, crawl_start_time, total_comment_count
 
    threading.Thread(target=listen_for_stop, daemon=True).start()
    threading.Thread(target=periodic_status_printer, daemon=True).start()
 
    crawl_start_time = time.time()
    start_time = crawl_start_time
    time_limit_seconds = TIME_LIMIT_HOURS * 3600
 
    existing = load_existing_data()
    if not existing.empty and "comment" in existing.columns:
        total_comment_count = len(existing)
 
    visited_urls = load_visited_urls()
    print(f"이미 수집한 책: {len(visited_urls)}개")
 
    # 진행률 표시 기준
    total_books_count = MAX_BOOKS
 
    # Selenium은 URL 수집에만 사용 (풀이 lazy하게 driver를 호출함)
    main_driver = init_driver(worker_id=0)
 
    try:
        if os.path.exists(COOKIE_FILE):
            if load_cookies(main_driver) and is_logged_in(main_driver):
                print("쿠키로 로그인 완료!")
            else:
                if not login(main_driver):
                    print("로그인 실패")
                    return
                save_cookies(main_driver)
        else:
            if not login(main_driver):
                print("로그인 실패")
                return
            save_cookies(main_driver)
 
        # URL 풀 초기화 — driver는 풀이 lazy하게 사용
        url_pool = get_book_url_pool(main_driver, visited_urls)
 
        if not url_pool.has_more():
            print("수집할 책이 없습니다.")
            return
 
        print(f"\n목표: 코멘트가 있는 책 {MAX_BOOKS}권 수집")
        print(f"{'─'*55}")
        print_progress()
        print()
 
        # 워커들은 풀에서 URL을 꺼내 처리 (목표 달성 또는 소스 소진 시 종료)
        with ThreadPoolExecutor(max_workers=N_WORKERS) as executor:
            futures = [
                executor.submit(
                    worker_run, url_pool, wid, start_time, time_limit_seconds, MAX_BOOKS
                )
                for wid in range(N_WORKERS)
            ]
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception as e:
                    print(f"워커 오류: {e}")
 
        # 관련 책(A 방식) 통계
        if hasattr(url_pool, "related_added_total"):
            print(f"\n[A 방식 통계] 관련 책에서 풀에 추가된 권수: "
                  f"{url_pool.related_added_total}권")
 
    except Exception as e:
        print(f"\n오류 발생: {e}")
    finally:
        try:
            main_driver.quit()
        except Exception:
            pass
 
    if os.path.exists(OUTPUT_FILE):
        df = pd.read_csv(OUTPUT_FILE, encoding="utf-8-sig", escapechar="\\")
        before = len(df)
        print(f"\n수집 완료! 총 {before:,}개 코멘트 → '{OUTPUT_FILE}'")
 
        changed = False
 
        # ============================================
        # 1) 잘못된 제목 행 제거 ("제목 없음", 빈 제목 등)
        # ============================================
        if "book_title" in df.columns:
            before_bad = len(df)
            df["book_title"] = df["book_title"].astype(str).str.strip()
            invalid_titles = ("제목 없음", "제목없음", "", "nan", "None", "NaN")
            mask_valid = ~df["book_title"].isin(invalid_titles) & df["book_title"].notna()
            df = df[mask_valid].reset_index(drop=True)
            removed_bad = before_bad - len(df)
            if removed_bad > 0:
                print(f"잘못된 제목 제거: {removed_bad:,}개 행 제거 → {len(df):,}개")
                changed = True
 
        # ============================================
        # 2) 중복 제거: 같은 책 + 같은 코멘트는 1개만 유지
        # ============================================
        if "book_title" in df.columns and "comment" in df.columns:
            before_dup = len(df)
            df = df.drop_duplicates(
                subset=["book_title", "comment"], keep="first"
            ).reset_index(drop=True)
            removed_dup = before_dup - len(df)
            if removed_dup > 0:
                print(f"중복 제거: {removed_dup:,}개 행 제거 → 최종 {len(df):,}개")
                changed = True
            elif removed_bad == 0:
                print("중복 없음 — 정리할 행 없음")
 
        # 변경사항 있으면 다시 저장
        if changed:
            df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig",
                      quoting=csv.QUOTE_ALL, escapechar="\\")
            print(f"→ CSV 정리 완료: {len(df):,}개")
 
        if "category" in df.columns:
            print("\n[카테고리별 수집 현황]")
            print(df.groupby("category")["book_title"].nunique().to_string())
 
        if "book_title" in df.columns:
            print(f"\n[총 수집 책 수] {df['book_title'].nunique():,}권")
 
 
if __name__ == "__main__":
    main()