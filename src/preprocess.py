import re
import pandas as pd


def input_excel_preprocessing(df):
    # 카드사 엑셀 형식: 첫 행을 컬럼명으로 쓰고 불필요한 상단 행 제거
    df = df.copy()
    df.columns = df.iloc[0]
    df = df.iloc[2:].reset_index(drop=True)
    df.columns = df.columns.astype(str).str.replace("\n", "", regex=False).str.strip()

    def _find_col(candidates):
        normalized = {str(c).replace(" ", "").lower(): c for c in df.columns}
        for cand in candidates:
            key = cand.replace(" ", "").lower()
            if key in normalized:
                return normalized[key]
        for norm_key, original in normalized.items():
            if any(cand.replace(" ", "").lower() in norm_key for cand in candidates):
                return original
        raise KeyError(f"필수 컬럼을 찾지 못했습니다. columns={list(df.columns)}")

    col_date = _find_col(["이용일자", "사용일자", "거래일자", "date"])
    col_merchant = _find_col(["이용가맹점", "가맹점명", "사용처", "적요", "notes", "note"])
    col_amount = _find_col(["이용금액", "결제금액", "승인금액", "amount"])

    std = pd.DataFrame(
        {
            "date": df[col_date].astype(str).str.strip(),
            "notes": df[col_merchant].astype(str).str.strip(),
            "amount": pd.to_numeric(
                df[col_amount]
                .astype(str)
                .str.replace(",", "", regex=False)
                .str.replace(r"[^0-9.\-]", "", regex=True),
                errors="coerce",
            ),
        }
    ).dropna(subset=["notes", "amount"]).reset_index(drop=True)

    std["amount"] = std["amount"].astype(int)
    return std


# note(이용가맹점) 문자열 1차 정제
def make_merchant_raw(notes:str) -> str:
    s = str(notes).strip().replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


# 네이버 검색에 방해되는 표현 제거
def normalize_merchant(merchant_raw:str) -> str:
    corp_words = [
        "주식회사",
        "(주)",
        "주)",
        "(유)",
        "유한회사",
        "본사",
        "직영",
        "대리점",
        "한국",
    ]

    name = str(merchant_raw).strip()
    for word in corp_words:
        name = name.replace(word, " ")
    name = re.sub(r"[^\w\s가-힣()]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


# 네이버 검색 결과의 HTML 태그 제거
def strip_html(s: str) -> str:
    return re.sub(r"<.*?>", "", s or "")
