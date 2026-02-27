from __future__ import annotations

import os
import uuid
import traceback
from typing import Dict, List
import requests
import streamlit as st

st.set_page_config(page_title="Card Chatbot", page_icon="💬", layout="wide")
st.title("카드 추천 챗봇 (MVP)")
st.caption("업로드 -> 추천 대화 흐름만 최소로 구현")

# 세션 id
if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())

if "chat_messages" not in st.session_state:
    st.session_state["chat_messages"]: List[Dict[str, str]] = [
        {"role": "assistant", "content": "안녕하세요! 먼저 거래내역 파일을 업로드해 주세요."}
    ]

with st.sidebar:
    st.header("연결 설정")
    api_base_url = st.text_input("API Base URL", value=os.getenv("BACKEND_URL", "http://127.0.0.1:8000"))
    timeout_s = st.slider("Timeout (sec)", 5, 120, 120, 5)
    show_debug = st.checkbox("디버그 보기", value=False)

    st.divider()
    st.subheader("거래내역 업로드")
    uploaded = st.file_uploader("csv/xlsx 업로드", type=["csv", "xlsx", "xls"])
    if st.button("업로드"):
        if uploaded is None:
            st.warning("파일을 선택해줘!")
        else:
            url = api_base_url.rstrip("/") + "/upload"
            params = {"session_id": st.session_state["session_id"]}
            files = {"file": (uploaded.name, uploaded.getvalue())}
            r = requests.post(url, params=params, files=files, timeout=float(timeout_s))
            if r.status_code == 200:
                data = r.json()
                st.success(f"업로드 완료! rows={data.get('rows')} session_id={data.get('session_id')}")
                st.session_state["session_id"] = data.get("session_id", st.session_state["session_id"])
            else:
                st.error(r.text)

    st.divider()
    st.caption(f"session_id: {st.session_state['session_id']}")
    if st.button("대화 초기화"):
        st.session_state["chat_messages"] = [{"role": "assistant", "content": "대화를 초기화했어요."}]
        st.rerun()

# 대화 렌더링
for msg in st.session_state["chat_messages"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

prompt = st.chat_input("메시지를 입력하세요 (예: 추천해줘 / 체크카드로 추천)")
if prompt:
    st.session_state["chat_messages"].append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("응답 생성 중..."):
            try:
                url = api_base_url.rstrip("/") + "/chat"
                payload = {
                    "session_id": st.session_state["session_id"],
                    "messages": st.session_state["chat_messages"],
                }
                r = requests.post(url, json=payload, timeout=float(timeout_s))
                answer = r.json()["answer"] if r.status_code == 200 else r.text

            except Exception as e:
                st.error(f"에러: {e}")
                if show_debug:
                    st.code(traceback.format_exc())
                answer = "죄송해요. 응답을 가져오지 못했습니다."

        st.markdown(answer)

    st.session_state["chat_messages"].append({"role": "assistant", "content": answer})

