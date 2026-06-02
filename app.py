"""
Minimal Streamlit chat app for Gemini.

Secrets expected on Streamlit Cloud:
- GEMINI_API_KEY
- NOTION_API_KEY, optional (also used to persist user preferences)
- NOTION_DATABASE_ID, optional
"""

from __future__ import annotations

import io
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

try:  # optional: clipboard paste support
    from streamlit_paste_button import paste_image_button as _paste_image_button
except Exception:  # pragma: no cover - component is optional
    _paste_image_button = None


APP_DIR = Path(__file__).parent
MODELS_FILE = APP_DIR / "models.json"
PREFS_FILE = APP_DIR / "prefs.json"
DEFAULT_NOTION_DB = "30ba6041-f59c-811a-8cde-cf1d8a9db1d6"
DEFAULT_MODEL = "gemini-3-flash-preview"
CONFIG_MARKER = "__APP_CONFIG__"
IMAGE_TYPES = ["png", "jpg", "jpeg", "webp", "gif"]


def _secret(name: str, default: str = "") -> str:
    """Read from Streamlit secrets first, then environment variables."""
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return str(value or os.environ.get(name, default) or "").strip()


def _load_models() -> list[str]:
    try:
        data = json.loads(MODELS_FILE.read_text(encoding="utf-8"))
        models = [m["id"] for m in data if m.get("id") and m.get("type", "chat") == "chat"]
        return models or [DEFAULT_MODEL]
    except Exception:
        return [DEFAULT_MODEL]


@st.cache_resource(show_spinner=False)
def _client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


# ---------------------------------------------------------------------------
# Notion helpers
# ---------------------------------------------------------------------------

def _notion_url(raw_id: str) -> str:
    return "https://www.notion.so/" + raw_id.replace("-", "")


def _chunks(text: str, size: int = 2000) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


def _notion_request(method: str, url: str, body: dict | None, notion_key: str) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {notion_key}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
    body = {
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
    try:
        _notion_request("POST", "https://api.notion.com/v1/pages", body, notion_key)
    except Exception as exc:
        print(f"[Notion log failed] {exc}")


def _notion_log_async(prompt: str, response: str, model: str, search: bool) -> None:
    notion_key = _secret("NOTION_API_KEY")
    notion_db = _secret("NOTION_DATABASE_ID", DEFAULT_NOTION_DB)
    threading.Thread(
        target=_notion_log,
        args=(prompt, response, model, search, notion_key, notion_db),
        daemon=True,
    ).start()


# ---------------------------------------------------------------------------
# Preferences (default model + custom models), persisted to Notion + local file
# ---------------------------------------------------------------------------

def _default_prefs() -> dict:
    return {"default_model": DEFAULT_MODEL, "custom_models": []}


def _read_local_prefs() -> dict:
    try:
        prefs = json.loads(PREFS_FILE.read_text(encoding="utf-8"))
        return {**_default_prefs(), **prefs}
    except Exception:
        return _default_prefs()


def _write_local_prefs(prefs: dict) -> None:
    try:
        PREFS_FILE.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"[Local prefs write failed] {exc}")


def _notion_read_prefs(notion_key: str, notion_db: str) -> tuple[dict | None, str | None]:
    """Return (prefs, config_page_id) from the Notion config row, if present."""
    if not notion_key or not notion_db:
        return None, None
    try:
        result = _notion_request(
            "POST",
            f"https://api.notion.com/v1/databases/{notion_db}/query",
            {
                "filter": {"property": "Prompt", "title": {"equals": CONFIG_MARKER}},
                "page_size": 1,
            },
            notion_key,
        )
        pages = result.get("results") or []
        if not pages:
            return None, None
        page = pages[0]
        rich = page.get("properties", {}).get("Response", {}).get("rich_text", [])
        raw = "".join(part.get("plain_text", "") for part in rich)
        prefs = {**_default_prefs(), **json.loads(raw)} if raw else _default_prefs()
        return prefs, page.get("id")
    except Exception as exc:
        print(f"[Notion prefs read failed] {exc}")
        return None, None


def _notion_write_prefs(prefs: dict, page_id: str | None) -> str | None:
    notion_key = _secret("NOTION_API_KEY")
    notion_db = _secret("NOTION_DATABASE_ID", DEFAULT_NOTION_DB)
    if not notion_key or not notion_db:
        return page_id
    payload = json.dumps(prefs)
    properties = {
        "Response": {"rich_text": [{"text": {"content": c}} for c in _chunks(payload)]},
        "Date": {"date": {"start": datetime.now().astimezone().isoformat()}},
    }
    try:
        if page_id:
            _notion_request(
                "PATCH",
                f"https://api.notion.com/v1/pages/{page_id}",
                {"properties": properties},
                notion_key,
            )
            return page_id
        body = {
            "parent": {"database_id": notion_db},
            "properties": {
                "Prompt": {"title": [{"text": {"content": CONFIG_MARKER}}]},
                "Model": {"select": {"name": "config"}},
                "Search": {"checkbox": False},
                **properties,
            },
        }
        created = _notion_request("POST", "https://api.notion.com/v1/pages", body, notion_key)
        return created.get("id")
    except Exception as exc:
        print(f"[Notion prefs write failed] {exc}")
        return page_id


@st.cache_data(show_spinner=False, ttl=3600)
def _load_prefs(notion_key: str, notion_db: str) -> tuple[dict, str | None]:
    prefs, page_id = _notion_read_prefs(notion_key, notion_db)
    if prefs is not None:
        return prefs, page_id
    return _read_local_prefs(), None


def _save_prefs() -> None:
    prefs = {
        "default_model": st.session_state.get("model_select", DEFAULT_MODEL),
        "custom_models": st.session_state.get("custom_models", []),
    }
    _write_local_prefs(prefs)
    page_id = _notion_write_prefs(prefs, st.session_state.get("config_page_id"))
    st.session_state.config_page_id = page_id
    _load_prefs.clear()


# ---------------------------------------------------------------------------
# Gemini helpers
# ---------------------------------------------------------------------------

def _to_contents(messages: list[dict]) -> list[types.Content]:
    contents: list[types.Content] = []
    for message in messages:
        parts: list[types.Part] = []
        text = message.get("content", "")
        if text:
            parts.append(types.Part.from_text(text=text))
        for img in message.get("images", []):
            parts.append(
                types.Part.from_bytes(data=img["data"], mime_type=img["mime"])
            )
        if not parts:
            continue
        role = "user" if message.get("role") == "user" else "model"
        contents.append(types.Content(role=role, parts=parts))
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
        model=model, contents=contents, config=config
    )
    for chunk in response:
        if chunk.text:
            yield chunk.text


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def _apply_style() -> None:
    st.markdown(
        """
        <style>
        .stApp { background: #f7f7f8; color: #1a1a1a; }
        .block-container {
            max-width: 1100px;
            padding-top: 1.4rem;
            padding-bottom: 2rem;
            padding-left: 2rem;
            padding-right: 2rem;
        }
        h1 {
            text-align: center;
            font-size: 1.65rem !important;
            line-height: 1.2 !important;
            margin-bottom: .25rem !important;
        }
        [data-testid="stCaptionContainer"] { text-align: center; color: #666; }
        [data-testid="stChatMessage"] {
            border-radius: 14px;
            border: 1px solid #e8e8e8;
            background: #fff;
            padding: .55rem .7rem;
        }
        [data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid #ededed; }
        .stButton > button { border-radius: 10px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _add_custom_model() -> None:
    name = (st.session_state.get("custom_model_input") or "").strip()
    if not name:
        return
    customs = st.session_state.setdefault("custom_models", [])
    if name not in customs:
        customs.append(name)
    st.session_state.model_select = name  # take effect immediately
    st.session_state.custom_model_input = ""
    _save_prefs()


def _collect_pending_images() -> None:
    """Render attachment controls; populate st.session_state.pending_images."""
    pending: list[dict] = st.session_state.setdefault("pending_images", [])

    if _paste_image_button is not None:
        pasted = _paste_image_button(
            "📋 Paste image from clipboard",
            text_color="#1a1a1a",
            background_color="#ffffff",
            hover_background_color="#f0f0f0",
            errors="ignore",
            key="paste_btn",
        )
        if getattr(pasted, "image_data", None) is not None:
            buf = io.BytesIO()
            pasted.image_data.convert("RGB").save(buf, format="PNG")
            data = buf.getvalue()
            if not any(p["data"] == data for p in pending):
                pending.append({"mime": "image/png", "data": data})

    if pending:
        st.caption(f"{len(pending)} image(s) attached")
        cols = st.columns(min(len(pending), 3))
        for i, img in enumerate(pending):
            cols[i % len(cols)].image(img["data"], use_container_width=True)
        if st.button("Remove attachments", use_container_width=True):
            st.session_state.pending_images = []
            st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="Gemini Chat",
        page_icon=":material/chat:",
        layout="wide",
    )
    _apply_style()

    api_key = _secret("GEMINI_API_KEY") or _secret("GOOGLE_API_KEY")
    notion_key = _secret("NOTION_API_KEY")
    notion_db = _secret("NOTION_DATABASE_ID", DEFAULT_NOTION_DB)
    base_models = _load_models()

    # Load persisted preferences once per session.
    if "prefs_loaded" not in st.session_state:
        prefs, page_id = _load_prefs(notion_key, notion_db)
        st.session_state.custom_models = list(prefs.get("custom_models", []))
        st.session_state.config_page_id = page_id
        default_model = prefs.get("default_model", DEFAULT_MODEL)
        st.session_state.model_select = default_model
        st.session_state.prefs_loaded = True

    if "messages" not in st.session_state:
        st.session_state.messages = []
    st.session_state.setdefault("pending_images", [])

    # Build the dropdown options: base models + user custom models (deduped).
    options: list[str] = []
    for m in base_models + st.session_state.custom_models:
        if m not in options:
            options.append(m)
    if st.session_state.get("model_select") not in options:
        options.append(st.session_state["model_select"])

    st.title("Gemini Chat")
    st.caption("Minimal chat interface using the direct Gemini API")

    with st.sidebar:
        st.subheader("Settings")
        selected_model = st.selectbox("Model", options, key="model_select")

        st.text_input(
            "Add custom model",
            key="custom_model_input",
            placeholder="e.g. gemini-3-pro-preview",
            on_change=_add_custom_model,
        )
        col_a, col_b = st.columns(2)
        col_a.button("Add model", use_container_width=True, on_click=_add_custom_model)
        if col_b.button("Set as default", use_container_width=True):
            _save_prefs()
            st.toast(f"Default model set to {selected_model}")

        search = st.toggle("Google Search grounding", value=True)

        st.divider()
        st.markdown("**Attachments**")
        _collect_pending_images()

        st.divider()
        if st.button("Clear chat", use_container_width=True):
            st.session_state.messages = []
            st.session_state.pending_images = []
            st.rerun()

        st.divider()
        st.markdown("**Chat history**")
        st.markdown(
            f"Saved to Notion: [open database]({_notion_url(notion_db)})"
            if notion_key
            else "_Notion logging is not configured._"
        )
        page_id = st.session_state.get("config_page_id")
        if page_id:
            st.caption(f"[Preferences page]({_notion_url(page_id)})")
        st.caption("Add GEMINI_API_KEY in Streamlit Cloud app secrets.")

    if not api_key:
        st.error(
            "GEMINI_API_KEY is not set. Add it to Streamlit secrets or your environment."
        )
        st.stop()

    client = _client(api_key)

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if message.get("content"):
                st.markdown(message["content"])
            for img in message.get("images", []):
                st.image(img["data"])

    user_input = st.chat_input(
        "Type a message...",
        accept_file="multiple",
        file_type=IMAGE_TYPES,
    )
    if not user_input:
        return

    prompt = (user_input.text or "").strip()
    images: list[dict] = list(st.session_state.pending_images)
    for f in user_input.files or []:
        images.append({"mime": f.type or "image/png", "data": f.getvalue()})

    if not prompt and not images:
        return

    st.session_state.pending_images = []
    model_name = selected_model

    with st.chat_message("user"):
        if prompt:
            st.markdown(prompt)
        for img in images:
            st.image(img["data"])

    st.session_state.messages.append(
        {"role": "user", "content": prompt, "images": images}
    )

    with st.chat_message("assistant"):
        placeholder = st.empty()
        try:
            stream = _stream_gemini(
                client=client,
                model=model_name,
                contents=_to_contents(st.session_state.messages),
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
