from __future__ import annotations
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

# 거래내역
class TransactionIn(BaseModel):
    notes: str = Field(default="", description="결제처/메모")
    amount: float = Field(default=0, description="결제 금액")

# 거래 내역으로 추천 요청
class RecommendRequest(BaseModel):
    transactions: List[TransactionIn]
    topn: int
    use_naver: bool = True
    cate_filter: str = "ALL"  # ALL | CRD | CHK

# 카드 DB Out
class CardOut(BaseModel):
    card_name: str
    issuer: str
    cate: Optional[str] = None
    note: Optional[str] = None

    score_adj: float
    score_capped: float
    score_raw: float

    eligible: Optional[bool] = None
    prev_month_spend: Optional[float] = None
    monthly_cap: Optional[float] = None
    annual_fee: Optional[float] = None
    condition_text: Optional[str] = None

# 추천 실행 후 받아온 것
class RecommendResponse(BaseModel):
    spend: Dict[str, float]
    total_spend: float
    top: List[CardOut]

# 챗 메세지
class ChatMessage(BaseModel):
    role: str
    content: str

# query 요청?
class ChatRequest(BaseModel):
    session_id: str
    messages: List[ChatMessage]

# 챗봇 답변
class ChatResponse(BaseModel):
    answer: str

# 업로드 응답
class UploadResponse(BaseModel):
    session_id: str
    rows: int
