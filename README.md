
---

# Card Recommend Chatbot MVP

거래내역(csv/xlsx)을 업로드하면 지출 카테고리를 분류하고(룰 + 네이버 로컬 검색),
카드 DB의 혜택률과 매칭하여 점수 기반으로 카드를 추천해주는 **대화형 카드 추천 챗봇(MVP)** 입니다.

* **FE**: Streamlit (업로드 + 채팅 UI)
* **BE**: FastAPI (전처리 / 카테고리 분류 / 추천 계산 / 챗 응답)
* **LLM**: `gpt-5-nano` (추천 결과 요약(JSON)을 근거로 자연스럽게 설명)

---

## 핵심 아이디어

이 프로젝트는 “문서 검색 RAG”가 아니라,
**계산 결과(추천 결과 요약 JSON)를 근거(context)로 사용**해 LLM이 답변을 생성하는 구조입니다.

* Retriever 역할: 전처리/카테고리 분류/점수 계산(코드)
* Generator 역할: JSON 근거 기반으로 답변 생성(LLM)

그래서 대화가 길어져도 “근거가 흔들리지 않고”, 결과가 일관됩니다.

---

## 주요 기능

### 1) 거래내역 업로드

* csv/xlsx 파일을 업로드하면 서버에서 `date`, `notes`, `amount` 형태로 표준화합니다.
* 업로드 결과는 세션 단위로 메모리에 저장됩니다.

### 2) 카테고리 분류 (룰 + 네이버 검색 + 캐시)

* 1차: 키워드 룰 기반 분류
* 2차: 룰로 분류되지 않은 항목(etc)은 **네이버 로컬 검색 API**로 보강
* 네이버 결과는 `data/cache/naver_cache.json`에 캐시되어 재호출을 줄입니다.
* 플랫폼 결제 힌트(PAY_HINTS)는 검색이 어려워 `simplepay`로 별도 처리합니다.

### 3) 점수 기반 추천

* 업로드된 거래내역을 카테고리별로 합산하고,
* 카드 DB의 혜택률(%)과 매칭하여 카드별 점수를 계산합니다.
* 점수 상위 카드 TOP N 추천이 가능합니다.

### 4) 대화형 추천 (/chat)

* “체크카드/신용카드 추천”, “1번 카드 더 설명” 같은 후속 질문을 지원합니다.
* **특정 카드 제외 추천**을 지원합니다.

  * 예: `나라사랑카드 제외하고 추천해줘`
  * 예: `톡톡카드 제외하고 신용카드 3개 추천해줘`

---

## 예시 대화

* `체크카드 추천해줘`
* `나라사랑카드 제외하고 추천해줘`
* `톡톡카드 제외하고 신용카드 3개 추천해줘`
* `2번 카드에 대해 더 설명해줘`
* `음식 카테고리 혜택 높은 카드 추천해줘`

---

## 프로젝트 구조

```
.
├── app_streamlit.py                 # Streamlit UI (업로드 + 채팅)
└── src
    ├── api.py                       # FastAPI 엔드포인트 (/upload, /chat, /recommend)
    ├── api_schemas.py               # Pydantic 스키마
    ├── preprocess.py                # 거래내역 전처리(표준 컬럼), merchant 정규화
    ├── categorize.py                # 룰 기반 + 네이버 검색 + 캐시 + PAY_HINTS
    ├── naver_client.py              # 네이버 로컬 검색 API 호출
    ├── cards_db.py                  # 카드 DB 로드/수치 정리
    ├── recommend.py                 # 점수 계산 로직
    ├── prompt.py                    # ChatPromptTemplate (context 기반 프롬프트)
    ├── constants.py                 # 카테고리 리스트(CATS)
    └── settings.py                  # .env 로드 (NAVER / OPENAI 키)
```

---

## 설치

### requirements 설치

```bash
pip install -r requirements.txt
```

---

## 실행

### 1) 백엔드(FastAPI)

```bash
uvicorn src.api:app --reload --port 8000
```

### 2) 프론트(Streamlit)

```bash
streamlit run app_streamlit.py
```

---

## API 요약

### POST `/upload`

* 거래내역 파일 업로드 → 전처리 → 카테고리 분류 → 세션 저장

### POST `/chat`

* 대화 입력 → 세션 저장된 데이터 기반 추천/설명 응답 생성

---

## 추천 로직(요약)

* 카테고리별 지출 합계 계산
* `지출 금액 × 카드 혜택률`을 합산하여 카드 점수 계산
* 상위 카드 추천

---

## 제외 추천 처리

사용자 요청에 “제외”가 포함되면, 추천 후보 리스트에서 해당 키워드가 포함된 카드명을 제거하고 TOP N을 다시 구성합니다.

예:

* `톡톡카드 제외` → 카드명에 “톡톡”이 포함된 카드 제거 후 추천

---

## 제한사항 (MVP)

* 세션 저장은 메모리(`app.state.sessions`) 기반이라 서버 재시작 시 초기화됩니다.
* 카드 혜택의 정확한 약관/조건은 카드사 공식 페이지 기준으로 확인이 필요합니다.
* 네이버 API 응답과 캐시 상태에 따라 일부 카테고리 매핑이 달라질 수 있습니다.

---

## Docker 실행 (로컬)

`FastAPI (src.api:app)` + `Streamlit (app_streamlit.py)`를 `docker compose`로 로컬 실행할 수 있습니다.

### 1) 환경변수 파일 준비

macOS/Linux:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

`.env`에 최소 `OPENAI_API_KEY`를 설정하세요. (`NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `TAVILY_API_KEY`는 사용 기능에 따라 선택)

### 2) 카드 DB 파일 위치

- 권장 경로: `data/cards/checkcards_wide_db.csv`
- Git 커밋 금지 (`.gitignore` 처리)

`docker-compose.yml`에서 `./data`는 `/app/data`로 **read-only 마운트**됩니다.

참고: 앱이 `data/cache/naver_cache.json`을 갱신할 수 있도록 `./data/cache`만 별도 writable 오버레이 마운트를 추가해 두었습니다.

### 3) 실행

```bash
docker compose up --build
```

접속 주소:

- Backend: `http://localhost:8000/health`
- Frontend: `http://localhost:8501`

### 4) 종료

```bash
docker compose down
```

---

## EC2 배포 절차 (Docker Compose)

### 1) EC2 생성 / 보안그룹

- 인바운드 허용: `22` (SSH), `8000` (FastAPI), `8501` (Streamlit)
- 운영 환경에서 외부 공개 시 필요하면 `80/443` + 리버스프록시(Nginx) 구성

### 2) Docker 설치 (Ubuntu 기준)

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker
```

### 3) 코드 배포

```bash
git clone <your-repo-url>
cd card_recommend_service_fix
cp .env.example .env
```

- `.env` 값 입력
- 카드 DB CSV를 `data/cards/checkcards_wide_db.csv`에 업로드 (Git 커밋 금지)

### 4) 컨테이너 실행

```bash
docker compose up -d --build
```

### 5) 확인 / 로그

```bash
docker compose ps
docker compose logs -f backend
docker compose logs -f frontend
```

### 6) 업데이트 배포

```bash
git pull
docker compose up -d --build
```
