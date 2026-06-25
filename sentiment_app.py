# -*- coding: utf-8 -*-
"""
📚 도서 리뷰 인사이트 (Book Review Insight)

웹크롤링(YES24·Watcha·Goodreads)으로 모은 도서 리뷰를 학습한 BiLSTM 감성 모델의
예측 결과를 활용한 '도서 탐색·분석 서비스'.

기능
  1) 책 검색·분석  : 리뷰 수 / 평균 평점 / 감정 분포 + '왜 좋고 나빴는지' 키워드 + 호불호 지수
  2) 랭킹·큐레이션 : 긍정률·호불호·리뷰수·평점 기준 추천
  3) 트렌드        : 카테고리·연도별 감성
  4) 책 비교       : 두 책을 나란히 비교
  5) 리뷰 직접 분석: 새 리뷰를 모델로 즉시 감성 예측 (단일/일괄)

데이터: insight_data.pkl (build_book_index.py 로 사전 계산) + model_3class/ (라이브 예측용)
실행:  streamlit run sentiment_app.py
"""

import os
import re
import pickle

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")

import numpy as np
import pandas as pd
import streamlit as st

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, "model_3class")
INSIGHT_PATH = os.path.join(BASE_DIR, "insight_data.pkl")

GREEN, GRAY, RED = "#2E7D32", "#757575", "#C62828"
STYLE = {
    "긍정": {"color": GREEN, "emoji": "😊"},
    "중립": {"color": GRAY, "emoji": "😐"},
    "부정": {"color": RED, "emoji": "😞"},
}

EXAMPLES = [
    "이 책 정말 재밌어요. 강추합니다!",
    "그냥 그래요. 시간 때우기용으로는 괜찮네요.",
    "돈 아깝다. 노잼이고 추천하지 않습니다.",
    "기대 이상이었어요. 밤새 읽었습니다 ㅠㅠ 감동",
    "내용이 너무 뻔하고 지루했어요.",
]


# ===========================================================================
# 데이터/모델 로딩
# ===========================================================================
@st.cache_data(show_spinner="도서 인덱스를 불러오는 중입니다...")
def load_insight():
    if not os.path.exists(INSIGHT_PATH):
        return None
    with open(INSIGHT_PATH, "rb") as f:
        return pickle.load(f)


@st.cache_resource(show_spinner="감성 분석 모델을 불러오는 중입니다... (최초 1회, 수십 초)")
def load_resources():
    import joblib
    import keras
    from keras.utils import pad_sequences
    from konlpy.tag import Okt

    cfg = joblib.load(os.path.join(MODEL_DIR, "sa_3class_config.pkl"))
    tokenizer = joblib.load(os.path.join(MODEL_DIR, "sa_3class_tokenizer.pkl"))
    model = keras.models.load_model(os.path.join(MODEL_DIR, "sa_3class_model.keras"), compile=False)
    okt = Okt()
    okt.morphs("워밍업")
    return cfg, tokenizer, model, okt, pad_sequences


# ===========================================================================
# 라이브 예측 (노트북과 동일 파이프라인)
# ===========================================================================
def clean_text(text):
    if not isinstance(text, str):
        return ""
    cleaned = re.sub("[^ 가-힣]+", " ", text)
    return re.sub(" +", " ", cleaned).strip()


def predict_one(text, cfg, tokenizer, model, okt, pad_sequences):
    label_names, max_len = cfg["LABEL_NAMES"], cfg["MAX_LEN"]
    cleaned = clean_text(text)
    if cleaned == "":
        return None, 0.0, None, [], cleaned
    tokens = okt.morphs(cleaned)
    enc = tokenizer.texts_to_sequences([tokens])[0]
    if len(enc) == 0:
        return None, 0.0, None, tokens, cleaned
    probs = model.predict(pad_sequences([enc], maxlen=max_len), verbose=0)[0]
    idx = int(np.argmax(probs))
    return label_names[idx], float(probs[idx]), {label_names[i]: float(probs[i]) for i in range(len(label_names))}, tokens, cleaned


def predict_many(texts, cfg, tokenizer, model, okt, pad_sequences, batch_size=256):
    label_names, max_len = cfg["LABEL_NAMES"], cfg["MAX_LEN"]
    labels, confs = ["중립"] * len(texts), [0.0] * len(texts)
    valid_idx, valid_seqs = [], []
    for i, t in enumerate(texts):
        cleaned = clean_text(t)
        if cleaned == "":
            continue
        enc = tokenizer.texts_to_sequences([okt.morphs(cleaned)])[0]
        if len(enc) == 0:
            continue
        valid_idx.append(i)
        valid_seqs.append(enc)
    if valid_seqs:
        preds = model.predict(pad_sequences(valid_seqs, maxlen=max_len), batch_size=batch_size, verbose=0)
        arg, mx = preds.argmax(axis=1), preds.max(axis=1)
        for j, i in enumerate(valid_idx):
            labels[i] = label_names[int(arg[j])]
            confs[i] = float(mx[j])
    return labels, confs


# ===========================================================================
# UI 헬퍼
# ===========================================================================
def sentiment_dist_bars(counts, total):
    for name in ["긍정", "중립", "부정"]:
        cnt = int(counts.get(name, 0))
        pct = (cnt / total * 100) if total else 0
        color = STYLE[name]["color"]
        st.markdown(
            f"""
            <div style="margin:6px 0;">
              <div style="display:flex;justify-content:space-between;font-size:0.9rem;">
                <span><b>{STYLE[name]['emoji']} {name}</b></span>
                <span>{cnt:,}개 ({pct:.1f}%)</span>
              </div>
              <div style="background:#e9ecef;border-radius:6px;height:15px;overflow:hidden;">
                <div style="width:{pct:.1f}%;background:{color};height:100%;"></div>
              </div>
            </div>""",
            unsafe_allow_html=True,
        )


def kw_chips(words, color):
    if not words or len(words) == 0:
        return "<span style='color:#aaa;font-size:0.9rem;'>키워드 부족</span>"
    return "".join(
        f"<span style='display:inline-block;background:{color}18;color:{color};"
        f"border:1px solid {color}55;border-radius:14px;padding:3px 11px;margin:3px 5px 3px 0;"
        f"font-size:0.92rem;font-weight:600;'>{w}</span>"
        for w in words
    )


def controversy_label(s):
    if s >= 0.6:
        return "⚖️ 호불호가 크게 갈리는 책"
    if s >= 0.3:
        return "🤔 의견이 다소 갈림"
    return "✅ 평가가 한쪽으로 뚜렷"


def has_kw(v):
    return isinstance(v, (list, tuple)) and len(v) > 0


def show_book_card(row):
    st.markdown(f"### 📖 {row['title']}")
    meta = []
    if str(row.get("author", "")).strip():
        meta.append(str(row["author"]))
    if str(row.get("category", "")).strip() not in ("", "기타", "nan"):
        meta.append(str(row["category"]))
    if meta:
        st.caption(" · ".join(meta))

    n = int(row["n_reviews"])
    c1, c2, c3 = st.columns(3)
    c1.metric("📝 리뷰 수", f"{n:,}개")
    avg = row["avg_rating"]
    c2.metric("⭐ 평균 평점", f"{avg:.1f} / 10" if pd.notna(avg) else "정보 없음")
    c3.metric("⚖️ 호불호 지수", f"{int(row['controversy'] * 100)}%",
              help="긍정·부정이 모두 높을수록 의견이 갈립니다")
    st.caption(controversy_label(row["controversy"]))

    st.markdown("**🎭 감정 분석 (리뷰 감성 분포)**")
    sentiment_dist_bars({"긍정": row["n_pos"], "중립": row["n_neu"], "부정": row["n_neg"]}, n)

    pos_kw = row["pos_keywords"] if has_kw(row["pos_keywords"]) else []
    neg_kw = row["neg_keywords"] if has_kw(row["neg_keywords"]) else []
    summ = []
    if pos_kw:
        summ.append(f"<b style='color:{GREEN}'>호평</b> {' · '.join(pos_kw[:3])}")
    if neg_kw:
        summ.append(f"<b style='color:{RED}'>아쉬움</b> {' · '.join(neg_kw[:3])}")
    if summ:
        st.markdown(
            "<div style='margin:10px 0;font-size:1.02rem;'>" + " &nbsp;|&nbsp; ".join(summ) + "</div>",
            unsafe_allow_html=True,
        )

    k1, k2 = st.columns(2)
    with k1:
        st.markdown("**👍 좋았던 점 키워드**")
        st.markdown(kw_chips(pos_kw, GREEN), unsafe_allow_html=True)
    with k2:
        st.markdown("**👎 아쉬운 점 키워드**")
        st.markdown(kw_chips(neg_kw, RED), unsafe_allow_html=True)

    sp, sn = str(row.get("sample_pos", "")), str(row.get("sample_neg", ""))
    if sp.strip() or sn.strip():
        with st.expander("📄 리뷰 예시 보기"):
            if sp.strip() and sp != "nan":
                st.markdown("**😊 긍정 리뷰**")
                st.write("· " + sp)
            if sn.strip() and sn != "nan":
                st.markdown("**😞 부정 리뷰**")
                st.write("· " + sn)


def show_result(label, conf, prob_dict, tokens, cleaned):
    if label is None:
        st.warning("한글 단어를 찾지 못했어요. 이 모델은 **한글 리뷰**만 분석합니다. (기본값 중립)")
        return
    s = STYLE[label]
    st.markdown(
        f"""
        <div style="background:{s['color']}15;border:2px solid {s['color']};border-radius:14px;
                    padding:18px;text-align:center;margin:10px 0;">
          <div style="font-size:2.6rem;line-height:1;">{s['emoji']}</div>
          <div style="font-size:1.8rem;font-weight:800;color:{s['color']};">{label}</div>
          <div style="margin-top:8px;">신뢰도 <b>{conf*100:.1f}%</b></div>
        </div>""",
        unsafe_allow_html=True,
    )
    st.markdown("**클래스별 예측 확률**")
    for name in ["긍정", "중립", "부정"]:
        pct = prob_dict.get(name, 0) * 100
        color = STYLE[name]["color"]
        st.markdown(
            f"""<div style="margin:5px 0;"><div style="display:flex;justify-content:space-between;font-size:0.9rem;">
            <span><b>{STYLE[name]['emoji']} {name}</b></span><span>{pct:.1f}%</span></div>
            <div style="background:#e9ecef;border-radius:6px;height:13px;overflow:hidden;">
            <div style="width:{pct:.1f}%;background:{color};height:100%;"></div></div></div>""",
            unsafe_allow_html=True,
        )
    with st.expander("🔍 전처리 결과"):
        st.write("**정제 텍스트:**", cleaned or "(없음)")
        st.write("**형태소:**", " · ".join(tokens) if tokens else "(없음)")


# ===========================================================================
# 메인
# ===========================================================================
def main():
    st.set_page_config(page_title="도서 리뷰 인사이트", page_icon="📚", layout="wide")
    st.title("📚 도서 리뷰 인사이트")
    st.caption(
        "웹크롤링한 도서 리뷰(YES24·Watcha) **14만+ 건**을 BiLSTM 감성 모델로 분석한 결과로, "
        "책의 **평가·호불호·장단점**을 한눈에 보여줍니다."
    )

    data = load_insight()

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["🔍 책 검색·분석", "🏆 랭킹·큐레이션", "📊 트렌드", "⚖️ 책 비교", "✍️ 리뷰 직접 분석"]
    )

    # ---------------------------------------------------------------- 책 검색
    with tab1:
        if data is None:
            st.warning("도서 인덱스(`insight_data.pkl`)가 없습니다. 먼저 `build_book_index.py`를 실행하세요.")
        else:
            books = data["books"]
            st.write("책 제목을 검색하면 **리뷰 수·평균 평점·감정 분석**과 **좋았던/아쉬운 점 키워드**를 보여줍니다.")
            tops = books.sort_values("n_reviews", ascending=False).head(5)["title"].tolist()
            st.caption("리뷰 많은 책으로 바로 보기:")
            cols = st.columns(len(tops))
            for i, t in enumerate(tops):
                if cols[i].button(t if len(t) <= 12 else t[:11] + "…", key=f"bk{i}", help=t):
                    st.session_state["book_query"] = t
            q = st.text_input("책 제목 검색", key="book_query", placeholder="예) 프로젝트 헤일메리").strip()
            if q:
                m = books[books["title"].str.contains(re.escape(q), case=False, na=False)]
                if m.empty:
                    st.warning(f"'{q}' 와(과) 일치하는 책이 없습니다. (크롤링한 도서만 검색)")
                else:
                    m = m.sort_values("n_reviews", ascending=False)
                    tlist = m["title"].tolist()
                    pick = tlist[0] if len(tlist) == 1 else st.selectbox(
                        f"🔎 검색 결과 {len(tlist):,}권", tlist,
                        format_func=lambda t: f"{t}  ({int(books.loc[books['title']==t,'n_reviews'].iloc[0]):,}개 리뷰)")
                    st.divider()
                    show_book_card(books[books["title"] == pick].iloc[0])

    # ---------------------------------------------------------------- 랭킹
    with tab2:
        if data is None:
            st.warning("도서 인덱스가 없습니다. `build_book_index.py`를 실행하세요.")
        else:
            books = data["books"]
            st.write("기준을 골라 **추천 도서**를 확인하세요.")
            c1, c2 = st.columns([2, 1])
            kind = c1.selectbox("랭킹 기준",
                                ["긍정 비율 높은 책", "호불호 갈리는 책", "리뷰 많은 책", "평균 평점 높은 책"])
            min_n = c2.slider("최소 리뷰 수", 10, 300, 30, step=10)
            f = books[books["n_reviews"] >= min_n].copy()
            if kind == "긍정 비율 높은 책":
                f = f.sort_values(["pos_ratio", "n_reviews"], ascending=False)
            elif kind == "호불호 갈리는 책":
                f = f.sort_values(["controversy", "n_reviews"], ascending=False)
            elif kind == "리뷰 많은 책":
                f = f.sort_values("n_reviews", ascending=False)
            else:
                f = f[f["avg_rating"].notna()].sort_values(["avg_rating", "n_reviews"], ascending=False)
            top = f.head(20)
            if top.empty:
                st.info("조건에 맞는 책이 없습니다. 최소 리뷰 수를 낮춰보세요.")
            else:
                disp = pd.DataFrame({
                    "제목": top["title"].values,
                    "리뷰수": top["n_reviews"].values,
                    "평균평점": [f"{r:.1f}" if pd.notna(r) else "-" for r in top["avg_rating"]],
                    "긍정%": (top["pos_ratio"] * 100).round(0).astype(int).astype(str) + "%",
                    "호불호": (top["controversy"] * 100).round(0).astype(int).astype(str) + "%",
                    "좋았던 점": [", ".join(k[:4]) if has_kw(k) else "-" for k in top["pos_keywords"]],
                    "아쉬운 점": [", ".join(k[:4]) if has_kw(k) else "-" for k in top["neg_keywords"]],
                })
                st.dataframe(disp, use_container_width=True, hide_index=True, height=560)

    # ---------------------------------------------------------------- 트렌드
    with tab3:
        if data is None:
            st.warning("도서 인덱스가 없습니다. `build_book_index.py`를 실행하세요.")
        else:
            st.write("크롤링한 리뷰 전체의 **감성 트렌드**입니다.")
            cat = data["category_trend"].copy()
            cat["합계"] = cat.sum(axis=1)
            cat = cat[cat["합계"] >= 200]
            if len(cat):
                cat["긍정비율(%)"] = (cat["긍정"] / cat["합계"] * 100).round(1)
                catv = cat.sort_values("긍정비율(%)", ascending=False).head(12)
                st.markdown("**📚 카테고리별 긍정 비율** (리뷰 200건 이상)")
                st.bar_chart(catv["긍정비율(%)"], height=300)
            yt = data["year_trend"].copy()
            yt = yt[(yt.sum(axis=1) >= 100)]
            if len(yt):
                yt["긍정비율(%)"] = (yt["긍정"] / yt.sum(axis=1) * 100).round(1)
                st.markdown("**📅 연도별 긍정 비율** (YES24 기준, 리뷰 100건 이상 연도)")
                st.line_chart(yt["긍정비율(%)"], height=300)
                st.markdown("**📅 연도별 리뷰 수**")
                st.bar_chart(yt[["긍정", "중립", "부정"]], height=300,
                             color=[GREEN, GRAY, RED])

    # ---------------------------------------------------------------- 비교
    with tab4:
        if data is None:
            st.warning("도서 인덱스가 없습니다. `build_book_index.py`를 실행하세요.")
        else:
            books = data["books"]
            opts = books[books["n_reviews"] >= 10].sort_values("n_reviews", ascending=False)["title"].tolist()
            if len(opts) < 2:
                st.info("비교할 책이 부족합니다.")
            else:
                st.write("두 책을 골라 **나란히 비교**합니다.")
                cc1, cc2 = st.columns(2)
                b1 = cc1.selectbox("책 1", opts, index=0, key="cmp1")
                b2 = cc2.selectbox("책 2", opts, index=min(1, len(opts) - 1), key="cmp2")
                st.divider()
                d1, d2 = st.columns(2)
                with d1:
                    show_book_card(books[books["title"] == b1].iloc[0])
                with d2:
                    show_book_card(books[books["title"] == b2].iloc[0])

    # ---------------------------------------------------------------- 리뷰 직접 분석
    with tab5:
        st.write("새 리뷰를 입력하면 **학습된 모델이 즉시** 긍정/중립/부정을 예측합니다. (한글 전용)")
        if "review_text" not in st.session_state:
            st.session_state["review_text"] = EXAMPLES[0]
        ex_cols = st.columns(len(EXAMPLES))
        for i, ex in enumerate(EXAMPLES):
            if ex_cols[i].button(f"예시 {i+1}", key=f"ex{i}", help=ex):
                st.session_state["review_text"] = ex
        text = st.text_area("리뷰 입력", key="review_text", height=120)
        if st.button("감성 예측하기", type="primary", use_container_width=True):
            if not text.strip():
                st.warning("리뷰를 입력해 주세요.")
            else:
                with st.spinner("모델 불러오는 중..."):
                    res_model = load_resources()
                with st.spinner("분석 중..."):
                    res = predict_one(text, *res_model)
                show_result(*res)

        st.divider()
        st.markdown("**📋 여러 개 한꺼번에** — 줄바꿈으로 구분하거나 CSV(텍스트 컬럼) 업로드")
        multi = st.text_area("여러 리뷰", height=120, placeholder="재밌어요 강추\n그냥 그래요\n돈 아깝다 별로")
        up = st.file_uploader("또는 CSV 업로드", type=["csv"])
        if st.button("일괄 예측하기", use_container_width=True):
            texts = None
            if up is not None:
                try:
                    bdf = pd.read_csv(up)
                except Exception:
                    up.seek(0)
                    bdf = pd.read_csv(up, encoding="utf-8-sig")
                obj = [c for c in bdf.columns if bdf[c].dtype == object]
                if obj:
                    texts = bdf[obj[0]].fillna("").astype(str).tolist()
            elif multi.strip():
                texts = [ln for ln in multi.splitlines() if ln.strip()]
            if not texts:
                st.warning("분석할 리뷰가 없습니다.")
            else:
                texts = texts[:5000]
                with st.spinner("모델 불러오는 중..."):
                    res_model = load_resources()
                with st.spinner(f"{len(texts):,}건 분석 중..."):
                    labels, confs = predict_many(texts, *res_model)
                out = pd.DataFrame({"리뷰": texts, "감성": labels, "신뢰도": [round(c, 3) for c in confs]})
                vc = out["감성"].value_counts()
                m1, m2, m3 = st.columns(3)
                m1.metric("😊 긍정", f"{int(vc.get('긍정', 0)):,}")
                m2.metric("😐 중립", f"{int(vc.get('중립', 0)):,}")
                m3.metric("😞 부정", f"{int(vc.get('부정', 0)):,}")
                st.bar_chart(vc.reindex(["긍정", "중립", "부정"]).fillna(0), color=GREEN)
                st.dataframe(out, use_container_width=True, height=320)
                st.download_button("결과 CSV 다운로드",
                                   out.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
                                   "sentiment_result.csv", "text/csv")


if __name__ == "__main__":
    main()
