from __future__ import annotations
from typing import Dict, List
import requests

def get_chat_response(messages: List[Dict[str, str]], session_id: str, api_base_url: str, timeout_s: float = 60.0) -> str:
    url = api_base_url.rstrip("/") + "/chat"
    resp = requests.post(url, json={"session_id": session_id, "messages": messages}, timeout=timeout_s)
    return resp.json()["answer"]

