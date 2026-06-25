# 📚 도서 리뷰 인사이트 (Streamlit)

웹크롤링으로 모은 도서 리뷰(YES24·Watcha) **14만+ 건**을 BiLSTM 감성 모델로 분석한 결과로,
책의 **평가·호불호·장단점**을 한눈에 보여주는 도서 탐색·분석 서비스입니다.

## 구성

| 파일 | 설명 |
|---|---|
| `sentiment_app.py` | Streamlit 앱 본체 |
| `build_book_index.py` | **사전계산 배치** — 책별 집계 + 긍/부정 키워드 추출 → `insight_data.pkl` 생성 |
| `insight_data.pkl` | 앱이 즉시 불러오는 도서 인덱스(책 요약·키워드·트렌드) |
| `run_sentiment_app.bat` | 더블클릭 실행용 배치 파일 |
| `model_3class/*` | 학습된 BiLSTM 모델·토크나이저·설정 (라이브 예측용) |

## 처음 한 번: 인덱스 생성
앱의 데이터 탭(책 검색·랭킹·트렌드·비교)은 `insight_data.pkl`이 필요합니다. 최초 1회만 실행하세요(수 분 소요):
```powershell
C:\Users\user\anaconda3\envs\aiservice26\python.exe build_book_index.py
```
> 결과 CSV(`result_yes24_book_reviews.csv`, `result_watcha_book_comments.csv`)로부터 책별 통계와 키워드를 미리 계산합니다. 재학습은 하지 않습니다.

## 실행 방법

### 방법 1) 배치 파일 (가장 간단)
`run_sentiment_app.bat` 를 더블클릭하면 브라우저에서 앱이 열립니다.

### 방법 2) 터미널
```powershell
# aiservice26 환경의 파이썬으로 실행
C:\Users\user\anaconda3\envs\aiservice26\python.exe -m streamlit run sentiment_app.py
```
또는 환경을 활성화한 뒤:
```powershell
conda activate aiservice26
streamlit run sentiment_app.py
```

실행하면 보통 `http://localhost:8501` 주소로 브라우저가 열립니다.

## 기능 (탭 5개)
1. **🔍 책 검색·분석**: 책 제목을 검색하면 **리뷰 수 · 평균 평점 · 감정 분포 · 호불호 지수**와, 리뷰에서 뽑은 **👍 좋았던 점 / 👎 아쉬운 점 키워드**, 감성별 리뷰 예시를 보여줍니다.
2. **🏆 랭킹·큐레이션**: 긍정 비율 / 호불호 / 리뷰 수 / 평균 평점 기준으로 추천 도서를 표로 보여줍니다(최소 리뷰 수 조절 가능).
3. **📊 트렌드**: 카테고리별 긍정 비율, 연도별 감성 추이.
4. **⚖️ 책 비교**: 두 책을 나란히 비교(평점·감성·키워드).
5. **✍️ 리뷰 직접 분석**: 새 리뷰를 모델로 즉시 예측(단일/일괄 CSV). 이 탭을 쓸 때만 모델을 불러옵니다.

### 키워드는 어떻게 뽑나 (재학습 없음)
- 긍정 리뷰 vs 부정 리뷰에서 **Okt 명사 빈도를 대비**해, 한쪽에서 두드러지는 단어를 키워드로 선정합니다.
- 그룹 기준: 평점이 있는 **YES24는 고평점(8~10) vs 저평점(1~4) 리뷰**로 나눠 추출 → 모델 정확도와 무관하게 신뢰도 높음. Watcha는 예측 감성으로 나눕니다.
- 감정 분포(긍/중/부)는 모델 예측 `sentiment` 기준이며, 책당 수백~수천 건을 모아 **책 단위로는 안정적**입니다.
- 평균 평점은 YES24(1~10점) 기준, 제목 끝 `(2024)` 표기는 같은 책으로 병합합니다.

## 전처리 파이프라인 (노트북과 동일)
```
clean_text(한글/공백만 남김) → Okt.morphs(형태소 분석) → texts_to_sequences → pad_sequences(100)
→ 모델 예측 → argmax → 긍정/중립/부정
```

## 참고 / 주의
- **한글 리뷰 전용** 모델입니다. 학습 시 영어 리뷰는 한국어로 번역해 사용했으므로, 영어를 그대로 입력하면 정확도가 떨어집니다(한글이 하나도 없으면 기본값 *중립* 처리).
- KoNLPy `Okt` 형태소 분석기는 **Java(JDK)** 가 필요합니다. (노트북 학습 환경에 이미 설치되어 있습니다.)
- 필요한 패키지(`aiservice26` 환경에 설치됨): `streamlit`, `tensorflow`, `keras`, `konlpy`, `jpype1`, `scikit-learn`, `pandas`, `numpy`.

## GitHub 업로드 / 배포

> ⚠️ **`run_sentiment_app.bat` 만 올리면 실행되지 않습니다.** 이 배치 파일은 내 PC의 conda 경로(`C:\Users\...\envs\aiservice26\python.exe`)가 박혀 있는 **로컬 전용 실행기**입니다.

### 실행에 꼭 필요한 파일 (이것만 있으면 됨)
| 파일 | 크기 | 용도 |
|---|---|---|
| `sentiment_app.py` | 작음 | 앱 본체 |
| `model_3class/sa_3class_model.keras` | 74.5MB | 모델 (리뷰 직접 분석 탭) |
| `model_3class/sa_3class_tokenizer.pkl` | 6.5MB | 토크나이저 |
| `model_3class/sa_3class_config.pkl` | 1KB | 설정 |
| `insight_data.pkl` | 3.9MB | 도서 인덱스 (검색·랭킹·트렌드·비교 탭) |
| `requirements.txt` / `packages.txt` | 작음 | 패키지 / Java 설치 |

→ **앱 실행에 원본·결과 CSV는 필요 없습니다.** (CSV는 `build_book_index.py`로 인덱스를 *다시 만들* 때만 사용)

### 올리면 안 되는 / 못 올리는 파일
- `reviews.csv`(234MB), `result_reviews.csv`(230MB), `reviews_translated_cache.csv`(225MB) → **GitHub 100MB 제한 초과, 업로드 거부됨.**
- `train_tokenized_cache.csv`, `result_*.csv`, 원본 `*.csv`, `best_3class.keras`(중복) → 실행에 불필요.
- 위 파일들은 `.gitignore`에 이미 제외해 두었습니다.
- 참고: `sa_3class_model.keras`(74.5MB)는 100MB 미만이라 그대로 커밋 가능하지만 50MB↑라 GitHub가 경고합니다. 깔끔하게 하려면 **Git LFS** 사용을 권장합니다: `git lfs track "*.keras"`.

### 로컬에서 (어느 PC든)
```bash
pip install -r requirements.txt   # 그리고 Java(JDK) 설치 필요
streamlit run sentiment_app.py
```

### Streamlit Community Cloud 배포 (무료, 추천)
1. 위 "필요한 파일"들을 GitHub 저장소에 올린다 (`README.md`로 이름 바꾸면 자동 표시).
2. share.streamlit.io 에서 저장소 연결 → `sentiment_app.py` 지정.
3. `requirements.txt`(파이썬 패키지)와 `packages.txt`(= `default-jdk`, konlpy용 Java)가 자동 설치됨.
4. 배포 완료. 데이터 탭은 바로 동작, "리뷰 직접 분석" 탭은 첫 사용 시 모델 로딩(수십 초).

> 팁: "리뷰 직접 분석"(모델·Java)이 부담되면, 그 탭을 빼고 **데이터 탭만** 배포하면 `streamlit·pandas·numpy`만으로 가볍게 올릴 수 있습니다(모델·Java 불필요).
