from urllib.parse import quote

import requests

try:
    from .preprocess import strip_html
    from .settings import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET
except ImportError:
    from preprocess import strip_html
    from settings import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET


def naver_local_search(query: str, display: int = 5):
    client_id = NAVER_CLIENT_ID
    client_secret = NAVER_CLIENT_SECRET
    if not client_id or not client_secret:
        raise RuntimeError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수가 필요합니다. (.env 로드 확인)")

    url = (
        "https://openapi.naver.com/v1/search/local.json"
        f"?query={quote(query)}&display={display}&start=1"
    )
    headers = {
        "X-Naver-Client-Id": client_id.strip(),
        "X-Naver-Client-Secret": client_secret.strip(),
    }
    r = requests.get(url, headers=headers, timeout=10)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def pick_best_item(resp):
    items = (resp or {}).get("items") or []
    if not items:
        return None
    it = items[0]
    return {
        "title": strip_html(it.get("title")),
        "category": it.get("category"),
        "roadAddress": it.get("roadAddress"),
    }
