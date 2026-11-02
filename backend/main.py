"""
Prompt Engineering Studio — FastAPI Backend
Features: prompt testing, A/B comparison, token counting, history, templates
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import os
import time
import logging
from datetime import datetime
from uuid import uuid4
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PromptStudio")

app = FastAPI(title="Prompt Engineering Studio API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory stores ──────────────────────────────────────────────────────────
prompt_history: List[dict] = []
saved_prompts: List[dict] = []

# ── Models ────────────────────────────────────────────────────────────────────
AVAILABLE_MODELS = {
    "gemini-1.5-flash": "Google Gemini 1.5 Flash (fast, free)",
    "gemini-1.5-pro": "Google Gemini 1.5 Pro (smart)",
    "gemini-2.0-flash": "Google Gemini 2.0 Flash (latest)",
}


class PromptRequest(BaseModel):
    prompt: str
    system_prompt: Optional[str] = None
    model: str = "gemini-1.5-flash"
    temperature: float = 0.7
    max_tokens: int = 1024


class ABTestRequest(BaseModel):
    prompt_a: str
    prompt_b: str
    system_prompt: Optional[str] = None
    model: str = "gemini-1.5-flash"
    temperature: float = 0.7


class SavePromptRequest(BaseModel):
    name: str
    prompt: str
    system_prompt: Optional[str] = None
    tags: List[str] = []
    description: str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────
def count_tokens(text: str) -> int:
    """Rough token estimate (4 chars ≈ 1 token)."""
    return max(1, len(text) // 4)


def call_gemini(prompt: str, system: Optional[str], model: str, temperature: float, max_tokens: int) -> dict:
    """Call Google Gemini API."""
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        # Demo mode
        return {
            "text": f"[Demo mode] This is a simulated response to: '{prompt[:80]}...'\n\nSet GEMINI_API_KEY in .env to get real responses.",
            "model": model,
            "input_tokens": count_tokens((system or "") + prompt),
            "output_tokens": 42,
            "latency_ms": 0,
            "demo": True,
        }
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        m = genai.GenerativeModel(
            model_name=model,
            system_instruction=system or "You are a helpful assistant.",
            generation_config=genai.types.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
        )
        start = time.time()
        response = m.generate_content(prompt)
        latency = round((time.time() - start) * 1000)
        text = response.text
        return {
            "text": text,
            "model": model,
            "input_tokens": count_tokens((system or "") + prompt),
            "output_tokens": count_tokens(text),
            "latency_ms": latency,
            "demo": False,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI API error: {str(e)}")


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"message": "Prompt Engineering Studio API", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.get("/models")
def get_models():
    return {"models": [{"id": k, "name": v} for k, v in AVAILABLE_MODELS.items()]}

@app.post("/run")
def run_prompt(req: PromptRequest):
    """Run a single prompt and return the response."""
    result = call_gemini(req.prompt, req.system_prompt, req.model, req.temperature, req.max_tokens)
    entry = {
        "id": str(uuid4())[:8],
        "timestamp": datetime.utcnow().isoformat(),
        "prompt": req.prompt[:200],
        "system_prompt": req.system_prompt,
        "model": req.model,
        "temperature": req.temperature,
        **result,
    }
    prompt_history.insert(0, entry)
    if len(prompt_history) > 100:
        prompt_history.pop()
    return entry

@app.post("/ab-test")
def ab_test(req: ABTestRequest):
    """Run A/B test comparing two prompts side by side."""
    result_a = call_gemini(req.prompt_a, req.system_prompt, req.model, req.temperature, 1024)
    result_b = call_gemini(req.prompt_b, req.system_prompt, req.model, req.temperature, 1024)
    return {
        "prompt_a": {"prompt": req.prompt_a, **result_a},
        "prompt_b": {"prompt": req.prompt_b, **result_b},
        "comparison": {
            "latency_diff_ms": result_b["latency_ms"] - result_a["latency_ms"],
            "token_diff": result_b["output_tokens"] - result_a["output_tokens"],
            "a_shorter": result_a["output_tokens"] < result_b["output_tokens"],
        }
    }

@app.post("/token-count")
def token_count(body: dict):
    text = body.get("text", "")
    return {
        "text_length": len(text),
        "estimated_tokens": count_tokens(text),
        "words": len(text.split()),
    }

@app.get("/history")
def get_history(limit: int = 20):
    return {"history": prompt_history[:limit], "total": len(prompt_history)}

@app.delete("/history")
def clear_history():
    prompt_history.clear()
    return {"message": "History cleared"}

@app.post("/prompts")
def save_prompt(req: SavePromptRequest):
    """Save a prompt to the library."""
    entry = {
        "id": str(uuid4())[:8],
        "created_at": datetime.utcnow().isoformat(),
        "name": req.name,
        "prompt": req.prompt,
        "system_prompt": req.system_prompt,
        "tags": req.tags,
        "description": req.description,
    }
    saved_prompts.insert(0, entry)
    return entry

@app.get("/prompts")
def list_prompts(tag: Optional[str] = None):
    """List saved prompts, optionally filtered by tag."""
    if tag:
        filtered = [p for p in saved_prompts if tag in p.get("tags", [])]
        return {"prompts": filtered}
    return {"prompts": saved_prompts}

@app.delete("/prompts/{prompt_id}")
def delete_prompt(prompt_id: str):
    global saved_prompts
    saved_prompts = [p for p in saved_prompts if p["id"] != prompt_id]
    return {"message": "Deleted"}

@app.get("/templates")
def get_templates():
    """Return built-in prompt templates."""
    return {"templates": [
        {"name": "Summarizer", "tags": ["writing"], "prompt": "Summarize the following text in 3 bullet points:\n\n{text}", "system_prompt": "You are a concise summarizer."},
        {"name": "Code Reviewer", "tags": ["code"], "prompt": "Review this code and suggest improvements:\n\n```\n{code}\n```", "system_prompt": "You are an expert software engineer focused on clean, efficient code."},
        {"name": "Email Writer", "tags": ["writing", "business"], "prompt": "Write a professional email about: {topic}\nTone: {tone}\nLength: {length}", "system_prompt": "You are a professional business writer."},
        {"name": "Idea Generator", "tags": ["creative"], "prompt": "Generate 10 creative ideas for: {topic}", "system_prompt": "You are a creative brainstorming expert."},
        {"name": "Explainer", "tags": ["education"], "prompt": "Explain {concept} to a {audience} in simple terms.", "system_prompt": "You are a clear, patient teacher."},
        {"name": "Translator", "tags": ["language"], "prompt": "Translate the following to {language}:\n\n{text}", "system_prompt": "You are a professional translator."},
        {"name": "Bug Fixer", "tags": ["code"], "prompt": "Fix the bug in this code and explain what was wrong:\n\n```\n{code}\n```\nError: {error}", "system_prompt": "You are a debugging expert."},
        {"name": "Blog Writer", "tags": ["writing", "marketing"], "prompt": "Write a blog post about {topic}. Include: intro, 3 sections, conclusion.", "system_prompt": "You are a skilled blog writer."},
    ]}
