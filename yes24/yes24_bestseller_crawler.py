"""
Yes24 광범위 리뷰 크롤러 (v6.0 - 목표 15만건)
감성분석용 데이터셋 구축

변경점 (v5.1 → v6.0)
------------------
- 카테고리 19개 → 80개 이상 (소설/경제경영/인문/과학 등 서브카테고리 전면 확장)
- 건강/취미(001020) 신규 메인 카테고리 추가
- 리스팅 모드 2개 → 4개: bestseller·newbook 추가
- pageSize 24 → 120 (페이지당 수집량 최대 5배 향상)
"""

import os
import re
import time
import random
import pandas as pd
from tqdm import tqdm

# 스크립트가 있는 폴더(yes24/)에 CSV 저장
_HERE = os.path.dirname(os.path.abspath(__file__))

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup


BASE_URL = "https://www.yes24.com"
MAX_PAGE_LIMIT = 50
PAGE_SIZE = 120  # 페이지당 최대 수집 (24→120, Yes24 미지원 시 기본값 반환)

# ── 전체 카테고리 (80개+) ─────────────────────────────────────
ALL_CATEGORIES = {
    # ── 소설/시/희곡 ─────────────────────────────────────────
    '소설/시/희곡':             '001001',
    '한국소설':                 '001001001',
    '외국소설':                 '001001002',
    '시':                       '001001003',
    '희곡/시나리오':            '001001004',
    '에세이':                   '001001005',
    '고전소설':                 '001001006',

    # ── 경제경영 ──────────────────────────────────────────────
    '경제경영':                 '001002',
    '경영일반':                 '001002001',
    '경제학/경제일반':          '001002002',
    '마케팅/세일즈':            '001002003',
    '재테크/금융/부동산':       '001002004',
    '인사/조직관리':            '001002005',
    '경영전략/혁신':            '001002006',
    '창업/경영기술':            '001002007',
    '무역/유통':                '001002008',

    # ── 자기계발 ──────────────────────────────────────────────
    '자기계발':                 '001003',
    '성공/처세':                '001003001',
    '화술/협상':                '001003002',
    '인간관계':                 '001003003',
    '시간관리/다이어리':        '001003004',

    # ── 인문 ──────────────────────────────────────────────────
    '인문':                     '001004',
    '철학/사상':                '001004001',
    '심리학/정신분석':          '001004002',
    '언어학':                   '001004003',
    '논리학/윤리학':            '001004004',

    # ── 가정/살림 ─────────────────────────────────────────────
    '가정/살림':                '001005',
    '가정살림일반':             '001005001',
    '임신/육아':                '001005002',
    '인테리어/DIY':             '001005003',
    '원예/조경':                '001005004',

    # ── 요리 ──────────────────────────────────────────────────
    '요리':                     '001006',
    '요리일반':                 '001006001',
    '한식':                     '001006002',
    '양식':                     '001006003',
    '일식':                     '001006004',
    '베이킹/다과':              '001006005',

    # ── 역사/문화 ─────────────────────────────────────────────
    '역사/문화':                '001007',
    '한국사':                   '001007001',
    '동양사/아시아사':          '001007002',
    '서양사':                   '001007003',
    '세계사':                   '001007004',
    '문화/문명':                '001007005',
    '역사일반':                 '001007006',

    # ── 예술/대중문화 ─────────────────────────────────────────
    '예술/대중문화':            '001008',
    '예술일반':                 '001008001',
    '음악':                     '001008002',
    '미술':                     '001008003',
    '영화/드라마':              '001008004',
    '사진':                     '001008005',
    '건축/디자인':              '001008006',

    # ── 종교/역학 ─────────────────────────────────────────────
    '종교/역학':                '001009',
    '기독교':                   '001009001',
    '불교':                     '001009002',
    '천주교':                   '001009003',
    '역학/점술':                '001009004',

    # ── 과학 ──────────────────────────────────────────────────
    '과학':                     '001010',
    '과학일반':                 '001010001',
    '물리학':                   '001010002',
    '화학':                     '001010003',
    '생물학':                   '001010004',
    '지구과학/해양학':          '001010005',
    '천문학':                   '001010006',
    '수학':                     '001010007',

    # ── 외국어 ────────────────────────────────────────────────
    '외국어':                   '001011',
    '영어':                     '001011001',
    '일본어':                   '001011002',
    '중국어':                   '001011003',
    '기타외국어':               '001011004',
    '제2외국어':                '001011005',

    # ── 컴퓨터/IT ─────────────────────────────────────────────
    '컴퓨터/IT':                '001012',
    '컴퓨터일반':               '001012001',
    '프로그래밍':               '001012002',
    '웹/모바일':                '001012003',
    '보안/네트워크':            '001012004',
    '데이터베이스':             '001012005',
    'AI/머신러닝':              '001012006',

    # ── 사회/정치 ─────────────────────────────────────────────
    '사회/정치':                '001013',
    '사회학':                   '001013001',
    '정치학/외교':              '001013002',
    '법률':                     '001013003',
    '언론/미디어':              '001013004',
    '환경/생태':                '001013005',

    # ── 여행 ──────────────────────────────────────────────────
    '여행':                     '001014',
    '여행일반':                 '001014001',
    '국내여행':                 '001014002',
    '해외여행':                 '001014003',

    # ── 수험/자격증 ───────────────────────────────────────────
    '수험/자격증':              '001015',
    '공무원수험서':             '001015001',
    '자격증':                   '001015002',
    '어학/외국어시험':          '001015003',
    '취업/면접':                '001015004',

    # ── 청소년 ────────────────────────────────────────────────
    '청소년':                   '001016',
    '청소년문학':               '001016001',
    '청소년지식/교양':          '001016002',
    '청소년자기계발':           '001016003',

    # ── 어린이 ────────────────────────────────────────────────
    '어린이':                   '001017',
    '어린이문학':               '001017001',
    '어린이학습':               '001017002',
    '어린이과학/사회':          '001017003',

    # ── 유아 ──────────────────────────────────────────────────
    '유아':                     '001018',
    '그림책':                   '001018001',
    '유아학습':                 '001018002',
    '유아놀이/교구':            '001018003',

    # ── 만화 ──────────────────────────────────────────────────
    '만화':                     '001019',
    '만화일반':                 '001019001',
    '순정만화':                 '001019002',
    '액션/무협만화':            '001019003',
    '학습만화':                 '001019004',

    # ── 건강/취미 (신규 메인 카테고리) ───────────────────────
    '건강/취미':                '001020',
    '건강/의학':                '001020001',
    '취미일반':                 '001020002',
    '스포츠/레저':              '001020003',
    '반려동물':                 '001020004',
    '원예/가드닝':              '001020005',
}

# 베스트셀러 모드 호환용
CATEGORY_NUMBERS = ALL_CATEGORIES

# Phase 1 에 사용할 리스팅 모드 (Yes24 URL slug)
# bestseller=주간베스트, newbook=신간, steadyseller=스테디셀러, realtimebestseller=실시간
LISTING_MODES = ['steadyseller', 'realtimebestseller', 'bestseller', 'newbook']


# ── 드라이버 ──────────────────────────────────────────────────
def init_driver(headless=True):
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(60)
    driver.implicitly_wait(10)
    return driver


def _ensure_driver(driver, headless=True):
    try:
        _ = driver.title
        return driver
    except Exception:
        try:
            driver.quit()
        except Exception:
            pass
        print("  [INFO] 드라이버 세션 만료 → 재시작")
        return init_driver(headless=headless)


# ── 텍스트 정제 ───────────────────────────────────────────────
def clean_review_text(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(
        r'[^가-힣ᄀ-ᇿ㄰-㆏\w\s.,!?]',
        ' ', text
    )
    text = text.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _rating_from_class(class_list):
    for cls in (class_list or []):
        m = re.match(r'total_rating_(\d+)$', cls)
        if m:
            return int(m.group(1))
    return None


def _wait_for(driver, css_selector, timeout=10):
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, css_selector))
        )
        return True
    except Exception:
        return False


# ── CSV 저장 ──────────────────────────────────────────────────
REVIEW_COLS = [
    'Title', 'Author', 'Category', 'Year', 'Month',
    'ReviewText', 'ReviewRating', 'ReviewDate', 'ReviewType', 'BookURL',
]


def _save_partial(all_books, all_reviews, books_csv, reviews_csv):
    try:
        if all_books:
            pd.DataFrame(all_books).to_csv(books_csv, index=False, encoding='utf-8-sig')
        if all_reviews:
            pd.DataFrame(all_reviews, columns=REVIEW_COLS).to_csv(
                reviews_csv, index=False, encoding='utf-8-sig'
            )
        print(f"  [저장] 책 {len(all_books)}건 / 리뷰 {len(all_reviews)}건")
    except Exception as e:
        print(f"  [WARN] 저장 실패: {e}")


# ── 리뷰 파싱 ─────────────────────────────────────────────────
def _parse_yes24_reviews(soup, max_reviews=None):
    reviews = []
    boxes = soup.select("div.reviewInfoGrp")
    if max_reviews is not None:
        boxes = boxes[:max_reviews]
    for box in boxes:
        try:
            rating = None
            rating_span = box.select_one("span.review_rating span[class*='total_rating_']")
            if rating_span:
                rating = _rating_from_class(rating_span.get('class', []))

            review_date = None
            date_el = box.select_one("em.txt_date")
            if date_el:
                review_date = date_el.get_text(strip=True)

            text = ""
            origin = box.select_one("div.reviewInfoBot.origin div.review_cont")
            if origin:
                text = clean_review_text(origin.get_text(separator=' ', strip=True))
            if not text:
                crop = box.select_one("div.reviewInfoBot.crop div.review_cont")
                if crop:
                    text = clean_review_text(crop.get_text(separator=' ', strip=True))

            if not text:
                continue

            reviews.append({
                "ReviewText":   text,
                "ReviewRating": rating,
                "ReviewDate":   review_date,
                "ReviewType":   "회원리뷰",
            })
        except Exception:
            continue

    return reviews


def scrape_book_reviews(driver, book_url, max_reviews=None):
    reviews = []
    try:
        driver.get(book_url)
        time.sleep(random.uniform(3, 5))

        driver.execute_script(
            "var el = document.getElementById('infoset_reviewContentList');"
            "if (el) el.scrollIntoView();"
        )
        time.sleep(2)

        _wait_for(driver, "div.reviewInfoGrp", timeout=10)

        for _page in range(200):
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            remaining = None if max_reviews is None else max_reviews - len(reviews)
            batch = _parse_yes24_reviews(soup, remaining)
            reviews.extend(batch)

            if max_reviews is not None and len(reviews) >= max_reviews:
                break

            try:
                container = driver.find_element(
                    By.CSS_SELECTOR, "#infoset_reviewContentList"
                )
                nxt = container.find_element(
                    By.CSS_SELECTOR, "div.yesUI_pagenS a.next:not(.dim)"
                )
                driver.execute_script("arguments[0].click();", nxt)
                time.sleep(random.uniform(2, 3))
                _wait_for(driver, "div.reviewInfoGrp", timeout=8)
            except Exception:
                break

    except Exception as e:
        print(f"  [WARN] 리뷰 수집 오류 ({book_url}): {e}")

    return reviews[:max_reviews] if max_reviews else reviews


# ── 책 목록 파싱 ──────────────────────────────────────────────
def parse_books(soup, year, month=None, category=''):
    """
    베스트셀러(ul.sGLi > li)와 스테디셀러/실시간 등 다른 페이지 모두 지원.
    1차: ul.sGLi > li (베스트셀러)
    2차: a.gd_name 의 부모 li 탐색 (스테디셀러 등)
    """
    books = []

    # ── 1차 셀렉터: 베스트셀러 페이지
    book_items = soup.select('ul.sGLi > li')

    # ── 2차 셀렉터: a.gd_name 을 포함하는 li 탐색 (스테디셀러/실시간 등)
    if not book_items:
        seen_ids = set()
        for link in soup.select('a.gd_name'):
            parent_li = link.find_parent('li')
            if parent_li and id(parent_li) not in seen_ids:
                seen_ids.add(id(parent_li))
                book_items.append(parent_li)

    if not book_items:
        return books

    for item in book_items:
        try:
            rank_tag = item.select_one('em.ico.rank')
            rank = rank_tag.text.strip() if rank_tag else "N/A"

            title_tag = item.select_one('a.gd_name')
            if not title_tag:
                continue
            title = title_tag.text.strip()
            href = title_tag.get('href', '')
            book_url = (BASE_URL + href) if href.startswith('/') else href

            author = "N/A"
            for sel in ('span.info_auth', 'span.gd_auth', '.info_auth'):
                auth_tag = item.select_one(sel)
                if auth_tag:
                    author = auth_tag.get_text(separator=' ').strip()
                    break

            publisher = "N/A"
            for sel in ('span.info_pub a', 'span.gd_pub a', 'a.gd_pub'):
                pub_tag = item.select_one(sel)
                if pub_tag:
                    publisher = pub_tag.text.strip()
                    break

            pub_date = "N/A"
            for sel in ('span.info_date', 'span.gd_date'):
                date_tag = item.select_one(sel)
                if date_tag:
                    pub_date = date_tag.text.strip()
                    break

            price = "N/A"
            price_tag = item.select_one('div.info_price strong.txt_num em.yes_b')
            if price_tag:
                price = price_tag.text.strip() + '원'

            rating = None
            for sel in ('span.rating_grade em.yes_b', 'em.star_score', '.star_score'):
                rating_tag = item.select_one(sel)
                if rating_tag:
                    try:
                        rating = float(rating_tag.text.strip())
                    except Exception:
                        pass
                    break

            review_count = 0
            for sel in (
                'span.rating_rvCount em.txC_blue',
                'em.gd_tit_count',
                '.gd_tit_count',
            ):
                review_tag = item.select_one(sel)
                if review_tag:
                    m = re.search(r'([\d,]+)', review_tag.text)
                    if m:
                        review_count = int(m.group(1).replace(',', ''))
                    break
            # 텍스트 전체에서 리뷰 수 파싱 (폴백)
            if review_count == 0:
                full_text = item.get_text()
                m = re.search(r'회원리뷰[^0-9]*([\d,]+)', full_text)
                if m:
                    review_count = int(m.group(1).replace(',', ''))

            sales_index = None
            sales_tag = item.select_one('span.saleNum')
            if sales_tag:
                m = re.search(r'([\d,]+)', sales_tag.text)
                if m:
                    sales_index = int(m.group(1).replace(',', ''))

            books.append({
                'Year':        year if year is not None else 'N/A',
                'Month':       month if month is not None else 'N/A',
                'Category':    category,
                'Rank':        rank,
                'Title':       title,
                'Author':      author,
                'Publisher':   publisher,
                'PubDate':     pub_date,
                'Price':       price,
                'Rating':      rating,
                'ReviewCount': review_count,
                'SalesIndex':  sales_index,
                'BookURL':     book_url,
            })
        except Exception:
            continue

    return books


# ── URL 빌더 ──────────────────────────────────────────────────
def _build_listing_url(mode, cat_num, page):
    """Phase 1 카테고리 리스팅 URL"""
    return (
        f"https://www.yes24.com/product/category/{mode}"
        f"?categoryNumber={cat_num}&pageNumber={page}&pageSize={PAGE_SIZE}"
    )


def _build_bestseller_url(period_type, cat_num, year, month, page):
    if period_type == 'mo':
        return (
            "https://www.yes24.com/Product/Category/MonthBestSeller"
            f"?categoryNumber={cat_num}&year={year}&month={month}"
            f"&pageNumber={page}&pageSize=24"
        )
    else:
        return (
            "https://www.yes24.com/product/category/bestseller"
            f"?categoryNumber={cat_num}&pageNumber={page}&pageSize=24"
        )


def _fetch_page_books(driver, url, year, month, cat_name):
    try:
        driver.get(url)
        time.sleep(random.uniform(2, 4))
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        books = parse_books(soup, year, month, cat_name)
        return books
    except Exception as e:
        print(f"  [WARN] 페이지 로드 실패 ({url}): {e}")
        return []


# ── 공통 리뷰 수집 ────────────────────────────────────────────
def _collect_reviews_for_books(
    driver, target_books, all_books, all_reviews, collected_urls,
    books_csv, reviews_csv, start_time, time_limit_seconds,
    max_reviews_per_book, headless, label,
    seen_review_keys,
):
    """
    target_books 에서 리뷰를 수집.
    seen_review_keys: {(book_url, review_text[:80])} — 중복 리뷰 방지
    반환: (new_reviews, crawled_books, timed_out)
    """
    new_reviews = 0
    crawled = 0

    for book in tqdm(target_books, desc=label, leave=False):
        if (time.time() - start_time) >= time_limit_seconds:
            print(f"\n[시간 제한] 안전 종료")
            return new_reviews, crawled, True

        book_url = book.get('BookURL', '')
        if not book_url or book.get('ReviewCount', 0) == 0:
            continue
        if book_url in collected_urls:
            continue

        driver = _ensure_driver(driver, headless)
        raw_reviews = scrape_book_reviews(driver, book_url, max_reviews=max_reviews_per_book)

        added = 0
        for rv in raw_reviews:
            rkey = (book_url, rv['ReviewText'][:80])
            if rkey in seen_review_keys:
                continue
            seen_review_keys.add(rkey)
            all_reviews.append({
                'Title':        book['Title'],
                'Author':       book['Author'],
                'Category':     book['Category'],
                'Year':         book['Year'],
                'Month':        book['Month'],
                'ReviewText':   rv['ReviewText'],
                'ReviewRating': rv['ReviewRating'],
                'ReviewDate':   rv['ReviewDate'],
                'ReviewType':   rv['ReviewType'],
                'BookURL':      book_url,
            })
            added += 1

        new_reviews += added
        crawled += 1
        collected_urls.add(book_url)

        _save_partial(all_books, all_reviews, books_csv, reviews_csv)
        time.sleep(random.uniform(2, 4))

    return new_reviews, crawled, False


# ── 메인 크롤러 (v5.1) ────────────────────────────────────────
def scrape_yes24_broad(
    category_numbers=None,
    listing_modes=None,
    min_review_count=5,
    max_reviews_per_book=None,
    target_total_reviews=150000,
    max_pages_per_cat=50,
    headless=True,
    books_csv=None,
    reviews_csv=None,
    time_limit_hours=24,
    also_crawl_bestseller=True,
    bestseller_start_year=2026,
    bestseller_end_year=2015,
):
    """
    Phase 1: 카테고리 리스팅(steadyseller/realtimebestseller) → 광범위 수집
    Phase 2: 월별 베스트셀러 → 보조 수집
    """
    if category_numbers is None:
        category_numbers = ALL_CATEGORIES
    if listing_modes is None:
        listing_modes = LISTING_MODES
    if books_csv is None:
        books_csv = os.path.join(_HERE, 'yes24_books_metadata.csv')
    if reviews_csv is None:
        reviews_csv = os.path.join(_HERE, 'yes24_book_reviews.csv')

    driver = init_driver(headless=headless)

    # ── 기존 데이터 이어하기 ─────────────────────────────────
    try:
        all_books = pd.read_csv(books_csv, encoding='utf-8-sig').to_dict('records')
        print(f"[이어하기] 기존 책 {len(all_books)}건 로드")
    except FileNotFoundError:
        all_books = []
    try:
        all_reviews = pd.read_csv(reviews_csv, encoding='utf-8-sig').to_dict('records')
        print(f"[이어하기] 기존 리뷰 {len(all_reviews)}건 로드")
    except FileNotFoundError:
        all_reviews = []

    # 책 URL 중복 방지
    collected_urls = {r.get('BookURL') for r in all_reviews if r.get('BookURL')}
    if collected_urls:
        print(f"[이어하기] 수집 완료 책 {len(collected_urls)}권")

    # 리뷰 중복 방지 (기존 데이터 기반 초기화)
    seen_review_keys = {
        (r.get('BookURL', ''), r.get('ReviewText', '')[:80])
        for r in all_reviews
    }
    print(f"[이어하기] 기존 리뷰 키 {len(seen_review_keys)}개 로드")

    start_time = time.time()
    time_limit_seconds = time_limit_hours * 3600
    stop_flag = False

    def _target_reached():
        if len(all_reviews) >= target_total_reviews:
            print(f"\n[목표 달성] {len(all_reviews):,}건 리뷰 수집 완료!")
            return True
        return False

    def _time_up():
        return (time.time() - start_time) >= time_limit_seconds

    # ══════════════════════════════════════════════════════════
    # Phase 1: 카테고리 리스팅 크롤링
    # ══════════════════════════════════════════════════════════
    print(f"\n{'='*60}")
    print(f"[Phase 1] 카테고리 리스팅 크롤링")
    print(f"  카테고리: {len(category_numbers)}개 / 모드: {listing_modes}")
    print(f"  최소 리뷰: {min_review_count}건 / 목표: {target_total_reviews:,}건")
    print(f"{'='*60}")

    for mode in listing_modes:
        if stop_flag or _target_reached() or _time_up():
            break

        for cat_name, cat_num in category_numbers.items():
            if stop_flag or _target_reached() or _time_up():
                break

            label = f"[{mode}][{cat_name}]"
            print(f"\n{label} 시작")
            seen_in_combo = set()
            consecutive_empty = 0

            for page in range(1, max_pages_per_cat + 1):
                if stop_flag or _target_reached() or _time_up():
                    break

                url = _build_listing_url(mode, cat_num, page)
                driver = _ensure_driver(driver, headless)
                page_books = _fetch_page_books(driver, url, 'N/A', 'N/A', cat_name)

                if not page_books:
                    consecutive_empty += 1
                    print(f"  {label} p{page}: 책 없음 (연속 {consecutive_empty}회)")
                    if consecutive_empty >= 3:
                        print(f"  {label}: 3페이지 연속 책 없음 → 중단")
                        break
                    time.sleep(random.uniform(2, 3))
                    continue
                else:
                    consecutive_empty = 0

                new_books_on_page = []
                for b in page_books:
                    url_b = b.get('BookURL', '')
                    if not url_b or url_b == BASE_URL:
                        continue
                    if url_b in seen_in_combo or url_b in collected_urls:
                        continue
                    if b.get('ReviewCount', 0) < min_review_count:
                        continue
                    seen_in_combo.add(url_b)
                    new_books_on_page.append(b)

                if not new_books_on_page:
                    consecutive_empty += 1
                    if consecutive_empty >= 3:
                        print(f"  {label} p{page}: 신규 책 3페이지 연속 없음 → 중단")
                        break
                    time.sleep(random.uniform(1, 2))
                    continue
                else:
                    consecutive_empty = 0

                all_books.extend(new_books_on_page)
                print(
                    f"  {label} p{page}: 신규 {len(new_books_on_page)}권 "
                    f"(누적 리뷰 {len(all_reviews):,}건)"
                )

                new_rv, crawled, timed_out = _collect_reviews_for_books(
                    driver, new_books_on_page, all_books, all_reviews, collected_urls,
                    books_csv, reviews_csv, start_time, time_limit_seconds,
                    max_reviews_per_book, headless,
                    label=f"{cat_name} p{page}",
                    seen_review_keys=seen_review_keys,
                )
                if timed_out:
                    stop_flag = True
                    break

                elapsed_min = (time.time() - start_time) / 60
                remain_min = (time_limit_seconds - (time.time() - start_time)) / 60
                print(
                    f"  {label} p{page}: 리뷰 +{new_rv}건 | "
                    f"누적 {len(all_reviews):,}건 | "
                    f"경과 {elapsed_min:.0f}분 / 남은 {remain_min:.0f}분"
                )
                time.sleep(random.uniform(1, 2))

    # ══════════════════════════════════════════════════════════
    # Phase 2: 베스트셀러 보조 크롤링
    # ══════════════════════════════════════════════════════════
    if also_crawl_bestseller and not stop_flag and not _target_reached() and not _time_up():
        print(f"\n{'='*60}")
        print(f"[Phase 2] 베스트셀러 보조 크롤링")
        print(f"  기간: {bestseller_end_year}~{bestseller_start_year}년")
        print(f"{'='*60}")

        for year in range(bestseller_start_year, bestseller_end_year - 1, -1):
            if stop_flag or _target_reached() or _time_up():
                break
            print(f"\n[베스트셀러] {year}년")

            for month in range(12, 0, -1):
                if stop_flag or _target_reached() or _time_up():
                    break

                for cat_name, cat_num in category_numbers.items():
                    if stop_flag or _target_reached() or _time_up():
                        break

                    new_books_queue = []
                    seen_urls_period = set()

                    for page in range(1, MAX_PAGE_LIMIT + 1):
                        if _time_up():
                            stop_flag = True
                            break
                        url = _build_bestseller_url('mo', cat_num, year, month, page)
                        driver = _ensure_driver(driver, headless)
                        page_books = _fetch_page_books(driver, url, year, month, cat_name)

                        if not page_books:
                            break

                        added = 0
                        for b in page_books:
                            url_b = b.get('BookURL', '')
                            if not url_b or url_b == BASE_URL:
                                continue
                            if url_b in seen_urls_period or url_b in collected_urls:
                                continue
                            if b.get('ReviewCount', 0) < min_review_count:
                                continue
                            seen_urls_period.add(url_b)
                            new_books_queue.append(b)
                            added += 1

                        if added == 0:
                            break
                        time.sleep(random.uniform(1, 2))

                    if not new_books_queue:
                        continue

                    all_books.extend(new_books_queue)
                    label_bs = f"베스트셀러 {year}년{month}월 {cat_name}"
                    print(f"  [{label_bs}] 신규 {len(new_books_queue)}권")

                    new_rv, crawled, timed_out = _collect_reviews_for_books(
                        driver, new_books_queue, all_books, all_reviews, collected_urls,
                        books_csv, reviews_csv, start_time, time_limit_seconds,
                        max_reviews_per_book, headless, label=label_bs,
                        seen_review_keys=seen_review_keys,
                    )
                    if timed_out:
                        stop_flag = True

                    elapsed_min = (time.time() - start_time) / 60
                    print(
                        f"  [{label_bs}] 리뷰 +{new_rv}건 | "
                        f"누적 {len(all_reviews):,}건 | 경과 {elapsed_min:.0f}분"
                    )

    # ── 최종 저장 + dedup ──────────────────────────────────────
    try:
        driver.quit()
    except Exception:
        pass

    books_df = pd.DataFrame(all_books)
    if not books_df.empty:
        books_df = books_df.drop_duplicates(subset=['BookURL']).reset_index(drop=True)

    reviews_df = (
        pd.DataFrame(all_reviews, columns=REVIEW_COLS)
        if all_reviews
        else pd.DataFrame(columns=REVIEW_COLS)
    )
    if not reviews_df.empty:
        before = len(reviews_df)
        # 같은 책, 같은 리뷰 텍스트 중복 제거
        reviews_df['_dedup_key'] = (
            reviews_df['BookURL'].fillna('') + '|'
            + reviews_df['ReviewText'].fillna('').str[:80]
        )
        reviews_df = (
            reviews_df.drop_duplicates(subset=['_dedup_key'])
            .drop(columns=['_dedup_key'])
            .reset_index(drop=True)
        )
        reviews_df = reviews_df[
            reviews_df['ReviewText'].str.len() > 0
        ].reset_index(drop=True)
        reviews_df['ReviewRating'] = pd.to_numeric(
            reviews_df['ReviewRating'], errors='coerce'
        )
        after = len(reviews_df)
        if before != after:
            print(f"[dedup] 리뷰 {before - after}건 중복 제거 ({before} → {after})")

    books_df.to_csv(books_csv, index=False, encoding='utf-8-sig')
    reviews_df.to_csv(reviews_csv, index=False, encoding='utf-8-sig')

    print(f"\n{'='*60}")
    print(f"최종 저장 완료!")
    print(f"  {books_csv}  : {len(books_df):,}건")
    print(f"  {reviews_csv}: {len(reviews_df):,}건")
    print(f"{'='*60}")

    return books_df, reviews_df


# ── 기존 v4.1 호환 래퍼 ───────────────────────────────────────
def scrape_yes24_with_reviews(
    start_year, end_year,
    period_type='mo',
    category_numbers=None,
    target_new_books_per_month=None,
    max_reviews=None,
    headless=True,
    books_csv=None,
    reviews_csv=None,
    time_limit_hours=12,
):
    if books_csv is None:
        books_csv = os.path.join(_HERE, 'yes24_books_metadata.csv')
    if reviews_csv is None:
        reviews_csv = os.path.join(_HERE, 'yes24_book_reviews.csv')
    return scrape_yes24_broad(
        category_numbers=category_numbers or {'국내도서 전체': '001'},
        listing_modes=[],
        min_review_count=1,
        max_reviews_per_book=max_reviews,
        target_total_reviews=999_999_999,
        headless=headless,
        books_csv=books_csv,
        reviews_csv=reviews_csv,
        time_limit_hours=time_limit_hours,
        also_crawl_bestseller=True,
        bestseller_start_year=start_year,
        bestseller_end_year=end_year,
    )


# ── 진입점 ────────────────────────────────────────────────────
if __name__ == "__main__":
    TARGET_CATEGORIES     = ALL_CATEGORIES
    LISTING_MODES_RUN     = ['steadyseller', 'realtimebestseller']
    MIN_REVIEW_COUNT      = 5
    MAX_REVIEWS_PER_BOOK  = None    # None = 모든 리뷰
    TARGET_TOTAL_REVIEWS  = 150_000
    MAX_PAGES_PER_CAT     = 50
    TIME_LIMIT_HOURS      = 48
    HEADLESS              = True
    ALSO_CRAWL_BESTSELLER = True
    BESTSELLER_START_YEAR = 2026
    BESTSELLER_END_YEAR   = 1990

    print("=" * 60)
    print("Yes24 광범위 크롤링 시작 (v6.0)")
    print(f"카테고리: {len(TARGET_CATEGORIES)}개 / 모드: {LISTING_MODES_RUN}")
    print(f"최소 리뷰: {MIN_REVIEW_COUNT}건 / 목표: {TARGET_TOTAL_REVIEWS:,}건")
    print(f"시간 제한: {TIME_LIMIT_HOURS}시간")
    print("=" * 60)

    try:
        books_df, reviews_df = scrape_yes24_broad(
            category_numbers=TARGET_CATEGORIES,
            listing_modes=LISTING_MODES_RUN,
            min_review_count=MIN_REVIEW_COUNT,
            max_reviews_per_book=MAX_REVIEWS_PER_BOOK,
            target_total_reviews=TARGET_TOTAL_REVIEWS,
            max_pages_per_cat=MAX_PAGES_PER_CAT,
            headless=HEADLESS,
            time_limit_hours=TIME_LIMIT_HOURS,
            also_crawl_bestseller=ALSO_CRAWL_BESTSELLER,
            bestseller_start_year=BESTSELLER_START_YEAR,
            bestseller_end_year=BESTSELLER_END_YEAR,
        )
    except KeyboardInterrupt:
        print("\n[사용자 중단] 수집 데이터가 CSV에 저장됐습니다.")
    except Exception as e:
        print(f"\n[WARN] 크롤링 중단 ({e.__class__.__name__}: {e})")
        print("부분 수집 데이터가 CSV에 저장됐습니다.")
    else:
        if not reviews_df.empty:
            print("\n리뷰 샘플 (상위 3건):")
            print(
                reviews_df[['Title', 'ReviewText', 'ReviewRating', 'ReviewDate']]
                .head(3).to_string(index=False)
            )
