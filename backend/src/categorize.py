from __future__ import annotations

import re
import json
import pandas as pd
import logging
from .preprocess import normalize_merchant
from .naver_client import naver_local_search, pick_best_item

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


RULE_KEYWORDS = {
    "simplepay": ["네이버페이", "카카오페이", "토스페이", "삼성페이", "페이코", "payco", "쿠팡"],
    "mart_convenience": ["gs25", "cu", "세븐일레븐", "이마트", "롯데마트", "홈플러스", "마트"],
    "cafe_dessert": ["스타벅스", "투썸", "이디야", "메가커피", "빽다방", "카페", "커피", "베이커리"],
    "food": ["식당", "한식", "중식", "일식", "분식", "치킨", "피자", "버거", "음식"],
    "health": ["병원", "약국", "의원", "치과", "한의원"],
    "education": ["학원", "교육", "교습", "독서실", "스터디"],
    "ott_culture": ["넷플릭스", "유튜브", "영화", "극장", "게임", "pc방", "만화"],
    "shopping": ["올리브영", "다이소", "백화점", "쇼핑", "의류", "무신사"],
}

NAVER_TO_LABEL = {
    "mart_convenience": ["편의점", "마트", "슈퍼"],
    "cafe_dessert": ["카페", "커피", "디저트", "베이커리"],
    "food": ["음식점", "한식", "중식", "일식", "양식", "분식", "치킨", "피자", "패스트푸드"],
    "health": ["병원", "약국", "의원", "치과", "한의원", "건강"],
    "education": ["학원", "교육", "교습", "독서실", "학교"],
    "ott_culture": ["영화", "극장", "공연", "문화", "게임", "pc방", "만화"],
    "shopping": ["쇼핑", "백화점", "의류", "생활", "전자", "문구"],
}

PAY_HINTS = ["카카오페이", "네이버페이", "갤럭시아", "ARS", "이투유", "쿠팡이츠", "페이먼츠", "NICE", "쿠팡", "리디"]


def _rule_label(text:str) -> str:
    s = (text or "").lower().replace(" ", "")
    for label, keys in RULE_KEYWORDS.items():
        for k in keys:
            if k.lower().replace(" ", "") in s:
                return label
            
    return "etc"

def _is_platform_txn(text: str) -> bool:
    s = (text or "").replace(" ", "")
    return any(k.replace(" ", "") in s for k in PAY_HINTS)

def _load_cache(cache_path:str) -> dict:
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
    
def _save_cache(cache: dict, cache_path: str) -> None:
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def _label_from_naver_category(cat: str) -> str:
    if not cat:
        return "etc"

    # "카페,디저트>카페" -> ["카페", "디저트", "카페"]
    tokens = [t.strip() for t in re.split(r"[>,]", cat) if t.strip()]

    for label, keywords in NAVER_TO_LABEL.items():    
        for kw in keywords:    
            if any(kw in tok for tok in tokens):
                return label
    return "etc"

def categorize_transactions(df: pd.DataFrame, cache_path:str) -> pd.DataFrame:
    cache = _load_cache(cache_path)

    out = df.copy()
    out["merchant_raw"] = out["notes"].astype(str)
    out["merchant_norm"] = out["merchant_raw"].apply(normalize_merchant)
    out["category_rule"] = out["merchant_raw"].apply(_rule_label)


    mapped = []
    naver_cat = []
    note = []

    cache_hit = 0
    api_call = 0

    for raw, norm, rule in zip(out["merchant_raw"], out["merchant_norm"], out["category_rule"]):
        if rule != "etc":
            mapped.append(None)
            naver_cat.append(None)
            note.append(None)
            continue

        if _is_platform_txn(raw):
            mapped.append("simplepay")
            naver_cat.append(None)
            note.append("pay_hint")
            continue

        if norm in cache:
            mapped.append(cache[norm].get("mapped_label"))
            naver_cat.append(cache[norm].get("naver_category"))
            note.append("cache")
            cache_hit += 1
            continue
            
        resp = naver_local_search(norm, display=5)
        api_call += 1
        best = pick_best_item(resp)
        cat = best.get("category") if best else None
        lab = _label_from_naver_category(cat)

        cache[norm] = {
            "merchant_norm": norm,
            "naver_category": cat,
            "mapped_label": lab,
            "note": "naver"
            }
        mapped.append(lab)
        naver_cat.append(cat)
        note.append("naver")

    out["mapped_label"] = mapped
    out["naver_category"] = naver_cat
    out["note"] = note

    out["category_final"] = out["category_rule"]
    mask = out["category_final"] == "etc"
    out.loc[mask, "category_final"] = out.loc[mask, "mapped_label"].fillna("etc")

    _save_cache(cache, cache_path)

    # 로깅 측정
    total_requests = cache_hit + api_call
    if total_requests > 0:
        hit_rate = (cache_hit / total_requests) * 100
    logger.info(f"--- 카테고리 매핑 완료 ---")
    logger.info(f"총 외부 매핑 시도: {total_requests}건")
    logger.info(f"캐시 적중: {cache_hit}건 (적중률: {hit_rate:.2f}%)")
    logger.info(f"API 호출: {api_call}건")

    return out










# def _match_label(text: str, keyword_map: Dict[str, List[str]], default: str = "etc") -> str:
#     s = str(text or "").replace(" ", "").lower()
#     for label, keywords in keyword_map.items():
#         for keyword in keywords:
#             if keyword.replace(" ", "").lower() in s:
#                 return label
#     return default


# def rule_label_from_merchant(merchant_raw:str) -> str:
#     return _match_label(merchant_raw, RULE_KEYWORDS, default="etc")


# def label_from_naver_category(category:str) -> str:
#     if not category:
#         return "etc"
#     return _match_label(category, NAVER_CATEGORY_KEYWORDS, default="etc")


# def is_platform_txn(merchant_raw: str) -> bool:
#     s = str(merchant_raw or "").replace(" ", "")
#     return any(k.replace(" ", "") in s for k in PAY_HINTS)


# def build_query_candidates(merchant_raw: str):
#     base = normalize_merchant(merchant_raw)
#     cands = [base]

#     m = re.match(r"^(.*)\((.*)\)$", base)
#     if m:
#         main = m.group(1).strip()
#         branch = m.group(2).strip()
#         if main:
#             cands.append(main)
#         if main and branch:
#             cands.append(f"{main} {branch}")

#     cleaned = base.replace("결제", " ").replace("승인", " ").replace("CJ", " ").replace("씨제이올리브네트웍스", "올리브영")
#     cleaned = re.sub(r"\s+", " ", cleaned).strip()
#     if cleaned and cleaned != base:
#         cands.append(cleaned)

#     uniq = []
#     for q in cands:
#         q = q.strip()
#         if q and q not in uniq:
#             uniq.append(q)
#     return uniq


# def enrich_one(
#     merchant_raw: str,
#     cache: Dict[str, dict],
#     search_func: Optional[Callable[..., dict]] = None,
#     sleep_s: float = 0.12,
# ):
#     key = normalize_merchant(merchant_raw)
#     if key in cache:
#         return cache[key]

#     if is_platform_txn(merchant_raw):
#         out = {
#             "merchant_norm": key,
#             "naver_category": None,
#             "mapped_label": "simplepay",
#             "note": "simplepay_txn",
#         }
#         cache[key] = out
#         return out

#     search = search_func or naver_local_search

#     for q in build_query_candidates(merchant_raw):
#         try:
#             resp = search(q, display=5)
#             best = pick_best_item(resp)
#         except Exception as e:
#             best = None
#             last_error = str(e)
#         else:
#             last_error = None

#         if best and best.get("category"):
#             out = {
#                 "merchant_norm": key,
#                 "naver_category": best["category"],
#                 "mapped_label": label_from_naver_category(best["category"]),
#                 "note": f"query={q}",
#             }
#             cache[key] = out
#             time.sleep(sleep_s)
#             return out
#         time.sleep(sleep_s)

#     out = {
#         "merchant_norm": key,
#         "naver_category": None,
#         "mapped_label": "etc",
#         "note": f"no_result:{last_error}" if last_error else "no_result",
#     }
#     cache[key] = out
#     return out


# def categorize_transactions(df: pd.DataFrame, cache: Dict[str, dict]) -> pd.DataFrame:
#     out = df.copy()
#     if "notes" not in out.columns:
#         raise KeyError("categorize_transactions requires 'notes' column")

#     out["merchant_raw"] = out["notes"].astype(str)
#     out["merchant_norm"] = out["merchant_raw"].apply(normalize_merchant)
#     out["category_rule"] = out["merchant_raw"].apply(rule_label_from_merchant)

#     mask_etc = out["category_rule"].eq("etc")
#     for merchant in out.loc[mask_etc, "merchant_raw"].dropna().unique().tolist():
#         enrich_one(merchant, cache)

#     if cache:
#         cache_df = pd.DataFrame(cache.values())
#         if not cache_df.empty:
#             cols = [c for c in ["merchant_norm", "naver_category", "mapped_label", "note"] if c in cache_df.columns]
#             out = out.merge(cache_df[cols].drop_duplicates("merchant_norm"), on="merchant_norm", how="left")
#     else:
#         out["naver_category"] = None
#         out["mapped_label"] = None

#     out["category_final"] = out["category_rule"]
#     mask_fill = out["category_rule"].eq("etc")
#     out.loc[mask_fill, "category_final"] = out.loc[mask_fill, "mapped_label"].fillna("etc")
#     return out
