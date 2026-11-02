# ⚡ Prompt Engineering Studio

![CI](https://github.com/Mayank-thakur21/octo-train-prompt/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green)
![License](https://img.shields.io/badge/license-MIT-yellow)

A full-featured **Prompt Engineering Studio** for testing, comparing, and managing AI prompts. Built with FastAPI + vanilla JS (no framework bloat).

---

## ✨ Features

| Feature | Description |
|--------|-------------|
| 🚀 Prompt Runner | Run prompts with any Gemini model, adjust temperature |
| ⚖️ A/B Testing | Compare two prompt variants side by side |
| 📊 Token Counter | Real-time token estimation |
| 📚 Templates | 8+ built-in prompt templates (summarizer, coder, translator...) |
| 💾 Prompt Library | Save and reuse your best prompts with tags |
| 📜 History | Full run history with one-click reload |
| 🤖 Multi-model | Switch between Gemini Flash, Pro, and 2.0 |
| 🐳 Docker Ready | One-command deploy |

---

## 🚀 Quick Start

### Option 1: Docker
```bash
git clone https://github.com/Mayank-thakur21/octo-train-prompt
cd octo-train-prompt
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
docker-compose up --build
```
- Studio UI: http://localhost:3000
- API: http://localhost:8000/docs

### Option 2: Manual
```bash
# Backend
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env
uvicorn main:app --reload

# Frontend — just open in browser
open frontend/index.html
# Or serve with: python -m http.server 3000 -d frontend
```

---

## 🔑 API Key
Get a free Gemini API key at https://aistudio.google.com  
Add it to `.env`:
```
GEMINI_API_KEY=your_key_here
```
> **Note:** The app works in **demo mode** without an API key — responses are simulated.

---

## 📡 API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/run` | Run a single prompt |
| POST | `/ab-test` | A/B compare two prompts |
| POST | `/token-count` | Count tokens in text |
| GET | `/history` | Prompt run history |
| GET/POST | `/prompts` | Save/list prompt library |
| GET | `/templates` | Built-in templates |
| GET | `/models` | Available models |

---

## 🏗️ Project Structure
```
octo-train-prompt/
├── backend/
│   ├── main.py           # FastAPI app
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   └── index.html        # Single-file studio UI
├── .env.example
├── docker-compose.yml
└── README.md
```

---

## 📄 License
MIT © Mayank Thakur
