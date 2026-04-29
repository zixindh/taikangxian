# Gemini Chat Streamlit App

Minimal Streamlit chat UI for Gemini using the direct Gemini API.

## Streamlit Cloud setup

1. Connect this repository in Streamlit Cloud.
2. Set the app entry point to `app.py`.
3. Add these secrets in Streamlit Cloud:

```toml
GEMINI_API_KEY = "your-gemini-api-key"
NOTION_API_KEY = "your-notion-api-key"
NOTION_DATABASE_ID = "your-notion-database-id"
```

`NOTION_API_KEY` and `NOTION_DATABASE_ID` are optional. If `NOTION_DATABASE_ID`
is omitted, the app uses the database ID already configured in `app.py`.

## Local run

```bash
pip install -r requirements.txt
streamlit run app.py
```
