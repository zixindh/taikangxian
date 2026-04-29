"""
Minimal Streamlit chat app for Gemini.

Secrets expected on Streamlit Cloud:
- GEMINI_API_KEY
- NOTION_API_KEY, optional
- NOTION_DATABASE_ID, optional
"""

from __future__ import annotations

import json
import os
import threading
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Iterable

import streamlit as st
from google import genai
from google.genai import types


APP_DIR = Path(__file__).parent
MODELS_FILE = APP_DIR / "models.json"
DEFAULT_NOTION_DB = "30ba6041-f59c-811a-8cde-cf1d8a9db1d6"
DEFAULT_MODEL = "gemini-3-flash-preview"


def _secret(name: str, default: str = "") -> str:
    """Read from Streamlit secrets first, then environment variables."""
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return str(value or os.environ.get(name, default) or "").strip()


def _load_models() -> list[dict[str, str]]:
    try:
        data = json.loads(MODELS_FILE.read_text(encoding="utf-8"))
        models = [m for m in data if m.get("id") and m.get("type", "chat") == "chat"]
        return models or [{"id": DEFAULT_MODEL, "type": "chat"}]
    except Exception:
        return [{"id": DEFAULT_MODEL, "type": "chat"}]


@st.cache_resource(show_spinner=False)
def _client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


def _chunks(text: str, size: int = 2000) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


def _notion_log(
    prompt: str,
    response: str,
    model: str,
    search: bool,
    notion_key: str,
    notion_db: str,
) -> None:
    if not notion_key or not notion_db:
        return

    body = json.dumps(
        {
            "parent": {"database_id": notion_db},
            "properties": {
                "Prompt": {"title": [{"text": {"content": p}} for p in _chunks(prompt)]},
                "Date": {"date": {"start": datetime.now().astimezone().isoformat()}},
                "Model": {"select": {"name": model}},
                "Search": {"checkbox": search},
                "Response": {
                    "rich_text": [{"text": {"content": c}} for c in _chunks(response)]
                },
            },
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        "https://api.notion.com/v1/pages",
        data=body,
        headers={
            "Authorization": f"Bearer {notion_key}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=20)
    except Exception as exc:
        print(f"[Notion log failed] {exc}")


def _notion_log_async(prompt: str, response: str, model: str, search: bool) -> None:
    notion_key = _secret("NOTION_API_KEY")
    notion_db = _secret("NOTION_DATABASE_ID", DEFAULT_NOTION_DB)
    thread = threading.Thread(
        target=_notion_log,
        args=(prompt, response, model, search, notion_key, notion_db),
        daemon=True,
    )
    thread.start()


def _to_contents(messages: list[dict[str, str]], prompt: str) -> list[types.Content]:
    contents: list[types.Content] = []
    for message in messages:
        text = message.get("content", "")
        if not text:
            continue
        role = "user" if message.get("role") == "user" else "model"
        contents.append(
            types.Content(role=role, parts=[types.Part.from_text(text=text)])
        )
    contents.append(
        types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
    )
    return contents


def _stream_gemini(
    client: genai.Client,
    model: str,
    contents: list[types.Content],
    search: bool,
) -> Iterable[str]:
    tools = [types.Tool(google_search=types.GoogleSearch())] if search else None
    config = types.GenerateContentConfig(tools=tools) if tools else None
    response = client.models.generate_content_stream(
        model=model,
        contents=contents,
        config=config,
    )
    for chunk in response:
        if chunk.text:
            yield chunk.text


def _apply_style() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background: #f7f7f8;
            color: #1a1a1a;
        }
        .block-container {
            max-width: 920px;
            padding-top: 1.6rem;
            padding-bottom: 2rem;
        }
        h1 {
            text-align: center;
            font-size: 1.65rem !important;
            line-height: 1.2 !important;
            margin-bottom: .25rem !important;
        }
        [data-testid="stCaptionContainer"] {
            text-align: center;
            color: #666;
        }
        [data-testid="stChatMessage"] {
            border-radius: 14px;
            border: 1px solid #e8e8e8;
            background: #fff;
            padding: .55rem .7rem;
        }
        [data-testid="stSidebar"] {
            background: #ffffff;
            border-right: 1px solid #ededed;
        }
        .stButton > button {
            border-radius: 10px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="Gemini Chat",
        page_icon=":material/chat:",
        layout="centered",
    )
    _apply_style()

    api_key = _secret("GEMINI_API_KEY") or _secret("GOOGLE_API_KEY")
    models = _load_models()
    model_ids = [m["id"] for m in models]

    if "messages" not in st.session_state:
        st.session_state.messages = []

    st.title("Gemini Chat")
    st.caption("Minimal chat interface using the direct Gemini API")

    with st.sidebar:
        st.subheader("Settings")
        selected_model = st.selectbox(
            "Model",
            model_ids,
            index=model_ids.index(DEFAULT_MODEL) if DEFAULT_MODEL in model_ids else 0,
        )
        custom_model = st.text_input("Custom model", placeholder="gemini-3-flash-preview")
        model_name = custom_model.strip() or selected_model
        search = st.toggle("Google Search grounding", value=False)

        if st.button("Clear chat", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

        st.divider()
        st.caption("For Streamlit Cloud, add GEMINI_API_KEY in app secrets.")

    if not api_key:
        st.error(
            "GEMINI_API_KEY is not set. Add it to Streamlit secrets or your environment."
        )
        st.stop()

    client = _client(api_key)

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input("Type a message...")
    if not prompt:
        return

    with st.chat_message("user"):
        st.markdown(prompt)

    prior_messages = list(st.session_state.messages)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        placeholder = st.empty()
        try:
            stream = _stream_gemini(
                client=client,
                model=model_name,
                contents=_to_contents(prior_messages, prompt),
                search=search,
            )
            response = st.write_stream(stream)
        except Exception as exc:
            response = f"**Error:** {exc}"
            placeholder.markdown(response)

    if isinstance(response, list):
        response = "".join(str(part) for part in response)
    response = str(response)
    st.session_state.messages.append({"role": "assistant", "content": response})
    _notion_log_async(prompt, response, model_name, search)


if __name__ == "__main__":
    main()
