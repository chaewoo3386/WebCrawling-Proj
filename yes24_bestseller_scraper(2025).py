"""
Yes24 베스트셀러 + 리뷰 크롤러
감성분석용 데이터셋 구축 (책 메타데이터 + 개별 리뷰 텍스트/별점/날짜)

KoNLPy / Mecab / Kiwi / transformers / KcBERT / HuggingFace 입력 형태로 바로 활용 가능
"""

import re
import time
import random
import pandas as pd
from tqdm import tqdm

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup


# ── 상수 ─────────────────────────────────────────────────────────────
BASE_URL = "https://www.yes24.com"

# ── Yes24 국내도서 분야별 categoryNumber ──────────────────────────────
# 추가하려면 yes24.com 베스트셀러 좌측 카테고리 링크의 categoryNumber 파라미터 참조
CATEGORY_NUMBERS = {
    '국내도서 전체': '001',
    '소설/시/희곡':  '001001',
    '경제경영':      '001002',
    '자기계발':      '001003',
    '인문':          '001004',
    '역사/문화':     '001007',
    '과학':          '001010',
}


def init_driver(headless=True):
    """Selenium Chrome 드라이버 초기화"""
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
    return webdriver.Chrome(service=service, options=chrome_options)


# ── 텍스트 정제 ───────────────────────────────────────────────────────
def clean_review_text(text):
    """
    리뷰 텍스트 정제 - KoNLPy / Mecab / Kiwi / transformers 입력용

    수행 작업
    ---------
    - HTML 태그 제거
    - 한글·영문·숫자·기본 문장부호 외 특수문자 제거
    - 줄바꿈·탭 제거
    - 중복 공백 정리
    - None/빈값 처리
    """
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(
        r'[^\uAC00-\uD7A3\u1100-\u11FF\u3130-\u318F\w\s.,!?]',
        ' ', text
    )
    text = text.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────
def _rating_from_class(class_list):
    """
    Yes24 별점 클래스 → 숫자
    예: ['total_rating', 'total_rating_10', 'bgGD'] → 10
    (2점 단위 버킷: 10, 8, 6, 4, 2)
    """
    for cls in (class_list or []):
        m = re.match(r'total_rating_(\d+)$', cls)
        if m:
            return int(m.group(1))
    return None


def _wait_for(driver, css_selector, timeout=10):
    """CSS 셀렉터 요소가 DOM에 나타날 때까지 대기"""
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, css_selector))
        )
        return True
    except Exception:
        return False


def _save_partial(all_books, all_reviews, books_csv, reviews_csv):
    """부분 수집 데이터를 CSV 로 저장 (중간 저장 / finally 용)"""
    try:
        if all_books:
            pd.DataFrame(all_books).to_csv(books_csv, index=False, encoding='utf-8-sig')
        if all_reviews:
            review_cols = [
                'Title', 'Author', 'Category', 'Year', 'Month',
                'ReviewText', 'ReviewRating', 'ReviewDate', 'ReviewType', 'BookURL',
            ]
            pd.DataFrame(all_reviews, columns=review_cols).to_csv(
                reviews_csv, index=False, encoding='utf-8-sig'
            )
        print(f"  [저장] {len(all_books)}건 책 / {len(all_reviews)}건 리뷰")
    except Exception as e:
        print(f"  [WARN] 저장 실패: {e}")


def _ensure_driver(driver, headless=True):
    """드라이버 세션이 살아있는지 확인 후 죽으면 재시작"""
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


# ── 리뷰 파싱 ─────────────────────────────────────────────────────────
def _parse_yes24_reviews(soup, max_reviews=None):
    """
    div.reviewInfoGrp 에서 Yes24 리뷰 수집
    - 별점 : span.review_rating > span.total_rating_N  → N (10점 척도)
    - 날짜 : em.txt_date
    - 텍스트: div.reviewInfoBot.origin (전문) > div.review_cont
              div.reviewInfoBot.crop  (요약) > div.review_cont  (fallback)
    max_reviews=None 이면 모든 리뷰 수집
    """
    reviews = []
    boxes = soup.select("div.reviewInfoGrp")
    if max_reviews is not None:
        boxes = boxes[:max_reviews]
    for box in boxes:
        try:
            # 별점
            rating = None
            rating_span = box.select_one("span.review_rating span[class*='total_rating_']")
            if rating_span:
                rating = _rating_from_class(rating_span.get('class', []))

            # 날짜
            review_date = None
            date_el = box.select_one("em.txt_date")
            if date_el:
                review_date = date_el.get_text(strip=True)

            # 텍스트 (전문 우선, 요약 fallback)
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


# ── 리뷰 수집 메인 함수 ───────────────────────────────────────────────
def scrape_book_reviews(driver, book_url, max_reviews=None):
    """
    Yes24 책 상세 페이지에서 리뷰 수집

    Parameters
    ----------
    driver      : Selenium WebDriver 인스턴스
    book_url    : 책 상세 페이지 절대 URL
    max_reviews : 수집할 최대 리뷰 수 (None=무제한)

    Returns
    -------
    list[dict]  : ReviewText, ReviewRating, ReviewDate, ReviewType
    """
    reviews = []
    try:
        driver.get(book_url)
        time.sleep(random.uniform(3, 5))

        # 리뷰 섹션으로 스크롤 → AJAX 트리거
        driver.execute_script(
            "var el = document.getElementById('infoset_reviewContentList');"
            "if (el) el.scrollIntoView();"
        )
        time.sleep(2)

        # div.reviewInfoGrp 로드 대기
        _wait_for(driver, "div.reviewInfoGrp", timeout=10)

        for _page in range(200):  # 실제 종료는 max_reviews 도달 / 다음버튼 없음
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            remaining = None if max_reviews is None else max_reviews - len(reviews)
            batch = _parse_yes24_reviews(soup, remaining)
            reviews.extend(batch)

            if max_reviews is not None and len(reviews) >= max_reviews:
                break

            # 다음 페이지 버튼 (container 내 페이저)
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

    return reviews[:max_reviews]


# ── 베스트셀러 파싱 ───────────────────────────────────────────────────
def parse_books(soup, year, month=None, category='국내도서 전체'):
    """베스트셀러 페이지에서 책 메타데이터 + 상세 URL 파싱"""
    books = []
    book_items = soup.select('ul.sGLi > li')

    for item in book_items:
        try:
            # 순위
            rank_tag = item.select_one('em.ico.rank')
            rank = rank_tag.text.strip() if rank_tag else "N/A"

            # 제목 & 상세 URL (절대 경로)
            title_tag = item.select_one('a.gd_name')
            if not title_tag:
                continue
            title = title_tag.text.strip()
            href = title_tag.get('href', '')
            book_url = (BASE_URL + href) if href.startswith('/') else href

            # 저자
            author = "N/A"
            auth_tag = item.select_one('span.info_auth')
            if auth_tag:
                author = auth_tag.get_text(separator=' ').strip()

            # 출판사
            publisher = "N/A"
            pub_tag = item.select_one('span.info_pub a')
            if pub_tag:
                publisher = pub_tag.text.strip()

            # 출판일
            pub_date = "N/A"
            date_tag = item.select_one('span.info_date')
            if date_tag:
                pub_date = date_tag.text.strip()

            # 판매가 (할인가)
            price = "N/A"
            price_tag = item.select_one('div.info_price strong.txt_num em.yes_b')
            if price_tag:
                price = price_tag.text.strip() + '원'

            # 별점 (float 변환)
            rating_raw = ""
            rating_tag = item.select_one('span.rating_grade em.yes_b')
            if rating_tag:
                rating_raw = rating_tag.text.strip()
            try:
                rating = float(rating_raw)
            except Exception:
                rating = None

            # 회원리뷰 수 (숫자만 추출)
            review_count = 0
            review_tag = item.select_one('span.rating_rvCount em.txC_blue')
            if review_tag:
                m = re.search(r'([\d,]+)', review_tag.text)
                if m:
                    review_count = int(m.group(1).replace(',', ''))

            # 판매지수 (숫자만 추출)
            sales_index = None
            sales_tag = item.select_one('span.saleNum')
            if sales_tag:
                m = re.search(r'([\d,]+)', sales_tag.text)
                if m:
                    sales_index = int(m.group(1).replace(',', ''))

            books.append({
                'Year':        year,
                'Month':       month if month is not None else "N/A",
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


# ── 베스트셀러 전용 크롤러 ────────────────────────────────────────────
def scrape_yes24_books(
    start_year, end_year,
    period_type='mo',
    category_numbers=None,
    pages_per_period=2,
    headless=True,
):
    """
    Yes24 베스트셀러 목록 크롤링 (리뷰 미포함)

    Parameters
    ----------
    start_year       : 수집 시작 연도 (큰 수)
    end_year         : 수집 종료 연도 (작은 수, 포함)
    period_type      : 'mo' (월간) 또는 'we' (주간 현재)
    category_numbers : {분야명: categoryNumber} 딕셔너리
    pages_per_period : 기간당 페이지 수 (1페이지 = 24건)
    headless         : Chrome headless 모드 ON/OFF
    """
    if category_numbers is None:
        category_numbers = {'국내도서 전체': '001'}

    driver = init_driver(headless=headless)
    all_books = []
    total_requests = 0

    try:
        for year in range(start_year, end_year - 1, -1):
            print(f"\n{'='*40}\n[{year}년]")
            months = list(range(12, 0, -1)) if period_type == 'mo' else [None]

            for month in months:
                for cat_name, cat_num in category_numbers.items():
                    label = f"{year}년 {month}월" if month else f"{year}년"
                    period_books = []

                    for page in range(1, pages_per_period + 1):
                        if period_type == 'mo':
                            url = (
                                "https://www.yes24.com/Product/Category/MonthBestSeller"
                                f"?categoryNumber={cat_num}&year={year}&month={month}"
                                f"&pageNumber={page}&pageSize=24"
                            )
                        else:
                            url = (
                                "https://www.yes24.com/product/category/bestseller"
                                f"?categoryNumber={cat_num}&pageNumber={page}&pageSize=24"
                            )

                        driver.get(url)
                        total_requests += 1
                        time.sleep(random.uniform(3, 5))

                        soup = BeautifulSoup(driver.page_source, 'html.parser')
                        page_books = parse_books(soup, year, month, cat_name)

                        if not page_books:
                            break

                        period_books.extend(page_books)
                        time.sleep(random.uniform(1, 2))

                    all_books.extend(period_books)
                    print(f"  [{label}][{cat_name}] {len(period_books)}건 | 누적: {len(all_books)}건")

    finally:
        driver.quit()

    print(f"\n총 요청 횟수: {total_requests}회 / 총 수집: {len(all_books)}건")
    return all_books


# ── 베스트셀러 + 리뷰 통합 크롤러 ───────────────────────────────────
def scrape_yes24_with_reviews(
    start_year, end_year,
    period_type='mo',
    category_numbers=None,
    pages_per_period=1,
    max_books_per_month=10,
    max_reviews=None,
    headless=True,
    books_csv='yes24_books_metadata.csv',
    reviews_csv='yes24_book_reviews.csv',
    time_limit_hours=12,
):
    """
    베스트셀러 목록 + 각 책의 리뷰 통합 크롤링

    Parameters
    ----------
    start_year          : 수집 시작 연도
    end_year            : 수집 종료 연도 (포함)
    period_type         : 'mo' (월간) / 'we' (주간)
    category_numbers    : {분야명: categoryNumber} 딕셔너리
    pages_per_period    : 기간당 베스트셀러 페이지 수 (1=24건)
    max_books_per_month : 월별 리뷰 수집 대상 최대 책 수
    max_reviews         : 책당 최대 리뷰 수
    headless            : Chrome headless 모드 ON/OFF
    books_csv           : 책 메타데이터 저장 파일명
    reviews_csv         : 리뷰 데이터 저장 파일명

    Returns
    -------
    (books_df, reviews_df) : 두 개의 DataFrame
    """
    if category_numbers is None:
        category_numbers = {'국내도서 전체': '001'}

    driver = init_driver(headless=headless)
    all_books = []
    all_reviews = []

    # 시간 제한 설정
    start_time = time.time()
    time_limit_seconds = time_limit_hours * 3600
    stop_flag = False

    def _time_left():
        return time_limit_seconds - (time.time() - start_time)

    def _check_time():
        if _time_left() <= 0:
            print(f"\n[시간 제한] {time_limit_hours}시간 도달 → 안전 종료")
            return True
        return False

    try:
        for year in range(start_year, end_year - 1, -1):
            if stop_flag:
                break
            print(f"\n{'='*50}\n[{year}년]")
            months = list(range(12, 0, -1)) if period_type == 'mo' else [None]

            for month in months:
                if stop_flag:
                    break
                for cat_name, cat_num in category_numbers.items():
                    if stop_flag:
                        break
                    label = f"{year}년 {month}월" if month else f"{year}년"
                    period_books = []

                    # 1) 베스트셀러 목록 수집
                    for page in range(1, pages_per_period + 1):
                        driver = _ensure_driver(driver, headless)
                        if period_type == 'mo':
                            url = (
                                "https://www.yes24.com/Product/Category/MonthBestSeller"
                                f"?categoryNumber={cat_num}&year={year}&month={month}"
                                f"&pageNumber={page}&pageSize=24"
                            )
                        else:
                            url = (
                                "https://www.yes24.com/product/category/bestseller"
                                f"?categoryNumber={cat_num}&pageNumber={page}&pageSize=24"
                            )

                        driver.get(url)
                        time.sleep(random.uniform(3, 5))
                        soup = BeautifulSoup(driver.page_source, 'html.parser')
                        page_books = parse_books(soup, year, month, cat_name)

                        if not page_books:
                            break
                        period_books.extend(page_books)
                        time.sleep(random.uniform(1, 2))

                    all_books.extend(period_books)

                    # 2) max_books_per_month 제한 적용 후 리뷰 수집
                    target_books = period_books[:max_books_per_month]
                    new_reviews = 0

                    for book in tqdm(target_books, desc=f"{label} {cat_name}", leave=False):
                        if _check_time():
                            stop_flag = True
                            break
                        url = book.get('BookURL', '')
                        if not url or url == BASE_URL:
                            continue
                        if book.get('ReviewCount', 0) == 0:
                            continue  # 리뷰 없는 책 건너뜀

                        driver = _ensure_driver(driver, headless)
                        raw_reviews = scrape_book_reviews(
                            driver, url, max_reviews=max_reviews
                        )

                        for rv in raw_reviews:
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
                                'BookURL':      url,
                            })
                        new_reviews += len(raw_reviews)
                        # 증분 저장: 매 책 수집 완료 시 CSV 업데이트 (SIGKILL/강제종료 대비)
                        _save_partial(all_books, all_reviews, books_csv, reviews_csv)
                        time.sleep(random.uniform(2, 4))

                    elapsed_min = (time.time() - start_time) / 60
                    remain_min = _time_left() / 60
                    print(
                        f"  [{label}][{cat_name}] 책 {len(target_books)}권 | "
                        f"리뷰 {new_reviews}건 | 누적 리뷰: {len(all_reviews)}건 | "
                        f"경과 {elapsed_min:.1f}분 / 남은시간 {remain_min:.1f}분"
                    )

    finally:
        try:
            driver.quit()
        except Exception:
            pass
        # 예외로 중단됐을 때도 부분 수집 데이터 저장
        if all_books or all_reviews:
            _save_partial(all_books, all_reviews, books_csv, reviews_csv)

    # 중복 제거 및 DataFrame 생성 (반환용)
    books_df = pd.DataFrame(all_books)
    if not books_df.empty:
        books_df = books_df.drop_duplicates(
            subset=['Title', 'Author', 'Year', 'Month']
        ).reset_index(drop=True)

    review_cols = [
        'Title', 'Author', 'Category', 'Year', 'Month',
        'ReviewText', 'ReviewRating', 'ReviewDate', 'ReviewType', 'BookURL',
    ]
    reviews_df = (
        pd.DataFrame(all_reviews, columns=review_cols)
        if all_reviews
        else pd.DataFrame(columns=review_cols)
    )
    if not reviews_df.empty:
        reviews_df = reviews_df[
            reviews_df['ReviewText'].str.len() > 0
        ].drop_duplicates(
            subset=['Title', 'ReviewText']
        ).reset_index(drop=True)
        reviews_df['ReviewRating'] = pd.to_numeric(
            reviews_df['ReviewRating'], errors='coerce'
        )

    # 중복 제거 후 최종 저장
    books_df.to_csv(books_csv, index=False, encoding='utf-8-sig')
    reviews_df.to_csv(reviews_csv, index=False, encoding='utf-8-sig')
    print(f"\n최종 저장 완료!")
    print(f"  {books_csv}  : {len(books_df):,}건")
    print(f"  {reviews_csv}: {len(reviews_df):,}건")

    return books_df, reviews_df


# ── 실행 진입점 ───────────────────────────────────────────────────────
if __name__ == "__main__":
    # ── 수집 모드 ─────────────────────────────────────────────────────
    # 'books' : 베스트셀러 목록만 수집 → yes24_monthly_bestsellers.csv
    # 'both'  : 베스트셀러 + 리뷰 통합 → yes24_books_metadata.csv + yes24_book_reviews.csv
    MODE = 'both'

    # ── 수집 설정 ─────────────────────────────────────────────────────
    TARGET_CATEGORIES = {
        '국내도서 전체': '001',  # 테스트용 1개 카테고리만
    }
    START_YEAR          = 2025
    END_YEAR            = 2025    # 테스트용 1년만
    PERIOD_TYPE         = 'mo'   # 'mo'=월간, 'ye'=연간
    PAGES_PER_PERIOD    = 9      # 9페이지 = 216권 (월별 200권 수집)
    MAX_BOOKS_PER_MONTH = 200    # 월별 리뷰 수집 대상 책 수
    MAX_REVIEWS         = None   # None = 책당 모든 리뷰 수집
    TIME_LIMIT_HOURS    = 12     # 최대 실행 시간 (초과 시 안전 종료)
    HEADLESS            = True   # 본격 수집용 headless ON
    # ──────────────────────────────────────────────────────────────────

    n_years  = START_YEAR - END_YEAR + 1
    n_months = 12 if PERIOD_TYPE == 'mo' else 1
    n_cats   = len(TARGET_CATEGORIES)

    print("=" * 55)
    print("Yes24 크롤링 시작")
    print(f"모드: {MODE} / 기간: {END_YEAR}~{START_YEAR}년 / 주기: {PERIOD_TYPE}")
    print(f"분야: {n_cats}개 / 월별 책: {MAX_BOOKS_PER_MONTH}권 / 책당 리뷰: {MAX_REVIEWS}건")
    est_min = n_years * n_months * n_cats * (PAGES_PER_PERIOD * 4 + MAX_BOOKS_PER_MONTH * 8) // 60
    print(f"예상 소요 시간: 약 {est_min}분 (네트워크 상태에 따라 변동)")
    print("=" * 55)

    if MODE == 'books':
        data = scrape_yes24_books(
            start_year=START_YEAR,
            end_year=END_YEAR,
            period_type=PERIOD_TYPE,
            category_numbers=TARGET_CATEGORIES,
            pages_per_period=PAGES_PER_PERIOD,
            headless=HEADLESS,
        )
        if data:
            df = pd.DataFrame(data)
            out = "yes24_monthly_bestsellers_2014_to_2025.csv"
            df.to_csv(out, index=False, encoding='utf-8-sig')
            print(f"\n완료! 총 {len(data):,}건 → '{out}' 저장")
            print(df.head(10).to_string(index=False))
        else:
            print("\n크롤링된 데이터가 없습니다.")

    else:
        try:
            books_df, reviews_df = scrape_yes24_with_reviews(
                start_year=START_YEAR,
                end_year=END_YEAR,
                period_type=PERIOD_TYPE,
                category_numbers=TARGET_CATEGORIES,
                pages_per_period=PAGES_PER_PERIOD,
                max_books_per_month=MAX_BOOKS_PER_MONTH,
                max_reviews=MAX_REVIEWS,
                headless=HEADLESS,
                time_limit_hours=TIME_LIMIT_HOURS,
            )
        except Exception as e:
            print(f"\n[WARN] 크롤링 중단 ({e.__class__.__name__})")
            print("부분 수집된 데이터가 CSV에 저장됐습니다.")
        else:
            if not reviews_df.empty:
                print("\n리뷰 샘플 (상위 5건):")
                print(
                    reviews_df[['Title', 'ReviewText', 'ReviewRating', 'ReviewDate']]
                    .head(5).to_string(index=False)
                )