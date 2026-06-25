# -*- coding: utf-8 -*-
"""
도서 인사이트 서비스용 사전계산 인덱스 생성 (1회 배치).

예측 결과 CSV(이미 감성·평점 있음)를 책 단위로 집계하고,
긍정/부정 리뷰에서 '왜 좋고 나빴는지' 키워드를 Okt 명사 빈도(대비)로 추출한다.
재학습 없음 — 통계/형태소 빈도만 사용.

출력: insight_data.pkl  { 'books': DataFrame, 'year_trend': DF, 'category_trend': DF }
실행: python build_book_index.py   (수 분~십수 분 소요 → 백그라운드 권장)
"""
import os
import re
import pickle
import time
from collections import Counter

import numpy as np
import pandas as pd
from konlpy.tag import Okt

BASE = os.path.dirname(os.path.abspath(__file__))
CAP = 150          # 책별 키워드 추출 시 그룹당 최대 리뷰 수(속도)
MIN_KW = 10        # 키워드를 뽑을 최소 리뷰 수
MIN_DF = 2         # 키워드가 등장해야 하는 최소 리뷰 수(그룹 내)
TOPK = 6

okt = Okt()

STOP = set("""
것 거 게 수 등 점 분 줄 데 때 말 면 중 후 전 안 위 속 듯 뿐 채 만 별 더 좀 잘 못 다 또 왜 뭐
이 그 저 이거 그거 저거 여기 거기 저기 누구 무엇 자신 자기 우리 저희 당신 너 나 내 또한 거기
정도 느낌 사람 부분 동안 때문 정말 진짜 그냥 약간 조금 매우 모두 다들 가장 거의 역시 너무 다시 일단
책 내용 이야기 작가 소설 글 작품 독자 페이지 권 장 줄거리 제목 서평 리뷰 평점 별점 저자 출판 출간
번 개 명 년 월 일 시간 정 분들 위해 통해 대해 관련 경우 자체 무언가 모습 부담 누군가 어디 언제
""".split())


def nouns(text):
    try:
        return [w for w in okt.nouns(str(text)) if len(w) >= 2 and w not in STOP]
    except Exception:
        return []


def doc_freq(texts):
    """리뷰 단위 문서빈도(한 리뷰에서 같은 단어는 1회) Counter, 리뷰 수"""
    c = Counter()
    n = 0
    for t in texts:
        n += 1
        for w in set(nouns(t)):
            c[w] += 1
    return c, n


def contrastive_keywords(pos_texts, neg_texts):
    pc, pn = doc_freq(pos_texts)
    nc, nn = doc_freq(neg_texts)
    pr = {w: pc[w] / pn for w in pc} if pn else {}
    nr = {w: nc[w] / nn for w in nc} if nn else {}
    vocab = set(pr) | set(nr)
    pos_s, neg_s = [], []
    for w in vocab:
        p, q = pr.get(w, 0.0), nr.get(w, 0.0)
        if pc.get(w, 0) >= MIN_DF:
            pos_s.append((w, p - q, pc[w]))
        if nc.get(w, 0) >= MIN_DF:
            neg_s.append((w, q - p, nc[w]))
    pos_s.sort(key=lambda x: (x[1], x[2]), reverse=True)
    neg_s.sort(key=lambda x: (x[1], x[2]), reverse=True)
    pos_kw = [w for w, s, _ in pos_s if s > 0][:TOPK]
    neg_kw = [w for w, s, _ in neg_s if s > 0][:TOPK]
    if not pos_kw and pn:
        pos_kw = [w for w, _ in pc.most_common(TOPK)]
    if not neg_kw and nn:
        neg_kw = [w for w, _ in nc.most_common(TOPK)]
    return pos_kw, neg_kw


def pick_sample(sub):
    s = sub["review"].dropna().astype(str)
    s = s[s.str.strip() != ""]
    mid = s[s.str.len().between(20, 160)]
    if len(mid):
        return mid.iloc[0]
    if len(s):
        return s.iloc[0][:160]
    return ""


def load_all():
    frames = []
    y = os.path.join(BASE, "result_yes24_book_reviews.csv")
    if os.path.exists(y):
        d = pd.read_csv(y, usecols=["Title", "Author", "Category", "Year",
                                    "ReviewText", "ReviewRating", "sentiment"],
                        encoding="utf-8-sig")
        d = d.rename(columns={"Title": "title", "Author": "author", "Category": "category",
                              "Year": "year", "ReviewText": "review", "ReviewRating": "rating"})
        frames.append(d)
    w = os.path.join(BASE, "result_watcha_book_comments.csv")
    if os.path.exists(w):
        d = pd.read_csv(w, usecols=["book_title", "author", "category", "comment", "sentiment"],
                        encoding="utf-8-sig")
        d = d.rename(columns={"book_title": "title", "comment": "review"})
        d["rating"] = np.nan
        d["year"] = np.nan
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    df = df[df["title"].notna()].copy()
    df["title"] = df["title"].astype(str).str.strip()
    df["title"] = df["title"].str.replace(r"\s*\(\d{4}\)\s*$", "", regex=True).str.strip()
    df = df[df["title"] != ""]
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce")
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df["sentiment"] = df["sentiment"].fillna("중립")
    df["category"] = df["category"].fillna("기타").astype(str).str.strip()
    return df


def polarity(rating, sentiment):
    if pd.notna(rating):
        if rating >= 8:
            return "pos"
        if rating <= 4:
            return "neg"
        return "mid"
    if sentiment == "긍정":
        return "pos"
    if sentiment == "부정":
        return "neg"
    return "mid"


def main():
    t0 = time.time()
    print("[1/4] 데이터 로드...", flush=True)
    df = load_all()
    df["pol"] = [polarity(r, s) for r, s in zip(df["rating"], df["sentiment"])]
    print(f"   리뷰 {len(df):,} / 책 {df['title'].nunique():,} / 카테고리 {df['category'].nunique()}", flush=True)
    print("   카테고리 예시:", df["category"].value_counts().head(8).to_dict(), flush=True)

    print("[2/4] 책별 집계 + 키워드 추출...", flush=True)
    rows = []
    groups = list(df.groupby("title", sort=False))
    total = len(groups)
    for i, (title, g) in enumerate(groups):
        if i % 300 == 0:
            print(f"   {i:,}/{total:,} 책 처리... ({time.time()-t0:.0f}s)", flush=True)
        n = len(g)
        vc = g["sentiment"].value_counts()
        n_pos, n_neu, n_neg = int(vc.get("긍정", 0)), int(vc.get("중립", 0)), int(vc.get("부정", 0))
        pr, nr = n_pos / n, n_neg / n
        ratings = g["rating"].dropna()
        avg = round(float(ratings.mean()), 1) if len(ratings) else None
        controversy = round(min(pr, nr) * 2, 2)
        cat = g["category"].mode()
        cat = cat.iloc[0] if len(cat) else "기타"
        author = g["author"].dropna().astype(str)
        author = author[(author != "nan") & (author.str.strip() != "")]
        author = author.iloc[0] if len(author) else ""

        pos_kw, neg_kw = [], []
        if n >= MIN_KW:
            pg = g[g["pol"] == "pos"]["review"].dropna()
            ng = g[g["pol"] == "neg"]["review"].dropna()
            if len(pg) >= 3 or len(ng) >= 3:
                if len(pg) > CAP:
                    pg = pg.sample(CAP, random_state=0)
                if len(ng) > CAP:
                    ng = ng.sample(CAP, random_state=0)
                pos_kw, neg_kw = contrastive_keywords(pg.tolist(), ng.tolist())

        rows.append({
            "title": title, "author": author, "category": cat,
            "n_reviews": n, "n_pos": n_pos, "n_neu": n_neu, "n_neg": n_neg,
            "pos_ratio": round(pr, 4), "neg_ratio": round(nr, 4),
            "neu_ratio": round(n_neu / n, 4),
            "avg_rating": avg, "controversy": controversy,
            "pos_keywords": pos_kw, "neg_keywords": neg_kw,
            "sample_pos": pick_sample(g[g["sentiment"] == "긍정"]),
            "sample_neg": pick_sample(g[g["sentiment"] == "부정"]),
        })
    books = pd.DataFrame(rows)

    print("[3/4] 트렌드 집계...", flush=True)
    yt = df.dropna(subset=["year"])
    yt = yt[yt["year"].between(2000, 2026)]
    year_trend = (yt.groupby([yt["year"].astype(int), "sentiment"]).size()
                  .unstack(fill_value=0).reindex(columns=["긍정", "중립", "부정"], fill_value=0))
    cat_trend = (df.groupby(["category", "sentiment"]).size()
                 .unstack(fill_value=0).reindex(columns=["긍정", "중립", "부정"], fill_value=0))

    print("[4/4] 저장...", flush=True)
    with open(os.path.join(BASE, "insight_data.pkl"), "wb") as f:
        pickle.dump({"books": books, "year_trend": year_trend, "category_trend": cat_trend}, f)
    print(f"DONE in {time.time()-t0:.0f}s | books={len(books):,} | "
          f"키워드 있는 책={(books['pos_keywords'].str.len()>0).sum():,}", flush=True)


if __name__ == "__main__":
    main()
