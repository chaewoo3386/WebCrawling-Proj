"""
Goodreads 도서 리뷰 크롤러
- 책 제목으로 검색 → 리뷰 수집 → CSV 저장
- Selenium 사용 (리뷰가 JS 렌더링이므로)
"""

import time
import random
import csv
import json
import os
import re
import hashlib
import logging
from dataclasses import dataclass, fields, asdict
from datetime import datetime, timedelta
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    NoSuchElementException, StaleElementReferenceException,
    TimeoutException, WebDriverException,
)
from webdriver_manager.chrome import ChromeDriverManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── 데이터 모델 ───────────────────────────────────────────────────

@dataclass
class Review:
    book_title: str
    book_id: str
    reviewer: str
    rating: Optional[float]   # 1~5, 없으면 None
    date: str
    text: str
    likes: int = 0
    url: str = ""


# ── 탐색 대상 정의 (인기 리스트 / 장르 셸프) ──────────────────────
# 각 항목을 여러 페이지(?page=N)로 펼쳐 수만 권 규모의 큐를 만든다.
# 탐색은 '발견 즉시 크롤링' 방식이라 URL 이 많아도 시작이 지연되지 않으며,
# 아래 _LIST_PAGES / _SHELF_PAGES 값을 키우면 큐가 더 커진다.

# Listopia 리스트 ID (페이지당 약 100권, 인기순 정렬이라 리뷰가 많음)
_BROWSE_LIST_IDS = [
    "1.Best_Books_Ever",
    "264.Books_That_Everyone_Should_Read_At_Least_Once",
    "43.Best_20th_Century_Novels",
    "7.Best_Books_of_the_20th_Century",
    "6.Best_Books_of_the_Decade_2000s",
    "119.Best_Books_of_the_Decade_2010s",
    "152.Best_Young_Adult_Books",
    "50.The_Best_Epic_Fantasy",
    "17.Best_Historical_Fiction",
    "16.Best_Mystery_Thriller_Novels",
    "3810.Best_Self_Help_Books",
    "76.Best_for_Book_Clubs",
    "47.Best_Dystopian_and_Post_Apocalyptic_Fiction",
    "2681.Books_That_Should_Be_Made_Into_Movies",
    "35080.Books_Every_Woman_Should_Read",
    "8166.Best_Romance_Novels",
    "4893.Best_Horror_Novels",
    "767.Best_Nonfiction_of_all_Time",
    "487.Best_Fantasy_Books_of_the_21st_Century",
    "1043.Childhood_Books_Everyone_Should_Read",
]

# 장르/주제 셸프 태그 (페이지당 약 50권)
_BROWSE_SHELF_TAGS = [
    # 대분류
    "fiction", "non-fiction", "classics", "contemporary", "literature",
    "literary-fiction", "novels", "anthologies",
    # 미스터리/스릴러/범죄
    "mystery", "thriller", "suspense", "crime", "true-crime", "detective",
    "noir", "espionage",
    # SF / 판타지
    "science-fiction", "fantasy", "urban-fantasy", "high-fantasy",
    "epic-fantasy", "dark-fantasy", "space-opera", "cyberpunk", "steampunk",
    "dystopia", "post-apocalyptic", "time-travel", "science-fiction-fantasy",
    # 호러 / 초자연
    "horror", "paranormal", "supernatural", "gothic", "vampires", "witches",
    "zombies", "ghosts",
    # 로맨스
    "romance", "contemporary-romance", "historical-romance",
    "paranormal-romance", "romantic-suspense", "chick-lit", "womens-fiction",
    "erotica",
    # 역사 / 전쟁 / 정치
    "history", "historical-fiction", "war", "military-history", "politics",
    "economics",
    # 청소년 / 아동
    "young-adult", "new-adult", "middle-grade", "childrens", "coming-of-age",
    # 논픽션 / 지식
    "biography", "memoir", "autobiography", "philosophy", "psychology",
    "sociology", "anthropology", "self-help", "personal-development",
    "productivity", "leadership", "business", "finance", "money",
    "science", "popular-science", "physics", "mathematics", "biology",
    "astronomy", "nature", "environment", "technology", "education",
    "parenting", "health", "medicine", "cooking", "food",
    # 종교 / 영성
    "spirituality", "religion", "christian", "buddhism", "mythology",
    # 예술 / 문화 / 기타
    "art", "music", "design", "architecture", "photography", "travel",
    "sports", "humor", "essays", "writing", "poetry", "drama", "plays",
    "graphic-novels", "comics", "manga", "short-stories", "fairy-tales",
    "retellings", "lgbt", "feminism",
    # 지역 문학
    "japanese-literature", "russian-literature", "french-literature",
    "american", "british-literature", "asian-literature",
]

# 페이지 깊이 (값을 키우면 큐가 커진다. 탐색은 lazy 라 부담 없음)
_LIST_PAGES = 40
_SHELF_PAGES = 25


def _build_browse_urls() -> list[str]:
    """리스트/셸프를 여러 페이지로 펼친 탐색 URL 목록을 만든다.

    페이지 우선(page-major) 순서라, 초반부터 여러 장르의 책이 골고루
    큐에 들어온다(특정 한 리스트에 치우치지 않음).
    """
    base = "https://www.goodreads.com"
    urls: list[str] = []
    for page in range(1, _LIST_PAGES + 1):
        for lid in _BROWSE_LIST_IDS:
            urls.append(f"{base}/list/show/{lid}?page={page}")
    for page in range(1, _SHELF_PAGES + 1):
        for tag in _BROWSE_SHELF_TAGS:
            urls.append(f"{base}/shelf/show/{tag}?page={page}")
    return urls


# ── 크롤러 ────────────────────────────────────────────────────────

class GoodreadsCrawler:
    BASE = "https://www.goodreads.com"

    def __init__(
        self,
        headless: bool = True,
        delay_range: tuple[float, float] = (2.0, 4.0),
    ):
        self.delay_range = delay_range
        self.driver = self._build_driver(headless)

    # ── 드라이버 ──────────────────────────────────────────────────

    def _build_driver(self, headless: bool) -> webdriver.Chrome:
        opts = Options()
        if headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        opts.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)
        # 느린 페이지가 무한정 매달리지 않도록 로드 타임아웃을 건다.
        # (Selenium↔ChromeDriver 통신 타임아웃 120초보다 작아야, 통신이
        #  끊기는 ReadTimeout 대신 깔끔한 TimeoutException 으로 처리된다.)
        driver.set_page_load_timeout(45)
        driver.set_script_timeout(30)
        driver.execute_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        return driver

    def _wait(self):
        time.sleep(random.uniform(*self.delay_range))

    def quit(self):
        self.driver.quit()

    def _safe_get(self, url: str, retries: int = 2) -> bool:
        """driver.get 을 타임아웃·일시 오류에 견디도록 감쌉니다.

        - 페이지 로드가 page_load_timeout 을 넘으면 로딩을 중단하고
          그때까지 받은 DOM 으로 계속 진행합니다(부분 로드도 보통 쓸 만함).
        - 그 외 WebDriver 오류는 잠시 쉬었다 재시도합니다.
        반환값: 진행 가능 여부(True 면 호출부에서 파싱을 시도해도 됨).
        """
        for attempt in range(1, retries + 1):
            try:
                self.driver.get(url)
                return True
            except TimeoutException:
                log.warning("  페이지 로드 타임아웃 — 부분 로드로 진행: %s", url)
                try:
                    self.driver.execute_script("window.stop();")
                except Exception:
                    pass
                return True
            except WebDriverException as e:
                first_line = (str(e) or "").splitlines()[0] if str(e) else repr(e)
                log.warning("  페이지 로드 오류 (%d/%d): %s — %s",
                            attempt, retries, url, first_line)
                time.sleep(2.0 * attempt)
        log.warning("  페이지 로드 실패(재시도 소진): %s", url)
        return False

    def _extract_book_id(self, href: str) -> str:
        m = re.search(r"/book/show/(\d+)", href or "")
        return m.group(1) if m else ""

    # ── 전체 탐색 (쿼리 없이 인기 목록에서 책 수집) ──────────────

    # 탐색할 Goodreads 인기 리스트/셸프 (여러 페이지로 펼침).
    # 정의·페이지 깊이는 위쪽 _BROWSE_LIST_IDS / _BROWSE_SHELF_TAGS /
    # _LIST_PAGES / _SHELF_PAGES 와 _build_browse_urls() 참조.
    BROWSE_URLS = _build_browse_urls()

    def iter_books(self, max_books: Optional[int] = None):
        """인기 목록/셸프를 순회하며 책을 '발견하는 즉시' 하나씩 내보냅니다(제너레이터).

        책 목록 전체를 미리 다 모으지 않으므로, 탐색 URL 이 수천 개라도
        첫 페이지의 책부터 곧바로 리뷰 수집을 시작할 수 있고, 중간에
        멈춰도 그때까지 크롤링한 책은 보존됩니다.
        max_books=None 이면 제한 없이 계속 발견합니다.
        """
        seen_ids: set[str] = set()
        count = 0

        for url in self.BROWSE_URLS:
            if max_books and count >= max_books:
                return
            log.info("목록 탐색 중: %s", url)
            found: list[dict] = []
            try:
                if not self._safe_get(url):
                    log.warning("  목록 로드 실패 — 건너뜁니다: %s", url)
                    continue
                self._wait()

                # 한 페이지 안에서 스크롤하며 책 로드
                prev_height = 0
                no_change = 0
                while no_change < 3:
                    self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(random.uniform(1.0, 1.6))
                    new_height = self.driver.execute_script("return document.body.scrollHeight")
                    if new_height == prev_height:
                        no_change += 1
                    else:
                        no_change = 0
                    prev_height = new_height

                link_selectors = [
                    "a.bookTitle",
                    "td a[href*='/book/show/']",
                    "div.coverWrapper a[href*='/book/show/']",
                    "article a[href*='/book/show/']",
                ]
                anchors = []
                for sel in link_selectors:
                    anchors = self.driver.find_elements(By.CSS_SELECTOR, sel)
                    if anchors:
                        break

                # href/제목을 먼저 모은다. (yield 도중 페이지를 떠나면
                #  남은 anchor 가 StaleElement 가 되므로 미리 추출)
                for a in anchors:
                    try:
                        href = a.get_attribute("href") or ""
                        title = a.text.strip()
                    except StaleElementReferenceException:
                        continue
                    book_id = self._extract_book_id(href)
                    if not book_id or book_id in seen_ids:
                        continue
                    seen_ids.add(book_id)
                    found.append({
                        "title": title or f"book_{book_id}",
                        "author": "", "book_id": book_id, "url": href,
                    })

                log.info("  이 페이지에서 %d권 발견 (누적 발견 %d권)",
                         len(found), len(seen_ids))
            except Exception as e:
                log.warning("  목록 탐색 중 오류 — 건너뜁니다: %s (%s)", url, e)
                continue

            # 발견한 책을 하나씩 내보낸다 → 호출부가 즉시 크롤링
            for book in found:
                yield book
                count += 1
                if max_books and count >= max_books:
                    return

    def browse_books(self, max_books: Optional[int] = None) -> list[dict]:
        """iter_books 를 리스트로 모아 반환합니다 (하위 호환용)."""
        return list(self.iter_books(max_books))

    # ── 리뷰 수집 ────────────────────────────────────────────────

    # 같은 책에서 별점×정렬 조합을 모두 순회해 노출되는 리뷰를 최대화한다.
    # Goodreads 는 한 필터 뷰당 노출 리뷰 수에 상한이 있으므로,
    # 조합을 늘릴수록 (전체/별점별 × 기본/최신/오래된순) 더 많은 리뷰가 풀린다.
    FILTER_COMBOS: list[tuple[Optional[int], str]] = [
        (None, "default"), (None, "newest"), (None, "oldest"),
        (5, "default"), (5, "newest"), (5, "oldest"),
        (4, "default"), (4, "newest"), (4, "oldest"),
        (3, "default"), (3, "newest"), (3, "oldest"),
        (2, "default"), (2, "newest"), (2, "oldest"),
        (1, "default"), (1, "newest"), (1, "oldest"),
    ]

    def get_reviews(
        self,
        book_id: str,
        book_title: str = "",
        max_per_book: Optional[int] = None,
    ) -> list[Review]:
        """
        책의 리뷰 전용 페이지를 별점·정렬 필터별로 순회하며 리뷰를 수집합니다.
        같은 책이라도 필터가 달라지면 노출되는 리뷰가 달라지므로 훨씬 많이 모입니다.
        """
        # 책 제목 확보 (전달받지 못한 경우 메인 페이지에서 가져옴)
        if not book_title:
            self._safe_get(f"{self.BASE}/book/show/{book_id}")
            self._wait()
            try:
                book_title = self.driver.find_element(
                    By.CSS_SELECTOR, "h1[data-testid='bookTitle'], h1.Text__title1"
                ).text.strip()
            except NoSuchElementException:
                book_title = f"book_{book_id}"

        reviews: list[Review] = []
        seen_texts: set[str] = set()

        for rating, sort in self.FILTER_COMBOS:
            if max_per_book and len(reviews) >= max_per_book:
                break

            before = len(reviews)
            self._load_reviews_page(book_id, rating=rating, sort=sort)
            self._collect_by_scrolling(
                book_id, book_title, reviews, seen_texts, max_per_book,
                rating_hint=rating,
            )
            log.info(
                "  필터(rating=%s, sort=%s) → +%d개 (누적 %d개)",
                rating if rating else "all", sort, len(reviews) - before, len(reviews),
            )

        return reviews

    def _load_reviews_page(
        self, book_id: str, rating: Optional[int] = None, sort: str = "default"
    ):
        """리뷰 전용 페이지를 로드하고 필터/정렬을 적용합니다."""
        url = f"{self.BASE}/book/show/{book_id}/reviews"
        params: list[str] = []
        if sort and sort != "default":
            params.append(f"sort={sort}")
        if rating:
            params.append(f"rating={rating}")
        if params:
            url += "?" + "&".join(params)

        log.info("리뷰 페이지 로드: %s", url)
        if not self._safe_get(url):
            return
        self._wait()

        # URL 파라미터가 무시되는 경우를 대비해 UI 버튼으로도 시도
        if rating:
            self._click_rating_filter(rating)
        if sort and sort != "default":
            self._click_sort_option(sort)

    def _click_rating_filter(self, rating: int):
        """별점 필터 버튼 클릭. 셀렉터가 변할 수 있어 여러 패턴을 시도."""
        candidates = [
            f"button[aria-label*='{rating} star']",
            f"button[aria-label*='{rating}-star']",
            f"button[data-testid='rating-filter-{rating}']",
            f"div[role='button'][aria-label*='{rating} star']",
            f"label[aria-label*='{rating} star'] button",
        ]
        for sel in candidates:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, sel)
                self.driver.execute_script("arguments[0].click();", btn)
                time.sleep(1.5)
                return
            except NoSuchElementException:
                continue

    def _click_sort_option(self, sort: str):
        """정렬 옵션 변경. 드롭다운을 열고 항목을 찾아 클릭."""
        for sel in [
            "button[data-testid='reviewsSort']",
            "button[aria-label*='Sort']",
            "div.ReviewsSort button",
            "button[class*='Sort']",
        ]:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, sel)
                self.driver.execute_script("arguments[0].click();", btn)
                time.sleep(0.6)
                break
            except NoSuchElementException:
                continue

        label = {"newest": "newest", "oldest": "oldest", "default": "default"}.get(
            sort, sort
        )
        try:
            opts = self.driver.find_elements(
                By.CSS_SELECTOR,
                "li[role='menuitem'], div[role='menuitem'], button[role='menuitem'], "
                "div[role='menu'] button, ul[role='menu'] li",
            )
            for opt in opts:
                if label in (opt.text or "").lower():
                    self.driver.execute_script("arguments[0].click();", opt)
                    time.sleep(1.5)
                    return
        except Exception:
            pass

    def _collect_by_scrolling(
        self,
        book_id: str,
        book_title: str,
        reviews: list[Review],
        seen: set[str],
        max_per_book: Optional[int] = None,
        rating_hint: Optional[int] = None,
    ):
        """현재 페이지에서 스크롤·'더 보기' 클릭을 반복하며 리뷰를 누적합니다.

        rating_hint 가 주어지면 (별점 필터 안이라는 의미), DOM 파싱이 실패한
        리뷰의 rating 을 해당 값으로 채워 별점 누락을 줄입니다.
        """
        no_change_streak = 0
        stagnant_count_streak = 0
        last_count = len(reviews)

        while True:
            if max_per_book and len(reviews) >= max_per_book:
                return

            new_reviews = self._parse_reviews_on_page(book_id, book_title, seen)
            if rating_hint is not None:
                for r in new_reviews:
                    if r.rating is None:
                        r.rating = float(rating_hint)
            reviews.extend(new_reviews)

            prev_height = self.driver.execute_script("return document.body.scrollHeight")
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(random.uniform(1.8, 2.8))
            self._click_show_more()
            new_height = self.driver.execute_script("return document.body.scrollHeight")

            # 높이 변화 + 리뷰 개수 변화를 둘 다 추적
            if new_height == prev_height:
                no_change_streak += 1
            else:
                no_change_streak = 0

            if len(reviews) == last_count:
                stagnant_count_streak += 1
            else:
                stagnant_count_streak = 0
            last_count = len(reviews)

            # 4번 연속 높이 변화 없거나, 6번 연속 리뷰 증가 없으면 종료
            if no_change_streak >= 4 or stagnant_count_streak >= 6:
                return

    def _parse_reviews_on_page(
        self, book_id: str, book_title: str, seen: set[str]
    ) -> list[Review]:
        """현재 페이지에서 리뷰 파싱."""
        found = []

        # Goodreads 의 리뷰 카드 셀렉터 (2024-2025 구조)
        selectors = [
            "article.ReviewCard",
            "div.Review",
            "div[class*='ReviewCard']",
            "section.ReviewsList article",
        ]
        cards = []
        for sel in selectors:
            cards = self.driver.find_elements(By.CSS_SELECTOR, sel)
            if cards:
                break

        for card in cards:
            try:
                review = self._parse_card(card, book_id, book_title)
                if review and review.text not in seen and len(review.text) > 20:
                    seen.add(review.text)
                    found.append(review)
            except StaleElementReferenceException:
                continue

        return found

    def _parse_card(self, card, book_id: str, book_title: str) -> Optional[Review]:
        # ── 리뷰어 이름 ──
        reviewer = ""
        for sel in [
            "div.ReviewerProfile__name",
            "span[class*='ReviewerName']",
            "a[href*='/user/show/']",
        ]:
            try:
                reviewer = card.find_element(By.CSS_SELECTOR, sel).text.strip()
                if reviewer:
                    break
            except NoSuchElementException:
                pass

        # ── 별점 ──
        rating = None
        for sel in [
            "span.RatingStars",
            "div[class*='RatingStars']",
            "span[class*='stars']",
        ]:
            try:
                el = card.find_element(By.CSS_SELECTOR, sel)
                aria = el.get_attribute("aria-label") or ""
                m = re.search(r"(\d+(?:\.\d+)?)\s*(out of|/)\s*5", aria, re.I)
                if not m:
                    m = re.search(r"(\d+(?:\.\d+)?)", aria)
                if m:
                    rating = float(m.group(1))
                    break
            except NoSuchElementException:
                pass

        # ── 날짜 ──
        date = ""
        for sel in [
            "span.Text__body3",
            "div[class*='ReviewDate']",
            "span[class*='date']",
            "time",
        ]:
            try:
                date = card.find_element(By.CSS_SELECTOR, sel).text.strip()
                if date:
                    break
            except NoSuchElementException:
                pass

        # ── 리뷰 본문 ──
        text = ""
        # "더 읽기" 펼치기
        for btn_sel in ["button[aria-label*='more']", "button.Truncated__truncButton"]:
            try:
                btn = card.find_element(By.CSS_SELECTOR, btn_sel)
                self.driver.execute_script("arguments[0].click();", btn)
                time.sleep(0.3)
            except NoSuchElementException:
                pass

        for sel in [
            "div.ReviewText__content",
            "div[class*='reviewText']",
            "div[data-testid='reviewText']",
            "section[class*='ReviewText']",
            "span.Formatted",
        ]:
            try:
                text = card.find_element(By.CSS_SELECTOR, sel).text.strip()
                if text:
                    break
            except NoSuchElementException:
                pass

        if not text:
            return None

        # ── 좋아요 수 ──
        likes = 0
        for sel in ["div[class*='SocialFooter'] button", "span[class*='like']"]:
            try:
                raw = card.find_element(By.CSS_SELECTOR, sel).text.strip()
                m = re.search(r"\d+", raw)
                if m:
                    likes = int(m.group())
                    break
            except NoSuchElementException:
                pass

        return Review(
            book_title=book_title,
            book_id=book_id,
            reviewer=reviewer,
            rating=rating,
            date=date,
            text=text,
            likes=likes,
            url=f"https://www.goodreads.com/book/show/{book_id}",
        )

    def _click_show_more(self):
        """'리뷰 더 보기' / 'Show more reviews' 버튼이 있으면 모두 클릭."""
        clicked = False
        for sel in [
            "button[data-testid='loadMoreReviews']",
            "button[data-testid='loadMore']",
            "a.actionLinkLite.votes.loadingLink",
            "button.Button--secondary",
            "button.Button--full",
            "span.Button__labelItem",
        ]:
            try:
                btns = self.driver.find_elements(By.CSS_SELECTOR, sel)
                for btn in btns:
                    label = (btn.text or "").lower()
                    if any(k in label for k in ("more review", "show more", "load more", "more")):
                        try:
                            self.driver.execute_script("arguments[0].click();", btn)
                            clicked = True
                            time.sleep(0.8)
                        except Exception:
                            continue
            except Exception:
                pass
        if clicked:
            time.sleep(1.0)


# ── 중복 제거 ────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """공백·대소문자 정규화."""
    return re.sub(r"\s+", " ", text.lower().strip())


def _text_hash(text: str) -> str:
    return hashlib.md5(_normalize(text).encode()).hexdigest()


class Deduper:
    """누적 중복 제거기.

    이미 본 리뷰의 키를 기억해 두고, 새로 들어온 리뷰 중 아직 보지 못한
    것만 통과시킵니다. 같은 실행 안은 물론, 기존 출력 파일을 seed 하면
    이전 실행 결과와도 중복을 제거합니다.

    중복 판정 기준 (셋 중 하나라도 걸리면 중복, 먼저 나온 리뷰를 유지):
      1. 같은 책(book_id) + 같은 리뷰어(reviewer)
      2. 같은 책(book_id) + 본문 MD5 해시 동일
      3. 같은 책(book_id) + 본문 앞 150자 동일 (잘린 텍스트 등 유사 중복)
    """

    def __init__(self):
        self.seen_reviewer: set[tuple[str, str]] = set()
        self.seen_hash: set[tuple[str, str]] = set()
        self.seen_prefix: set[tuple[str, str]] = set()

    def _check_and_register(self, r: Review) -> bool:
        """r 이 중복이면 True. 처음 보는 리뷰면 키를 등록하고 False 반환."""
        key_reviewer = (r.book_id, _normalize(r.reviewer)) if r.reviewer else None
        key_hash = (r.book_id, _text_hash(r.text))
        key_prefix = (r.book_id, _normalize(r.text)[:150])

        if (
            (key_reviewer and key_reviewer in self.seen_reviewer)
            or key_hash in self.seen_hash
            or key_prefix in self.seen_prefix
        ):
            return True

        if key_reviewer:
            self.seen_reviewer.add(key_reviewer)
        self.seen_hash.add(key_hash)
        self.seen_prefix.add(key_prefix)
        return False

    def filter_new(self, reviews: list[Review]) -> list[Review]:
        """아직 보지 못한 리뷰만 골라 반환하고, 그 키를 등록합니다."""
        return [r for r in reviews if not self._check_and_register(r)]

    def seed_from_csv(self, path: str) -> int:
        """기존 CSV 리뷰들을 '이미 본' 것으로 등록합니다. 등록한 행 수 반환."""
        if not os.path.exists(path):
            return 0
        n = 0
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                self._check_and_register(Review(
                    book_title=row.get("book_title", ""),
                    book_id=row.get("book_id", ""),
                    reviewer=row.get("reviewer", ""),
                    rating=None,
                    date=row.get("date", ""),
                    text=row.get("text", ""),
                ))
                n += 1
        return n


def deduplicate_reviews(reviews: list[Review]) -> list[Review]:
    """리스트 내부의 중복을 제거합니다 (먼저 나온 리뷰를 유지)."""
    unique = Deduper().filter_new(reviews)
    log.info("중복 제거: %d건 제거 → %d건 남음", len(reviews) - len(unique), len(unique))
    return unique


def deduplicate_csv(input_path: str, output_path: Optional[str] = None) -> int:
    """
    저장된 CSV 파일을 읽어 중복을 제거한 뒤 다시 저장합니다.
    output_path 가 None 이면 원본 파일을 덮어씁니다.
    반환값: 제거된 행 수
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {input_path}")

    with open(input_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    before = len(rows)
    reviews = [
        Review(
            book_title=row.get("book_title", ""),
            book_id=row.get("book_id", ""),
            reviewer=row.get("reviewer", ""),
            rating=float(row["rating"]) if row.get("rating") else None,
            date=row.get("date", ""),
            text=row.get("text", ""),
            likes=int(row["likes"]) if row.get("likes") else 0,
            url=row.get("url", ""),
        )
        for row in rows
    ]

    unique = deduplicate_reviews(reviews)
    out = output_path or input_path
    save_to_csv(unique, out)
    return before - len(unique)


# ── 크롤링 완료 책 목록 관리 ─────────────────────────────────────

class BookRegistry:
    """
    이미 크롤링한 book_id 를 파일로 기록·조회합니다.
    프로그램을 다시 실행해도 같은 책은 건너뜁니다.
    """

    def __init__(self, path: str = "crawled_books.json"):
        self.path = path
        self._data: dict[str, str] = self._load()  # {book_id: book_title}

    def _load(self) -> dict[str, str]:
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def already_crawled(self, book_id: str) -> bool:
        return book_id in self._data

    def mark_done(self, book_id: str, book_title: str):
        self._data[book_id] = book_title
        self._save()

    def list_crawled(self) -> dict[str, str]:
        return dict(self._data)


# ── CSV / JSON 저장 ───────────────────────────────────────────────

def save_to_csv(reviews: list[Review], path: str):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[fd.name for fd in fields(Review)])
        writer.writeheader()
        writer.writerows(asdict(r) for r in reviews)
    log.info("CSV 저장 완료: %s (%d건)", path, len(reviews))


def save_to_json(reviews: list[Review], path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in reviews], f, ensure_ascii=False, indent=2)
    log.info("JSON 저장 완료: %s (%d건)", path, len(reviews))


def append_to_csv(reviews: list[Review], path: str):
    """기존 CSV 에 행을 추가합니다. 파일이 없으면 새로 만듭니다."""
    write_header = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[fd.name for fd in fields(Review)])
        if write_header:
            writer.writeheader()
        writer.writerows(asdict(r) for r in reviews)


def append_to_json(reviews: list[Review], path: str):
    """기존 JSON 배열에 항목을 추가합니다. 파일이 없으면 새로 만듭니다."""
    existing: list[dict] = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, ValueError):
            existing = []
    existing.extend(asdict(r) for r in reviews)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def flush_reviews(
    reviews: list[Review], csv_path: str, json_path: str,
    label: str = "", deduper: Optional["Deduper"] = None,
) -> int:
    """중복 제거 후 CSV·JSON 에 즉시 추가 저장합니다.

    deduper 가 주어지면 기존 파일·이전 책들과의 중복까지 걸러내므로,
    같은 책을 다시 크롤링해도 파일에 중복이 쌓이지 않습니다.
    실제로 저장된(새로운) 리뷰 수를 반환합니다.
    """
    if not reviews:
        return 0
    unique = deduper.filter_new(reviews) if deduper else deduplicate_reviews(reviews)
    if not unique:
        log.info("저장 생략%s: 모두 기존 리뷰와 중복", f" [{label}]" if label else "")
        return 0
    append_to_csv(unique, csv_path)
    append_to_json(unique, json_path)
    log.info("저장 완료%s: %d건 → %s / %s", f" [{label}]" if label else "", len(unique), csv_path, json_path)
    return len(unique)


# ── 메인 ─────────────────────────────────────────────────────────

def main():
    import argparse

    # 스크립트가 있는 폴더를 기준으로 기본 저장 경로 설정
    here = os.path.dirname(os.path.abspath(__file__))

    parser = argparse.ArgumentParser(description="Goodreads 도서 리뷰 크롤러")
    parser.add_argument(
        "--books", type=int, default=None,
        help="수집할 최대 책 수 (기본: 제한 없음, 모든 목록 전체 수집)"
    )
    parser.add_argument(
        "--out-csv", default=os.path.join(here, "reviews.csv"), help="CSV 출력 경로"
    )
    parser.add_argument(
        "--out-json", default=os.path.join(here, "reviews.json"), help="JSON 출력 경로"
    )
    parser.add_argument(
        "--time-limit", type=float, default=24.0,
        help="최대 실행 시간(시간 단위, 기본 24시간)"
    )
    parser.add_argument(
        "--max-per-book", type=int, default=None,
        help="책 한 권당 수집할 최대 리뷰 수 (기본: 제한 없음)"
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="이미 크롤링한 책도 다시 방문해 추가 리뷰를 수집합니다 (강화된 필터 전략)"
    )
    parser.add_argument(
        "--no-headless", action="store_true", help="브라우저 창 표시"
    )
    parser.add_argument(
        "--dedup-csv", metavar="FILE",
        help="크롤링 없이 기존 CSV 파일의 중복만 제거합니다"
    )
    parser.add_argument(
        "--registry", default=os.path.join(here, "crawled_books.json"),
        help="크롤링 완료 책 목록 파일 경로"
    )
    parser.add_argument(
        "--list-crawled", action="store_true",
        help="이미 크롤링된 책 목록을 출력하고 종료합니다"
    )
    args = parser.parse_args()

    registry = BookRegistry(args.registry)

    # ── 크롤링 완료 목록 조회 모드 ───────────────────────────────
    if args.list_crawled:
        crawled = registry.list_crawled()
        if crawled:
            print(f"크롤링 완료된 책 ({len(crawled)}권):")
            for bid, title in crawled.items():
                print(f"  [{bid}] {title}")
        else:
            print("아직 크롤링된 책이 없습니다.")
        return

    # ── 기존 CSV 중복 제거 모드 ───────────────────────────────────
    if args.dedup_csv:
        removed = deduplicate_csv(args.dedup_csv)
        print(f"중복 제거 완료: {removed}건 삭제 → {args.dedup_csv}")
        return

    # ── 크롤링 모드 ───────────────────────────────────────────────
    deadline = datetime.now() + timedelta(hours=args.time_limit)
    log.info("제한 시간: %s시간 → %s 까지", args.time_limit, deadline.strftime("%Y-%m-%d %H:%M:%S"))

    # 기존 출력 파일을 읽어 '이미 가진 리뷰' 를 중복 기준에 등록.
    # 이후 저장 단계에서 이 기준과 비교해, 같은 책을 다시 크롤링해도
    # 중복 리뷰가 파일에 쌓이지 않는다 (별도 중복 제거 명령 불필요).
    deduper = Deduper()
    seeded = deduper.seed_from_csv(args.out_csv)
    if seeded:
        log.info("기존 리뷰 %d건을 중복 제거 기준에 등록했습니다.", seeded)

    crawler = GoodreadsCrawler(headless=not args.no_headless)

    total = 0
    timed_out = False
    interrupted = False
    try:
        log.info("인기 목록에서 책을 발견하는 즉시 크롤링합니다.")
        for book in crawler.iter_books(args.books):
            if datetime.now() >= deadline:
                log.warning("시간 제한 도달 — 크롤링을 중단합니다.")
                timed_out = True
                break

            if registry.already_crawled(book["book_id"]) and not args.refresh:
                log.info("건너뜀 (이미 수집됨): [%s]", book["title"])
                continue

            log.info("=== [%s] by %s ===", book["title"], book["author"])
            try:
                reviews = crawler.get_reviews(
                    book["book_id"], book["title"], max_per_book=args.max_per_book
                )
            except KeyboardInterrupt:
                log.warning("사용자 중단 — 현재까지 수집한 리뷰를 저장합니다.")
                interrupted = True
                break
            except Exception as e:
                log.warning("책 처리 중 오류 — 건너뜁니다: [%s] (%s)", book["title"], e)
                continue

            # 책 한 권이 끝날 때마다 즉시 저장 (기존 파일과 중복은 자동 제외)
            saved = flush_reviews(
                reviews, args.out_csv, args.out_json, book["title"], deduper=deduper
            )
            registry.mark_done(book["book_id"], book["title"])
            total += saved
            log.info("  → 새 리뷰 %d개 저장 (수집 %d개 중, 누적 %d개)",
                     saved, len(reviews), total)
            time.sleep(random.uniform(3, 6))

    except KeyboardInterrupt:
        log.warning("사용자 중단 (Ctrl+C) — 저장된 데이터는 보존됩니다.")
        interrupted = True
    finally:
        crawler.quit()

    if timed_out:
        print(f"\n총 {total}개 리뷰 수집 후 시간 초과로 중단.")
    elif interrupted:
        print(f"\n총 {total}개 리뷰 수집 후 중단.")
    else:
        print(f"\n총 {total}개 리뷰 수집 완료.")


if __name__ == "__main__":
    main()
