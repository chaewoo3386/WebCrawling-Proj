"""
Yes24 베스트셀러 + 리뷰 크롤러 (v3)
감성분석용 데이터셋 구축 (책 메타데이터 + 개별 리뷰 텍스트/별점/날짜)
 
변경점 (v2 → v3)
----------------
- max_books_per_month 가 "신규 크롤링 대상 책 수" 를 의미하도록 변경
  (이미 수집한 책은 카운트에서 제외, 부족하면 다음 페이지 가져옴)
- 신규 N권을 채우거나 베스트셀러 페이지가 끝날 때까지 페이지 확장
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
MAX_PAGE_LIMIT = 50   # 베스트셀러 페이지 확장 안전 한계 (50페이지 = 1200권)
 
# ── Yes24 국내도서 분야별 categoryNumber ──────────────────────────────
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
    """리뷰 텍스트 정제 - KoNLPy / Mecab / Kiwi / transformers 입력용"""
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
    """Yes24 별점 클래스 → 숫자 (2점 단위: 10, 8, 6, 4, 2)"""
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
    """부분 수집 데이터를 CSV 로 저장"""
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
    """div.reviewInfoGrp 에서 Yes24 리뷰 수집"""
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
 
 
# ── 리뷰 수집 메인 함수 ───────────────────────────────────────────────
def scrape_book_reviews(driver, book_url, max_reviews=None):
    """Yes24 책 상세 페이지에서 리뷰 수집"""
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
 
 
# ── 베스트셀러 파싱 ───────────────────────────────────────────────────
def parse_books(soup, year, month=None, category='국내도서 전체'):
    """베스트셀러 페이지에서 책 메타데이터 + 상세 URL 파싱"""
    books = []
    book_items = soup.select('ul.sGLi > li')
 
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
            auth_tag = item.select_one('span.info_auth')
            if auth_tag:
                author = auth_tag.get_text(separator=' ').strip()
 
            publisher = "N/A"
            pub_tag = item.select_one('span.info_pub a')
            if pub_tag:
                publisher = pub_tag.text.strip()
 
            pub_date = "N/A"
            date_tag = item.select_one('span.info_date')
            if date_tag:
                pub_date = date_tag.text.strip()
 
            price = "N/A"
            price_tag = item.select_one('div.info_price strong.txt_num em.yes_b')
            if price_tag:
                price = price_tag.text.strip() + '원'
 
            rating_raw = ""
            rating_tag = item.select_one('span.rating_grade em.yes_b')
            if rating_tag:
                rating_raw = rating_tag.text.strip()
            try:
                rating = float(rating_raw)
            except Exception:
                rating = None
 
            review_count = 0
            review_tag = item.select_one('span.rating_rvCount em.txC_blue')
            if review_tag:
                m = re.search(r'([\d,]+)', review_tag.text)
                if m:
                    review_count = int(m.group(1).replace(',', ''))
 
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
 
 
def _build_bestseller_url(period_type, cat_num, year, month, page):
    """베스트셀러 URL 생성"""
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
 
 
def _fetch_bestseller_page(driver, period_type, cat_num, year, month, page, cat_name):
    """베스트셀러 1페이지 가져와서 책 리스트 반환"""
    url = _build_bestseller_url(period_type, cat_num, year, month, page)
    driver.get(url)
    time.sleep(random.uniform(3, 5))
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    return parse_books(soup, year, month, cat_name)
 
 
# ── 베스트셀러 + 리뷰 통합 크롤러 (v3) ──────────────────────────────
def scrape_yes24_with_reviews(
    start_year, end_year,
    period_type='mo',
    category_numbers=None,
    target_new_books_per_month=200,
    max_reviews=None,
    headless=True,
    books_csv='yes24_books_metadata.csv',
    reviews_csv='yes24_book_reviews.csv',
    time_limit_hours=12,
):
    """
    베스트셀러 목록 + 각 책의 리뷰 통합 크롤링 (v3)
 
    핵심 변경
    ---------
    - target_new_books_per_month: "신규 크롤링 책 수"
    - 이미 수집한 책은 카운트에서 제외 → 부족하면 다음 페이지 가져와서 채움
    - 베스트셀러 페이지가 비거나 MAX_PAGE_LIMIT 도달까지 확장
    """
    if category_numbers is None:
        category_numbers = {'국내도서 전체': '001'}
 
    driver = init_driver(headless=headless)
 
    review_cols = ['Title', 'Author', 'Category', 'Year', 'Month',
                   'ReviewText', 'ReviewRating', 'ReviewDate', 'ReviewType', 'BookURL']
 
    # 기존 CSV 로드 (이어하기 지원)
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
 
    # 이미 수집한 (BookURL, Year) 추적
    collected_book_years = set()
    for r in all_reviews:
        url = r.get('BookURL')
        yr = r.get('Year')
        if url and yr is not None:
            try:
                collected_book_years.add((url, int(yr)))
            except (ValueError, TypeError):
                pass
    if collected_book_years:
        print(f"[이어하기] 이미 수집된 (책,연도) 쌍 {len(collected_book_years)}건")
 
    # 시간 제한
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
 
                    # ── 신규 N권 채울 때까지 페이지 확장 ──────────────
                    period_books_all = []   # 이번 기간 본 모든 책 (메타데이터 저장용)
                    new_books_queue = []    # 신규 크롤링 대상 (스킵 안 한 책)
                    seen_urls_this_period = set()  # 같은 기간 내 중복 방지
                    page = 0
 
                    while len(new_books_queue) < target_new_books_per_month:
                        if _check_time():
                            stop_flag = True
                            break
                        page += 1
                        if page > MAX_PAGE_LIMIT:
                            print(f"  [{label}][{cat_name}] 페이지 한계 {MAX_PAGE_LIMIT} 도달")
                            break
 
                        driver = _ensure_driver(driver, headless)
                        page_books = _fetch_bestseller_page(
                            driver, period_type, cat_num, year, month, page, cat_name
                        )
                        if not page_books:
                            print(f"  [{label}][{cat_name}] 페이지 {page}: 책 없음 → 종료")
                            break
 
                        period_books_all.extend(page_books)
 
                        # 신규 책만 큐에 추가
                        for b in page_books:
                            url = b.get('BookURL', '')
                            if not url or url == BASE_URL:
                                continue
                            if url in seen_urls_this_period:
                                continue  # 같은 기간 페이지 내 중복 방지
                            seen_urls_this_period.add(url)
 
                            # 이미 같은 연도에 수집한 책은 큐에서 제외
                            if (url, year) in collected_book_years:
                                continue
                            new_books_queue.append(b)
 
                            if len(new_books_queue) >= target_new_books_per_month:
                                break
 
                        time.sleep(random.uniform(1, 2))
 
                    # 메타데이터 누적
                    all_books.extend(period_books_all)
 
                    if stop_flag:
                        break
 
                    target_books = new_books_queue[:target_new_books_per_month]
                    print(
                        f"  [{label}][{cat_name}] 페이지 {page}p 탐색 / "
                        f"신규 대상 {len(target_books)}권 확보 "
                        f"(전체 본 책: {len(period_books_all)}권)"
                    )
 
                    # ── 리뷰 수집 ───────────────────────────────────
                    new_reviews = 0
                    crawled = 0
 
                    for book in tqdm(target_books, desc=f"{label} {cat_name}", leave=False):
                        if _check_time():
                            stop_flag = True
                            break
                        book_url = book.get('BookURL', '')
                        if book.get('ReviewCount', 0) == 0:
                            continue  # 리뷰 없는 책 건너뜀
 
                        # 안전망: 큐 만든 이후 다른 카테고리에서 수집했을 수도 있으니 재확인
                        key = (book_url, year)
                        if key in collected_book_years:
                            continue
 
                        driver = _ensure_driver(driver, headless)
                        raw_reviews = scrape_book_reviews(
                            driver, book_url, max_reviews=max_reviews
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
                                'BookURL':      book_url,
                            })
                        new_reviews += len(raw_reviews)
                        crawled += 1
                        collected_book_years.add(key)
 
                        _save_partial(all_books, all_reviews, books_csv, reviews_csv)
                        time.sleep(random.uniform(2, 4))
 
                    elapsed_min = (time.time() - start_time) / 60
                    remain_min = _time_left() / 60
                    print(
                        f"  [{label}][{cat_name}] 크롤링 {crawled}권 | "
                        f"리뷰 {new_reviews}건 | 누적 리뷰: {len(all_reviews)}건 | "
                        f"경과 {elapsed_min:.1f}분 / 남은시간 {remain_min:.1f}분"
                    )
 
    finally:
        try:
            driver.quit()
        except Exception:
            pass
        if all_books or all_reviews:
            _save_partial(all_books, all_reviews, books_csv, reviews_csv)
 
    # ── 최종 DataFrame 정리 ─────────────────────────────────────────
    books_df = pd.DataFrame(all_books)
    if not books_df.empty:
        books_df = books_df.drop_duplicates(
            subset=['Title', 'Author', 'Year', 'Month']
        ).reset_index(drop=True)
 
    reviews_df = (
        pd.DataFrame(all_reviews, columns=review_cols)
        if all_reviews
        else pd.DataFrame(columns=review_cols)
    )
    if not reviews_df.empty:
        reviews_df = reviews_df[
            reviews_df['ReviewText'].str.len() > 0
        ].drop_duplicates(
            subset=['BookURL', 'ReviewText']
        ).reset_index(drop=True)
        reviews_df['ReviewRating'] = pd.to_numeric(
            reviews_df['ReviewRating'], errors='coerce'
        )
 
    books_df.to_csv(books_csv, index=False, encoding='utf-8-sig')
    reviews_df.to_csv(reviews_csv, index=False, encoding='utf-8-sig')
    print(f"\n최종 저장 완료!")
    print(f"  {books_csv}  : {len(books_df):,}건")
    print(f"  {reviews_csv}: {len(reviews_df):,}건")
 
    return books_df, reviews_df
 
 
# ── 실행 진입점 ───────────────────────────────────────────────────────
if __name__ == "__main__":
    TARGET_CATEGORIES = {
        '국내도서 전체': '001',
    }
    START_YEAR                   = 2022
    END_YEAR                     = 2020
    PERIOD_TYPE                  = 'mo'
    TARGET_NEW_BOOKS_PER_MONTH   = 200   # 월별 신규 크롤링 책 수 (스킵된 책 제외)
    MAX_REVIEWS                  = None
    TIME_LIMIT_HOURS             = 12
    HEADLESS                     = True
 
    print("=" * 55)
    print("Yes24 크롤링 시작 (v3 - 신규 N권 보장)")
    print(f"기간: {END_YEAR}~{START_YEAR}년 / 주기: {PERIOD_TYPE}")
    print(f"월별 신규 책: {TARGET_NEW_BOOKS_PER_MONTH}권 / 책당 리뷰: {MAX_REVIEWS}건")
    print("=" * 55)
 
    try:
        books_df, reviews_df = scrape_yes24_with_reviews(
            start_year=START_YEAR,
            end_year=END_YEAR,
            period_type=PERIOD_TYPE,
            category_numbers=TARGET_CATEGORIES,
            target_new_books_per_month=TARGET_NEW_BOOKS_PER_MONTH,
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