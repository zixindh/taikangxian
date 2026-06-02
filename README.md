# Gemini Chat Streamlit App

Minimal Streamlit chat UI for Gemini using the direct Gemini API.

## Features

- **Custom models** — type a model name and press Enter (or "Add model") to add it
  to the dropdown instantly; it is selected and used right away.
- **Default model** — "Set as default" persists your choice for future sessions
  (stored in Notion when configured, with a local `prefs.json` fallback). Custom
  models you add are remembered too.
- **Images** — attach images directly in the chat box (upload / drag-and-drop) or
  paste from the clipboard via the sidebar button. Vision works across turns.
- **Notion logging** — every exchange is saved to a Notion database; the sidebar
  links to that database (and to the preferences page).
- **Wide layout** — content fills more of the screen with minimal side margins.

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
