from __future__ import annotations

# 성능 평가 위한 시간 측정
import time
import logging

from pathlib import Path
from io import BytesIO
import uuid
import json
import pandas as pd
from fastapi import FastAPI, UploadFile, File
from contextlib import asynccontextmanager



from .api_schemas import (RecommendRequest, RecommendResponse, CardOut, ChatRequest, ChatResponse, UploadResponse)

from .preprocess import input_excel_preprocessing
from .categorize import categorize_transactions
from .cards_db import load_cards_db
from .recommend import compute_recommendation
from .prompt import reco_prompt, general_prompt
from .langgraph_flow import build_graph

from langchain_openai import ChatOpenAI


# 성능 평가 위한 코드
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CARDS_DIR = DATA_DIR / "cards"
CACHE_PATH = DATA_DIR / "cache" / "naver_cache.json"

app = FastAPI(title="Card Recommendation MVP (Simple)")

# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     app.state.sessions = {}
#     app.state.chat_graph = build_graph()
#     yield

@app.on_event("startup")
async def startup_event():
    # 세션 저장소
    app.state.sessions = {}

    # graph/retriever 초기화
    from .langgraph_flow import build_graph, build_retriever_from_csv, find_csv_path

    csv_path = find_csv_path()
    retriever = build_retriever_from_csv(csv_path)
    app.state.card_retriever = retriever

    app.state.chat_graph = build_graph(retriever)

def _cards_file() -> Path:
    # data/cards 안에서 첫 번째 csv를 카드 DB로 사용
    return sorted(CARDS_DIR.glob("*.csv"))[0]

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/upload", response_model=UploadResponse)
async def upload(session_id:str | None = None, file: UploadFile = File(...)):
    """
    거래내역 업로드 -> 전처리 -> 카테고리 -> 세션 저장
    """
    sid = session_id or str(uuid.uuid4())
    raw = await file.read()

    if (file.filename or "").lower().endswith(".csv"):
        df_raw = pd.read_csv(BytesIO(raw))
    else:
        df_raw = pd.read_excel(BytesIO(raw))
    
    # 시간 측정으로 감싸기
    start_prep = time.time()
    df_std = input_excel_preprocessing(df_raw)
    logger.info(f"[{sid}] 1. 전처리 소요시간: {time.time() - start_prep:.4f}초")

    start_cat = time.time()
    df2 = categorize_transactions(df_std, str(CACHE_PATH))
    logger.info(f"[{sid}] 2. 매핑 소요 시간: {time.time() - start_cat:.4}초 (총 {len(df2)}건)")

    app.state.sessions[sid] = {"df2": df2, "last": None}
    return UploadResponse(session_id=sid, rows=len(df2))

@app.post("/recommend", response_model=RecommendResponse)
def recommend(req: RecommendRequest):
    """
    (테스트용) JSON transactions로 바로 추천 계산
    """
    df_raw = pd.DataFrame([t.model_dump() for t in req.transactions])
    df_raw["notes"] = df_raw["notes"].fillna("").astype(str)
    df_raw["amounts"] = pd.to_numeric(df_raw["amounts"], errors="coerce").fillna(0).astype(int)

    df2 = categorize_transactions(df_raw, str(CACHE_PATH))
    cards = load_cards_db(_cards_file())

    cate_filter = (req.cate_filter or "ALL").upper()
    if cate_filter != "ALL":
        cards = cards[cards["cate"].astype(str).str.upper() == cate_filter].copy()

    _, top_df, spend, total_spend = compute_recommendation(df2, cards, topn=req.topn)

    top_records = top_df.to_dict(orient="records")
    return RecommendResponse(
        spend = {k:float(v) for k, v in spend.items()},
        total_spend=float(total_spend),
        top=[CardOut(**r) for r in top_records]
    )


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """
    대화 입력 -> 세션의 df2로 추천 계산 -> 대화형 텍스트 응답
    """
    out = app.state.chat_graph.invoke({
        "session": app.state.sessions.get(req.session_id),
        "session_id": req.session_id,
        "user_text": req.messages[-1].content if req.messages else "",
    })
    return ChatResponse(answer=out["answer"])

    """
    session = app.state.sessions.get(req.session_id)
    if session is None:
        return ChatResponse(answer="먼저 거래내역을 업로드해줘! (csv/xlsx)")

    df2 = session["df2"]
    user_text = req.messages[-1].content if req.messages else ""

    # 추천이 들어오면 추천, 아니면 마지막 추천 요약 기반 응답
    if "추천" in user_text:
        cards = load_cards_db(_cards_file())
        cate_filter = "CHK" if ("체크" in user_text) else "CRD" if ("신용" in user_text) else "ALL"
        if cate_filter != "ALL":
            cards = cards[cards["cate"].astype(str).str.upper() == cate_filter].copy()

        start_reco = time.time()
        _, top_df, spend, total_spend = compute_recommendation(df2, cards, topn=30)
        logger.info(f"[{req.session_id}] 3. 추천 연산 시간: {time.time() - start_reco:.4}초")

        spend_sorted = sorted(spend.items(), key=lambda x: x[1], reverse=True)[:30]

        CATS = ["food","simplepay","cafe_dessert","mart_convenience","ott_culture","shopping","health","education"]

        top_cards = []
        for _, r in top_df.head(30).iterrows():
        # 카드DB 원본 row에서 혜택률(%)
            perks = {}
            for cat in CATS:
                rate = float(r.get(cat, 0) or 0)  # top_df에 이미 cat 컬럼이 있으면 그대로 사용 가능
                if rate > 0:
                    perks[cat] = rate  # 예: 0.05

            top_cards.append({
                "card_name": r.get("card_name"),
                "issuer": r.get("issuer"),
                "cate": r.get("cate"),
                "score_adj": float(r.get("score_adj", 0) or 0),
                "perks": perks,
                "condition_text": str(r.get("condition_text","") or "").strip(),
                "monthly_cap": float(r.get("monthly_cap", 0) or 0),
                "prev_month_spend": float(r.get("prev_month_spend", 0) or 0),
                "annual_fee": float(r.get("annual_fee", 0) or 0),
            })

        session["last"] = {
            "cate_filter": cate_filter,
            "total_spend": total_spend,
            "top_spend": spend_sorted,
            "top_cards": top_cards,
        }
    
    # 추천이 아닌 질문은 "마지막 추천 결과"를 바탕으로 간단 응답
    last = session.get("last")
    if last is None:
        return ChatResponse(answer="업로드는 완료됐어. 이제 '추천해줘'라고 말해줘!")
    
    # 추천 요청인지 판단(지금처럼 "추천" 키워드로 충분)
    is_reco = ("추천" in user_text)

    llm = ChatOpenAI(model="gpt-4o-mini")
    context = json.dumps(last, ensure_ascii=False)

    p = reco_prompt if is_reco else general_prompt
    messages = p.format_messages(context=context, question=user_text)

    start_llm = time.time()
    res = llm.invoke(messages)
    logger.info(f"[{req.session_id}] 4. LLM 응답 시간: {time.time() - start_llm:.4}초")

    answer = res.content
    return ChatResponse(answer=answer)
    """
