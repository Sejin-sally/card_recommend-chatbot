from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, TypedDict

os.environ["ANONYMIZED_TELEMETRY"] = "false"

import chromadb
import pandas as pd
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langgraph.graph import END, START, StateGraph

from .cards_db import load_cards_db
from .constants import CATS
from .prompt import general_prompt, reco_prompt
from .recommend import compute_recommendation


logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CARDS_DIR = DATA_DIR / "cards"
CHROMA_DIR = str(BASE_DIR / "chroma-data")


class ChatGraphState(TypedDict, total=False):
    session: dict[str, Any] | None
    session_id: str
    user_text: str
    answer: str
    route: str
    reason: str


def _cards_file() -> Path:
    return sorted(CARDS_DIR.glob("*.csv"))[0]


def _llm() -> ChatOpenAI:
    return ChatOpenAI(model="gpt-4o-mini")


def _clean_meta_value(v: Any) -> Any:
    if pd.isna(v):
        return ""
    if isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def _issuer_domains(issuer: str) -> list[str]:
    s = (issuer or "").lower()
    mapping = {
        "신한": ["shinhancard.com", "shinhan.com"],
        "shinhan": ["shinhancard.com", "shinhan.com"],
        "국민": ["kbcard.com", "kbstar.com"],
        "kb": ["kbcard.com", "kbstar.com"],
        "하나": ["hanacard.co.kr"],
        "hana": ["hanacard.co.kr"],
        "삼성": ["samsungcard.com"],
        "samsung": ["samsungcard.com"],
        "현대": ["hyundaicard.com"],
        "hyundai": ["hyundaicard.com"],
        "롯데": ["lottecard.co.kr"],
        "lotte": ["lottecard.co.kr"],
        "우리": ["wooricard.com", "card.wooribank.com"],
        "woori": ["wooricard.com", "card.wooribank.com"],
        "농협": ["card.nonghyup.com"],
        "nh": ["card.nonghyup.com"],
        "bc": ["bccard.com"],
        "비씨": ["bccard.com"],
    }
    out: list[str] = []
    for k, domains in mapping.items():
        if k in s:
            out.extend(domains)
    return list(dict.fromkeys(out))


def _pick_official_result(results: list[dict[str, Any]], issuer: str) -> dict[str, Any] | None:
    domains = _issuer_domains(issuer)
    if domains:
        for r in results:
            url = str(r.get("url") or "")
            if any(d in url for d in domains):
                return r
    for r in results:
        url = str(r.get("url") or "")
        if any(x in url for x in ["card", "card.", "cards"]) and "http" in url:
            return r
    return results[0] if results else None


OFFICIAL_DOMAINS = [
    "kbcard.com", "shinhan.com", "shinhancard.com", "card.nonghyup.com", "nhcard.co.kr",
    "hanacard.co.kr", "hana-card.co.kr", "samsungcard.com",
    "hyundaicard.com", "lottecard.co.kr", "wooricard.com", "bccard.com",
]


def _extract_apply_link(note: str) -> str | None:
    if not note:
        return None
    m = re.search(r"신청\s*:\s*(https?://\S+)", str(note))
    return m.group(1) if m else None


def _pick_official(urls: list[str]) -> str | None:
    for u in urls:
        if u and any(d in u for d in OFFICIAL_DOMAINS):
            return u
    return None


def find_csv_path() -> Path:
    candidates = sorted(DATA_DIR.rglob("checkcards_wide_db.csv"))
    if not candidates:
        raise FileNotFoundError("checkcards_wide_db.csv not found under data/")
    return candidates[0]


def build_retriever_from_csv(csv_path: Path | str):
    df = pd.read_csv(csv_path)
    docs: list[Document] = []
    ids: list[str] = []
    for i, row in df.iterrows():
        meta = {str(k): _clean_meta_value(v) for k, v in row.to_dict().items()}
        perks = []
        for cat in CATS:
            try:
                rate = float(meta.get(cat, 0) or 0)
            except Exception:
                rate = 0.0
            if rate:
                perks.append(f"{cat}:{rate}")
        page = (
            f"{meta.get('card_name','')} | issuer={meta.get('issuer') or meta.get('card_company') or ''} "
            f"| condition={meta.get('condition_text','')} | annual_fee={meta.get('annual_fee','')} "
            f"| prev_month_spend={meta.get('prev_month_spend','')} | monthly_cap={meta.get('monthly_cap','')} "
            f"| perks={', '.join(perks[:6])}"
        )
        docs.append(Document(page_content=page, metadata=meta))
        ids.append(f"card-{i}")

    client = chromadb.PersistentClient(path=CHROMA_DIR)
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    vectorstore = Chroma(
        collection_name="cards-v1",
        client=client,
        embedding_function=embeddings,
    )

    try:
        count = vectorstore._collection.count()
    except Exception:
        count = 0
    if count == 0 and docs:
        vectorstore.add_documents(docs, ids=ids)

    return vectorstore.as_retriever(search_kwargs={"k": 1})


def _build_top_cards(top_df) -> list[dict[str, Any]]:
    top_cards: list[dict[str, Any]] = []
    for _, r in top_df.head(30).iterrows():
        perks = {}
        for cat in CATS:
            rate = float(r.get(cat, 0) or 0)
            if rate > 0:
                perks[cat] = rate
        top_cards.append(
            {
                "card_name": r.get("card_name"),
                "issuer": r.get("issuer"),
                "cate": r.get("cate"),
                "score_adj": float(r.get("score_adj", 0) or 0),
                "perks": perks,
                "condition_text": str(r.get("condition_text", "") or "").strip(),
                "monthly_cap": float(r.get("monthly_cap", 0) or 0),
                "prev_month_spend": float(r.get("prev_month_spend", 0) or 0),
                "annual_fee": float(r.get("annual_fee", 0) or 0),
            }
        )
    return top_cards


def _parse_router_json(text: str) -> tuple[str, str]:
    try:
        data = json.loads(text)
        route = str(data.get("route", "chat")).strip().lower()
        reason = str(data.get("reason", "")).strip()
        if route not in {"recommend", "search", "chat"}:
            route = "chat"
        return route, reason
    except Exception:
        return "chat", "router_json_parse_failed"


def router_node(state: ChatGraphState) -> ChatGraphState:
    user_text = state.get("user_text", "") or ""
    llm = _llm()
    messages = [
        (
            "system",
            """
너는 카드 추천 챗봇의 라우팅(분기) 어시스턴트다.
다음 3개 중 하나로만 분기(route)를 결정해라: recommend, search, chat.
출력은 반드시 아래 JSON 1개만 반환해라. (설명/추가 문장 금지)
{"route": "...", "reason": "..."}

규칙:
- recommend: 사용자가 여러 카드 후보를 뽑아달라거나(Top3/Top5), 본인 소비내역 기준으로 추천을 원하거나,
  여러 카드를 폭넓게 비교/추천해달라는 경우
- search: 사용자가 특정 카드명을 언급하고 그 카드에 대해 묻는 경우
  (상세정보/혜택/조건/연회비/전월실적/월한도/신청 방법/평가/“추천해줘(=이 카드 괜찮아?)” 포함)
- chat: 그 외 일반 대화

예시:
User: "추천해줘"
-> {"route":"recommend","reason":"여러 카드 추천을 원함"}

User: "청춘대로 톡톡카드 추천해줘"
-> {"route":"search","reason":"특정 카드명을 언급했고 해당 카드 평가/추천 여부를 묻는 질문"}

User: "톡톡 Pay카드 연회비 알려줘"
-> {"route":"search","reason":"특정 카드 상세 정보 질문"}

User: "카드 뭐가 좋아?"
-> {"route":"recommend","reason":"폭넓은 카드 추천을 원함"}
            """.strip(),
        ),
        ("human", user_text),
    ]
    try:
        res = llm.invoke(messages)
        route, reason = _parse_router_json(str(res.content))
        return {"route": route, "reason": reason}
    except Exception as e:
        logger.warning("router_node failed: %s", e)
        return {"route": "chat", "reason": "router_exception"}


def recommend_node(state: ChatGraphState) -> ChatGraphState:
    session = state.get("session")
    if session is None:
        return {"answer": "먼저 거래내역을 업로드해줘! (csv/xlsx)"}

    df2 = session["df2"]
    user_text = state.get("user_text", "")
    cards = load_cards_db(_cards_file())
    cate_filter = "CHK" if ("체크" in user_text) else "CRD" if ("신용" in user_text) else "ALL"
    if cate_filter != "ALL":
        cards = cards[cards["cate"].astype(str).str.upper() == cate_filter].copy()

    start_reco = time.time()
    _, top_df, spend, total_spend = compute_recommendation(df2, cards, topn=30)
    logger.info("[%s] 3. 추천 연산 시간: %.4f초", state.get("session_id"), time.time() - start_reco)

    spend_sorted = sorted(spend.items(), key=lambda x: x[1], reverse=True)[:30]
    session["last"] = {
        "cate_filter": cate_filter,
        "total_spend": total_spend,
        "top_spend": spend_sorted,
        "top_cards": _build_top_cards(top_df),
    }

    llm = _llm()
    context = json.dumps(session["last"], ensure_ascii=False)
    messages = reco_prompt.format_messages(context=context, question=user_text)
    start_llm = time.time()
    res = llm.invoke(messages)
    logger.info("[%s] 4. LLM 응답 시간: %.4f초", state.get("session_id"), time.time() - start_llm)
    return {"answer": str(res.content)}


def _tavily_once(card_name: str, issuer: str, user_text: str) -> tuple[str, str]:
    if not os.getenv("TAVILY_API_KEY"):
        return "공식 링크 확인이 필요합니다", ""
    try:
        from langchain_tavily import TavilySearch
    except Exception:
        return "공식 링크 확인이 필요합니다", ""

    domains = _issuer_domains(issuer)
    domain_hint = f" site:{domains[0]}" if domains else " 카드사 공식"
    query = f"{card_name} {issuer} 신청 발급 연회비 전월실적 혜택{domain_hint}".strip()
    try:
        tool = TavilySearch(max_results=5)
        raw = tool.invoke({"query": query})
        results = raw.get("results", raw) if isinstance(raw, dict) else raw
        results = [r for r in (results or []) if isinstance(r, dict)]
        best = _pick_official_result(results, issuer)
        snippets = []
        for r in results[:3]:
            title = str(r.get("title") or "").strip()
            text = str(r.get("content") or r.get("snippet") or "").strip().replace("\n", " ")
            snippets.append(f"{title}: {text[:120]}")
        summary = "\n".join(snippets[:3]) if snippets else "웹 검색 결과 요약 없음"
        link = str(best.get("url") or "") if best else ""
        return summary, link
    except Exception as e:
        logger.warning("Tavily failed: %s", e)
        return "공식 링크 확인이 필요합니다", ""


def search_node(state: ChatGraphState, retriever) -> ChatGraphState:
    user_text = state.get("user_text", "") or ""
    docs = []
    try:
        docs = retriever.invoke(user_text) if retriever else []
    except Exception as e:
        logger.warning("retriever failed: %s", e)
        docs = []
    if not docs:
        return {"answer": "모르겠습니다"}

    doc = docs[0] if docs else None
    row = dict(doc.metadata or {})
    card_name = str(row.get("card_name") or "")
    issuer = str(row.get("issuer") or row.get("card_company") or "")
    note = str(row.get("note") or "")

    web_summary, official_link = _tavily_once(card_name, issuer, user_text)
    apply_link = _extract_apply_link(note) or _pick_official([official_link])

    local_context = {
        "card_name": card_name,
        "issuer": issuer,
        "annual_fee": row.get("annual_fee", ""),
        "prev_month_spend": row.get("prev_month_spend", ""),
        "monthly_cap": row.get("monthly_cap", ""),
        "condition_text": row.get("condition_text", ""),
        "cate": row.get("cate", ""),
        "perks": {cat: row.get(cat, "") for cat in CATS},
        "note": note,
        "official_link": apply_link or "공식 링크 확인이 필요합니다",
        "web_summary": web_summary,
    }

    llm = _llm()
    context = json.dumps(local_context, ensure_ascii=False)
    res = llm.invoke(general_prompt.format_messages(question=user_text, context=context))
    answer = str(res.content)
    if apply_link and apply_link not in answer:
        answer = f"{answer}\n신청 링크: {apply_link}"
    elif not apply_link and "신청 링크" not in answer:
        answer = f"{answer}\n공식 링크 확인이 필요합니다."
    return {"answer": answer}


def chat_node(state: ChatGraphState) -> ChatGraphState:
    session = state.get("session")
    if session is None:
        return {"answer": "먼저 거래내역을 업로드해줘! (csv/xlsx)"}

    last = session.get("last")
    context = json.dumps(last, ensure_ascii=False) if last is not None else ""
    llm = _llm()
    user_text = state.get("user_text", "")
    start_llm = time.time()
    res = llm.invoke(general_prompt.format_messages(question=user_text, context=context))
    logger.info("[%s] 4. LLM 응답 시간: %.4f초", state.get("session_id"), time.time() - start_llm)
    return {"answer": str(res.content)}


def build_graph(retriever):
    graph = StateGraph(ChatGraphState)
    graph.add_node("router_node", router_node)
    graph.add_node("recommend_node", recommend_node)
    graph.add_node("search_node", lambda state: search_node(state, retriever))
    graph.add_node("chat_node", chat_node)
    graph.add_edge(START, "router_node")
    graph.add_conditional_edges(
        "router_node",
        lambda state: str(state.get("route", "chat")),
        {"recommend": "recommend_node", "search": "search_node", "chat": "chat_node"},
    )
    graph.add_edge("recommend_node", END)
    graph.add_edge("search_node", END)
    graph.add_edge("chat_node", END)
    return graph.compile()
