"""OpenRouter Models — Cloudflare Python Worker.

Fetches models from OpenRouter API every hour (cron), generates a comparison
HTML page, and stores it in KV.  The fetch handler serves the cached HTML.
"""

import json
from html import escape as html_escape
from datetime import datetime, timezone

from js import Response, fetch, Headers


EXPLORER_KV_KEY = "models_html"
FLASHSHIP_KV_KEY = "flashship_html"

FLASHSHIP_TARGETS = [
    {
        "slug": "openai",
        "company": "OpenAI",
        "family_label": "GPT-5.4",
        "variants": [
            {
                "label": "Standard",
                "preferred_ids": ["openai/gpt-5.4"],
                "fallback_prefixes": ["openai/gpt-5.4"],
            },
            {
                "label": "Pro",
                "preferred_ids": ["openai/gpt-5.4-pro"],
                "fallback_prefixes": ["openai/gpt-5.4-pro"],
            },
        ],
    },
    {
        "slug": "anthropic",
        "company": "Anthropic",
        "family_label": "Claude 4.6",
        "variants": [
            {
                "label": "Sonnet",
                "preferred_ids": ["anthropic/claude-sonnet-4.6"],
                "fallback_prefixes": ["anthropic/claude-sonnet-4.6"],
            },
            {
                "label": "Opus",
                "preferred_ids": ["anthropic/claude-opus-4.6"],
                "fallback_prefixes": ["anthropic/claude-opus-4.6"],
            },
        ],
    },
    {
        "slug": "google",
        "company": "Google",
        "family_label": "Gemini 3.1 Pro",
        "variants": [
            {
                "label": "Preview",
                "preferred_ids": ["google/gemini-3.1-pro-preview"],
                "fallback_prefixes": ["google/gemini-3.1-pro-preview"],
            },
        ],
    },
    {
        "slug": "grok",
        "company": "Grok",
        "family_label": "Grok 4.20",
        "variants": [
            {
                "label": "Beta",
                "preferred_ids": ["x-ai/grok-4.20-beta"],
                "fallback_prefixes": ["x-ai/grok-4.20-beta"],
            },
            {
                "label": "Multi-Agent Beta",
                "preferred_ids": ["x-ai/grok-4.20-multi-agent-beta"],
                "fallback_prefixes": ["x-ai/grok-4.20-multi-agent-beta"],
            },
        ],
    },
    {
        "slug": "deepseek",
        "company": "DeepSeek",
        "family_label": "DeepSeek V3.2",
        "variants": [
            {
                "label": "Base",
                "preferred_ids": ["deepseek/deepseek-v3.2"],
                "fallback_prefixes": ["deepseek/deepseek-v3.2"],
            },
            {
                "label": "Exp",
                "preferred_ids": ["deepseek/deepseek-v3.2-exp"],
                "fallback_prefixes": ["deepseek/deepseek-v3.2-exp"],
            },
            {
                "label": "Speciale",
                "preferred_ids": ["deepseek/deepseek-v3.2-speciale"],
                "fallback_prefixes": ["deepseek/deepseek-v3.2-speciale"],
            },
        ],
    },
    {
        "slug": "qwen",
        "company": "Qwen",
        "family_label": "Qwen 3.5",
        "variants": [
            {
                "label": "397B A17B",
                "preferred_ids": ["qwen/qwen3.5-397b-a17b"],
                "fallback_prefixes": ["qwen/qwen3.5-397b-a17b"],
            },
            {
                "label": "122B A10B",
                "preferred_ids": ["qwen/qwen3.5-122b-a10b"],
                "fallback_prefixes": ["qwen/qwen3.5-122b-a10b"],
            },
            {
                "label": "35B A3B",
                "preferred_ids": ["qwen/qwen3.5-35b-a3b"],
                "fallback_prefixes": ["qwen/qwen3.5-35b-a3b"],
            },
            {
                "label": "27B",
                "preferred_ids": ["qwen/qwen3.5-27b"],
                "fallback_prefixes": ["qwen/qwen3.5-27b"],
            },
            {
                "label": "9B",
                "preferred_ids": ["qwen/qwen3.5-9b"],
                "fallback_prefixes": ["qwen/qwen3.5-9b"],
            },
            {
                "label": "Plus",
                "preferred_ids": ["qwen/qwen3.5-plus-02-15"],
                "fallback_prefixes": ["qwen/qwen3.5-plus"],
            },
            {
                "label": "Flash",
                "preferred_ids": ["qwen/qwen3.5-flash-02-23"],
                "fallback_prefixes": ["qwen/qwen3.5-flash"],
            },
        ],
    },
    {
        "slug": "kimi",
        "company": "Kimi",
        "family_label": "Kimi K2.5",
        "variants": [
            {
                "label": "Standard",
                "preferred_ids": ["moonshotai/kimi-k2.5"],
                "fallback_prefixes": ["moonshotai/kimi-k2.5"],
            },
        ],
    },
    {
        "slug": "minimax",
        "company": "MiniMax",
        "family_label": "MiniMax M2.5",
        "variants": [
            {
                "label": "Standard",
                "preferred_ids": ["minimax/minimax-m2.5"],
                "fallback_prefixes": ["minimax/minimax-m2.5"],
            },
        ],
    },
    {
        "slug": "z-ai",
        "company": "Z.ai",
        "family_label": "GLM-5",
        "variants": [
            {
                "label": "Standard",
                "preferred_ids": ["z-ai/glm-5"],
                "fallback_prefixes": ["z-ai/glm-5"],
            },
        ],
    },
]


# ── Fetch handler ──────────────────────────────────────────────────────────

async def on_fetch(request, env):
    url = request.url
    path = url.split("?", 1)[0].rstrip("/")

    if path.endswith("/refresh"):
        await update_models(env)
        return Response.new(
            "Refreshed explorer and flashship pages!",
            headers=Headers.new({"content-type": "text/plain"}.items()),
        )

    kv_key = FLASHSHIP_KV_KEY if path.endswith("/flashship") else EXPLORER_KV_KEY
    html = await env.MODELS_KV.get(kv_key)
    if not html:
        await update_models(env)
        html = await env.MODELS_KV.get(kv_key)

    return Response.new(
        html or "No data yet.",
        headers=Headers.new({"content-type": "text/html;charset=UTF-8"}.items()),
    )


# ── Scheduled handler (cron) ───────────────────────────────────────────────

async def on_scheduled(event, env, ctx):
    await update_models(env)


# ── Core logic ─────────────────────────────────────────────────────────────

async def update_models(env):
    raw_models = await fetch_models()
    models = process_models(raw_models)
    fetch_time = datetime.now(timezone.utc)
    explorer_html = generate_html(models, fetch_time, flashship_url="/flashship")
    flashship_html = generate_flashship_html(models, fetch_time)
    await env.MODELS_KV.put(EXPLORER_KV_KEY, explorer_html)
    await env.MODELS_KV.put(FLASHSHIP_KV_KEY, flashship_html)


async def fetch_models():
    resp = await fetch(
        "https://openrouter.ai/api/v1/models",
        headers=Headers.new({"User-Agent": "OpenRouter-Models-Fetcher/1.0"}.items()),
    )
    data = (await resp.json()).to_py()
    return data.get("data", [])


def process_models(raw_models):
    models = []
    for m in raw_models:
        pricing = m.get("pricing") or {}
        prompt_price = float(pricing.get("prompt") or "0")
        completion_price = float(pricing.get("completion") or "0")
        image_price = float(pricing.get("image") or "0")
        reasoning_price = float(pricing.get("internal_reasoning") or "0")

        arch = m.get("architecture") or {}
        top = m.get("top_provider") or {}

        model_id = m.get("id", "")
        provider = model_id.split("/")[0] if "/" in model_id else "unknown"

        models.append({
            "id": model_id,
            "name": m.get("name", model_id),
            "provider": provider,
            "description": (m.get("description") or "")[:200],
            "context_length": m.get("context_length", 0),
            "max_completion": (top.get("max_completion_tokens") or 0),
            "modality": arch.get("modality", "text->text"),
            "input_modalities": arch.get("input_modalities") or ["text"],
            "output_modalities": arch.get("output_modalities") or ["text"],
            "prompt_price": prompt_price,
            "completion_price": completion_price,
            "image_price": image_price,
            "reasoning_price": reasoning_price,
            "prompt_price_1m": prompt_price * 1_000_000,
            "completion_price_1m": completion_price * 1_000_000,
            "reasoning_price_1m": reasoning_price * 1_000_000,
            "is_free": prompt_price == 0 and completion_price == 0,
            "supported_params": m.get("supported_parameters") or [],
        })

    models.sort(key=lambda x: (x["provider"].lower(), x["name"].lower()))
    return models


# ── HTML generation ────────────────────────────────────────────────────────

def generate_html(models, fetch_time, flashship_url="/flashship"):
    providers = sorted(set(m["provider"] for m in models))
    all_input_mods = sorted(set(mod for m in models for mod in m["input_modalities"]))

    models_json = json.dumps(models, ensure_ascii=False)
    providers_json = json.dumps(providers, ensure_ascii=False)
    input_mods_json = json.dumps(all_input_mods, ensure_ascii=False)

    total_models = len(models)
    total_providers = len(providers)
    free_count = sum(1 for m in models if m["is_free"])
    max_ctx_k = max((m["context_length"] for m in models), default=0) // 1000
    fetch_str = fetch_time.strftime("%Y-%m-%d %H:%M:%S UTC")

    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OpenRouter Models — {fetch_time.strftime('%Y-%m-%d %H:%M')}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@300;400;500&family=Instrument+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

[data-theme="dark"] {{
  --bg-deep: #0a0e17;
  --bg-surface: #111825;
  --bg-card: #1a2235;
  --bg-hover: #212d45;
  --border: #2a3550;
  --border-bright: #3d4f6f;
  --text-primary: #e2e8f0;
  --text-secondary: #8892a8;
  --text-dim: #5a6578;
  --accent-cyan: #22d3ee;
  --accent-cyan-dim: rgba(34,211,238,0.12);
  --accent-amber: #fbbf24;
  --accent-amber-dim: rgba(251,191,36,0.10);
  --accent-green: #34d399;
  --accent-green-dim: rgba(52,211,153,0.10);
  --accent-rose: #fb7185;
  --accent-rose-dim: rgba(251,113,133,0.10);
  --accent-violet: #a78bfa;
  --accent-violet-dim: rgba(167,139,250,0.10);
  --grain-opacity: 0.03;
  --glow-opacity: 0.06;
  --scrollbar-track: #0a0e17;
}}

[data-theme="light"] {{
  --bg-deep: #f4f6f9;
  --bg-surface: #eaecf1;
  --bg-card: #ffffff;
  --bg-hover: #f0f2f7;
  --border: #d5d9e2;
  --border-bright: #bfc5d2;
  --text-primary: #1a1d26;
  --text-secondary: #555d6e;
  --text-dim: #8891a0;
  --accent-cyan: #0891b2;
  --accent-cyan-dim: rgba(8,145,178,0.08);
  --accent-amber: #d97706;
  --accent-amber-dim: rgba(217,119,6,0.07);
  --accent-green: #059669;
  --accent-green-dim: rgba(5,150,105,0.07);
  --accent-rose: #e11d48;
  --accent-rose-dim: rgba(225,29,72,0.06);
  --accent-violet: #7c3aed;
  --accent-violet-dim: rgba(124,58,237,0.07);
  --grain-opacity: 0.015;
  --glow-opacity: 0.03;
  --scrollbar-track: #f4f6f9;
}}

:root {{
  --radius: 8px;
  --font-mono: 'DM Mono', 'Fira Code', monospace;
  --font-sans: 'Instrument Sans', system-ui, sans-serif;
}}

html {{ scroll-behavior: smooth; }}

body {{
  font-family: var(--font-sans);
  background: var(--bg-deep);
  color: var(--text-primary);
  min-height: 100vh;
  line-height: 1.5;
  transition: background 0.3s, color 0.3s;
}}

body::before {{
  content: '';
  position: fixed;
  inset: 0;
  z-index: 0;
  opacity: var(--grain-opacity);
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  pointer-events: none;
}}

body::after {{
  content: '';
  position: fixed;
  top: -200px;
  right: -100px;
  width: 600px;
  height: 600px;
  background: radial-gradient(circle, rgba(34,211,238,var(--glow-opacity)) 0%, transparent 70%);
  pointer-events: none;
  z-index: 0;
}}

.container {{
  position: relative;
  z-index: 1;
  max-width: 1600px;
  margin: 0 auto;
  padding: 32px 24px;
}}

.header {{
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 32px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--border);
  animation: fadeDown 0.6s ease-out;
}}

.header-left h1 {{
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.5px;
  background: linear-gradient(135deg, var(--text-primary) 0%, var(--accent-cyan) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}}

.header-right {{
  display: flex;
  align-items: flex-end;
  gap: 16px;
}}

.header .meta {{
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-dim);
  text-align: right;
  line-height: 1.8;
}}

.header .meta span {{
  color: var(--accent-cyan);
}}

.toggle-group {{
  display: flex;
  gap: 8px;
}}

.toggle-pill {{
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  border-radius: 20px;
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--text-dim);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.25s;
  user-select: none;
}}

.toggle-pill:hover {{
  border-color: var(--accent-cyan);
  color: var(--text-secondary);
}}

.flashship-link {{
  border-color: var(--accent-cyan);
  background: linear-gradient(135deg, var(--accent-cyan) 0%, #67e8f9 100%);
  color: #06202a;
  box-shadow: 0 10px 24px rgba(34, 211, 238, 0.22);
}}

.flashship-link:hover {{
  color: #04151c;
  transform: translateY(-1px);
}}

[data-theme="light"] .flashship-link {{
  color: #ffffff;
}}

.toggle-pill svg {{
  width: 14px;
  height: 14px;
  transition: transform 0.3s;
}}

[data-theme="light"] .toggle-pill.theme-toggle svg {{ transform: rotate(180deg); }}

.stats-bar {{
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
  flex-wrap: wrap;
  animation: fadeDown 0.6s ease-out 0.1s both;
}}

.stat-card {{
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 20px;
  flex: 1;
  min-width: 160px;
  transition: background 0.3s, border-color 0.3s;
}}

.stat-card .label {{
  font-size: 11px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 1.2px;
  color: var(--text-dim);
  margin-bottom: 4px;
}}

.stat-card .value {{
  font-family: var(--font-mono);
  font-size: 22px;
  font-weight: 500;
  color: var(--accent-cyan);
}}

.stat-card .value.amber {{ color: var(--accent-amber); }}
.stat-card .value.green {{ color: var(--accent-green); }}
.stat-card .value.rose {{ color: var(--accent-rose); }}

.controls {{
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  flex-wrap: wrap;
  align-items: center;
  animation: fadeDown 0.6s ease-out 0.2s both;
}}

.search-box {{
  flex: 1;
  min-width: 280px;
  position: relative;
}}

.search-box svg {{
  position: absolute;
  left: 14px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-dim);
  width: 16px;
  height: 16px;
}}

.search-box input {{
  width: 100%;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 14px 10px 40px;
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--text-primary);
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s, background 0.3s;
}}

.search-box input::placeholder {{ color: var(--text-dim); }}
.search-box input:focus {{
  border-color: var(--accent-cyan);
  box-shadow: 0 0 0 3px var(--accent-cyan-dim);
}}

select, .btn {{
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 14px;
  font-family: var(--font-sans);
  font-size: 13px;
  color: var(--text-primary);
  cursor: pointer;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s, background 0.3s, color 0.3s;
  -webkit-appearance: none;
}}

select:focus, .btn:focus {{
  border-color: var(--accent-cyan);
  box-shadow: 0 0 0 3px var(--accent-cyan-dim);
}}

.btn {{
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}}

.btn:hover {{ background: var(--bg-hover); }}

.btn.active {{
  background: var(--accent-cyan-dim);
  border-color: var(--accent-cyan);
  color: var(--accent-cyan);
}}

.filter-group {{
  display: flex;
  align-items: center;
  gap: 8px;
}}

.filter-group label {{
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--text-dim);
  white-space: nowrap;
}}

.count-badge {{
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-secondary);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 6px 14px;
  white-space: nowrap;
  transition: background 0.3s, border-color 0.3s;
}}

.table-wrap {{
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  animation: fadeUp 0.6s ease-out 0.3s both;
  transition: border-color 0.3s;
}}

.table-scroll {{
  overflow-x: auto;
}}

table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}}

thead {{
  position: sticky;
  top: 0;
  z-index: 10;
}}

thead th {{
  background: var(--bg-card);
  border-bottom: 2px solid var(--border-bright);
  padding: 12px 16px;
  text-align: left;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--text-dim);
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
  transition: color 0.2s, background 0.3s;
}}

thead th:hover {{ color: var(--accent-cyan); }}

thead th.sorted {{
  color: var(--accent-cyan);
}}

thead th .sort-arrow {{
  display: inline-block;
  margin-left: 4px;
  opacity: 0.4;
  font-size: 10px;
}}

thead th.sorted .sort-arrow {{ opacity: 1; }}

tbody tr {{
  border-bottom: 1px solid var(--border);
  transition: background 0.15s;
}}

tbody tr:hover {{
  background: var(--bg-hover);
}}

tbody td {{
  padding: 10px 16px;
  white-space: nowrap;
  vertical-align: middle;
}}

.cell-model {{
  max-width: 320px;
  white-space: normal;
}}

.model-name {{
  font-weight: 600;
  font-size: 13px;
  color: var(--text-primary);
}}

.model-id {{
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-dim);
  margin-top: 2px;
  word-break: break-all;
}}

.cell-provider {{
  font-weight: 600;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}}

.cell-price {{
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 400;
}}

.price-free {{ color: var(--accent-green); font-weight: 500; }}
.price-low {{ color: var(--accent-green); }}
.price-mid {{ color: var(--accent-amber); }}
.price-high {{ color: var(--accent-rose); }}

.cell-ctx {{
  font-family: var(--font-mono);
  font-size: 13px;
}}

.modality-badge {{
  display: inline-block;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 2px 8px;
  border-radius: 4px;
  margin: 1px 2px;
}}

.mod-text {{ background: var(--accent-cyan-dim); color: var(--accent-cyan); }}
.mod-image {{ background: var(--accent-violet-dim); color: var(--accent-violet); }}
.mod-audio {{ background: var(--accent-amber-dim); color: var(--accent-amber); }}
.mod-video {{ background: var(--accent-rose-dim); color: var(--accent-rose); }}
.mod-file {{ background: var(--accent-green-dim); color: var(--accent-green); }}

.param-badges {{
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
  max-width: 240px;
}}

.param-badge {{
  font-size: 9px;
  font-family: var(--font-mono);
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  color: var(--text-dim);
}}

.empty-state {{
  text-align: center;
  padding: 60px 20px;
  color: var(--text-dim);
  font-size: 15px;
}}

@keyframes fadeDown {{
  from {{ opacity: 0; transform: translateY(-12px); }}
  to {{ opacity: 1; transform: translateY(0); }}
}}

@keyframes fadeUp {{
  from {{ opacity: 0; transform: translateY(12px); }}
  to {{ opacity: 1; transform: translateY(0); }}
}}

@media (max-width: 768px) {{
  .header {{ flex-direction: column; align-items: flex-start; gap: 12px; }}
  .header-right {{ flex-direction: column; align-items: flex-start; }}
  .header .meta {{ text-align: left; }}
  .stats-bar {{ gap: 8px; }}
  .stat-card {{ min-width: 120px; padding: 10px 14px; }}
  .stat-card .value {{ font-size: 18px; }}
  .controls {{ gap: 8px; }}
}}

::-webkit-scrollbar {{ width: 6px; height: 6px; }}
::-webkit-scrollbar-track {{ background: var(--scrollbar-track); }}
::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}
::-webkit-scrollbar-thumb:hover {{ background: var(--border-bright); }}

.cell-check {{
  width: 40px;
  text-align: center;
}}

.cell-check input[type="checkbox"] {{
  appearance: none;
  -webkit-appearance: none;
  width: 16px;
  height: 16px;
  border: 2px solid var(--border-bright);
  border-radius: 4px;
  background: var(--bg-surface);
  cursor: pointer;
  position: relative;
  transition: all 0.15s;
  vertical-align: middle;
}}

.cell-check input[type="checkbox"]:checked {{
  background: var(--accent-cyan);
  border-color: var(--accent-cyan);
}}

.cell-check input[type="checkbox"]:checked::after {{
  content: '';
  position: absolute;
  left: 3px;
  top: 0px;
  width: 5px;
  height: 9px;
  border: solid var(--bg-deep);
  border-width: 0 2px 2px 0;
  transform: rotate(45deg);
}}

tbody tr.row-selected {{
  background: var(--accent-cyan-dim);
}}

tbody tr.row-selected:hover {{
  background: var(--accent-cyan-dim);
}}

.compare-bar {{
  position: fixed;
  bottom: -80px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 100;
  background: var(--bg-card);
  border: 1px solid var(--accent-cyan);
  border-radius: 16px;
  padding: 12px 24px;
  display: flex;
  align-items: center;
  gap: 16px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.4);
  backdrop-filter: blur(12px);
  transition: bottom 0.35s cubic-bezier(0.4,0,0.2,1), background 0.3s, border-color 0.3s;
}}

.compare-bar.visible {{
  bottom: 28px;
}}

.compare-bar .selected-chips {{
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  max-width: 600px;
}}

.compare-chip {{
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 8px;
  background: var(--accent-cyan-dim);
  color: var(--accent-cyan);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}}

.compare-chip .chip-remove {{
  cursor: pointer;
  opacity: 0.6;
  font-size: 14px;
  line-height: 1;
  margin-left: 2px;
}}

.compare-chip .chip-remove:hover {{ opacity: 1; }}

.compare-bar .btn-compare {{
  background: var(--accent-cyan);
  color: var(--bg-deep);
  border: none;
  border-radius: 10px;
  padding: 8px 20px;
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
  transition: opacity 0.2s;
}}

.compare-bar .btn-compare:hover {{ opacity: 0.85; }}

.compare-bar .btn-clear {{
  background: none;
  border: none;
  color: var(--text-dim);
  font-size: 12px;
  cursor: pointer;
  padding: 4px;
  transition: color 0.2s;
}}

.compare-bar .btn-clear:hover {{ color: var(--accent-rose); }}

.modal-overlay {{
  position: fixed;
  inset: 0;
  z-index: 200;
  background: rgba(0,0,0,0.6);
  backdrop-filter: blur(4px);
  display: none;
  align-items: center;
  justify-content: center;
  padding: 24px;
  animation: modalFadeIn 0.25s ease-out;
}}

.modal-overlay.open {{
  display: flex;
}}

.modal {{
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  width: 100%;
  max-width: 1500px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 24px 64px rgba(0,0,0,0.5);
  animation: modalSlideUp 0.3s ease-out;
}}

.modal-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px;
  border-bottom: 1px solid var(--border);
}}

.modal-header h2 {{
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
}}

.modal-close {{
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--text-dim);
  font-size: 18px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}}

.modal-close:hover {{
  border-color: var(--accent-rose);
  color: var(--accent-rose);
}}

.modal-body {{
  overflow: auto;
  padding: 24px;
  flex: 1;
}}

.cmp-best {{
  background: var(--accent-green-dim);
  border-radius: 4px;
  padding: 2px 6px;
}}

.modal-body table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}}

.modal-body thead th {{
  background: var(--bg-card);
  border-bottom: 2px solid var(--border-bright);
  padding: 12px 16px;
  text-align: left;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--text-dim);
  white-space: nowrap;
}}

.modal-body tbody tr {{
  border-bottom: 1px solid var(--border);
  transition: background 0.15s;
}}

.modal-body tbody tr:hover {{
  background: var(--bg-hover);
}}

.modal-body tbody td {{
  padding: 10px 16px;
  white-space: nowrap;
  vertical-align: middle;
}}

@keyframes modalFadeIn {{
  from {{ opacity: 0; }}
  to {{ opacity: 1; }}
}}

@keyframes modalSlideUp {{
  from {{ opacity: 0; transform: translateY(20px); }}
  to {{ opacity: 1; transform: translateY(0); }}
}}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="header-left">
      <h1 data-i18n="title">OpenRouter Model Explorer</h1>
    </div>
    <div class="header-right">
      <div class="toggle-group">
        <a class="toggle-pill flashship-link" href="{html_escape(flashship_url)}">Flashship ↗</a>
        <button class="toggle-pill theme-toggle" id="themeToggle" title="Toggle light/dark">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 3v2.25m6.364.386l-1.591 1.591M21 12h-2.25m-.386 6.364l-1.591-1.591M12 18.75V21m-4.773-4.227l-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z"/></svg>
          <span data-i18n="theme">Theme</span>
        </button>
        <button class="toggle-pill" id="langToggle">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M10.5 21l5.25-11.25L21 21m-9-3h7.5M3 5.621a48.474 48.474 0 016-.371m0 0c1.12 0 2.233.038 3.334.114M9 5.25V3m3.334 2.364C11.176 10.658 7.69 15.08 3 17.502m9.334-12.138c.896.061 1.785.147 2.666.257m-4.589 8.495a18.023 18.023 0 01-3.827-5.802"/></svg>
          <span id="langLabel">EN / CN</span>
        </button>
      </div>
      <div class="meta">
        <span data-i18n="fetched">fetched</span> <span>{fetch_str}</span><br>
        <span id="visibleCount"></span> / <span>{total_models}</span> <span data-i18n="models_suffix">models</span>
      </div>
    </div>
  </div>

  <div class="stats-bar">
    <div class="stat-card">
      <div class="label" data-i18n="stat_total">Total Models</div>
      <div class="value">{total_models}</div>
    </div>
    <div class="stat-card">
      <div class="label" data-i18n="stat_providers">Providers</div>
      <div class="value amber">{total_providers}</div>
    </div>
    <div class="stat-card">
      <div class="label" data-i18n="stat_free">Free Models</div>
      <div class="value green">{free_count}</div>
    </div>
    <div class="stat-card">
      <div class="label" data-i18n="stat_maxctx">Max Context</div>
      <div class="value rose">{max_ctx_k}K</div>
    </div>
  </div>

  <div class="controls">
    <div class="search-box">
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"/>
      </svg>
      <input type="text" id="searchInput" data-i18n-placeholder="search_placeholder" placeholder="Search models, providers, IDs...">
    </div>
    <div class="filter-group">
      <label data-i18n="filter_provider">Provider</label>
      <select id="providerFilter">
        <option value="" data-i18n="all">All</option>
      </select>
    </div>
    <div class="filter-group">
      <label data-i18n="filter_input">Input</label>
      <select id="inputModFilter">
        <option value="" data-i18n="all">All</option>
      </select>
    </div>
    <div class="filter-group">
      <label data-i18n="filter_pricing">Pricing</label>
      <select id="pricingFilter">
        <option value="" data-i18n="all">All</option>
        <option value="free" data-i18n="free">Free</option>
        <option value="paid" data-i18n="paid">Paid</option>
      </select>
    </div>
    <button class="btn" id="toggleParams">
      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 010 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 010-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28z"/><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
      <span data-i18n="params_btn">Params</span>
    </button>
    <span class="count-badge" id="countBadge"></span>
  </div>

  <div class="table-wrap">
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th class="cell-check"><input type="checkbox" id="selectAll" title="Select all"></th>
            <th data-sort="name"><span data-i18n="col_model">Model</span> <span class="sort-arrow">&uarr;</span></th>
            <th data-sort="provider"><span data-i18n="col_provider">Provider</span> <span class="sort-arrow">&uarr;</span></th>
            <th data-sort="prompt_price_1m"><span data-i18n="col_input_price">Input $/1M</span> <span class="sort-arrow">&uarr;</span></th>
            <th data-sort="completion_price_1m"><span data-i18n="col_output_price">Output $/1M</span> <span class="sort-arrow">&uarr;</span></th>
            <th data-sort="reasoning_price_1m"><span data-i18n="col_reasoning_price">Reasoning $/1M</span> <span class="sort-arrow">&uarr;</span></th>
            <th data-sort="context_length"><span data-i18n="col_context">Context</span> <span class="sort-arrow">&uarr;</span></th>
            <th data-sort="max_completion"><span data-i18n="col_max_output">Max Output</span> <span class="sort-arrow">&uarr;</span></th>
            <th data-i18n="col_input_mod">Input Modalities</th>
            <th data-i18n="col_output_mod">Output Modalities</th>
            <th class="params-col" style="display:none;" data-i18n="col_params">Supported Params</th>
          </tr>
        </thead>
        <tbody id="modelTableBody">
        </tbody>
      </table>
    </div>
    <div class="empty-state" id="emptyState" style="display:none;" data-i18n="empty_state">
      No models match your filters.
    </div>
  </div>
</div>

<div class="compare-bar" id="compareBar">
  <div class="selected-chips" id="selectedChips"></div>
  <button class="btn-compare" id="btnCompare" data-i18n="compare_btn">Compare</button>
  <button class="btn-clear" id="btnClearSelection" data-i18n="clear_selection">Clear</button>
</div>

<div class="modal-overlay" id="modalOverlay">
  <div class="modal">
    <div class="modal-header">
      <h2 data-i18n="compare_title">Model Comparison</h2>
      <button class="modal-close" id="modalClose">&times;</button>
    </div>
    <div class="modal-body" id="modalBody"></div>
  </div>
</div>

<footer style="text-align:center;padding:32px 0 24px;color:var(--text-dim);font-size:13px;">
  <a href="https://github.com/xiaojay/openrouter-model-explorer" target="_blank" rel="noopener"
     style="color:var(--text-dim);text-decoration:none;transition:color .2s;"
     onmouseover="this.style.color='var(--accent)'" onmouseout="this.style.color='var(--text-dim)'">
    &#9733; GitHub: openrouter-model-explorer
  </a>
</footer>

<script>
const ALL_MODELS = {models_json};
const PROVIDERS = {providers_json};
const INPUT_MODS = {input_mods_json};

const I18N = {{
  en: {{
    title: 'OpenRouter Model Explorer',
    theme: 'Theme',
    fetched: 'fetched',
    models_suffix: 'models',
    stat_total: 'Total Models',
    stat_providers: 'Providers',
    stat_free: 'Free Models',
    stat_maxctx: 'Max Context',
    search_placeholder: 'Search models, providers, IDs...',
    filter_provider: 'Provider',
    filter_input: 'Input',
    filter_pricing: 'Pricing',
    all: 'All',
    free: 'Free',
    paid: 'Paid',
    params_btn: 'Params',
    col_model: 'Model',
    col_provider: 'Provider',
    col_input_price: 'Input $/1M',
    col_output_price: 'Output $/1M',
    col_reasoning_price: 'Reasoning $/1M',
    col_context: 'Context',
    col_max_output: 'Max Output',
    col_input_mod: 'Input Modalities',
    col_output_mod: 'Output Modalities',
    col_params: 'Supported Params',
    empty_state: 'No models match your filters.',
    shown_suffix: 'shown',
    price_free: 'FREE',
    compare_btn: 'Compare',
    clear_selection: 'Clear',
    compare_title: 'Model Comparison',
    selected_suffix: 'selected',
  }},
  zh: {{
    title: 'OpenRouter \u6a21\u578b\u6d4f\u89c8\u5668',
    theme: '\u4e3b\u9898',
    fetched: '\u83b7\u53d6\u4e8e',
    models_suffix: '\u4e2a\u6a21\u578b',
    stat_total: '\u6a21\u578b\u603b\u6570',
    stat_providers: '\u670d\u52a1\u5546',
    stat_free: '\u514d\u8d39\u6a21\u578b',
    stat_maxctx: '\u6700\u5927\u4e0a\u4e0b\u6587',
    search_placeholder: '\u641c\u7d22\u6a21\u578b\u540d\u79f0\u3001\u670d\u52a1\u5546\u3001ID...',
    filter_provider: '\u670d\u52a1\u5546',
    filter_input: '\u8f93\u5165',
    filter_pricing: '\u4ef7\u683c',
    all: '\u5168\u90e8',
    free: '\u514d\u8d39',
    paid: '\u4ed8\u8d39',
    params_btn: '\u53c2\u6570',
    col_model: '\u6a21\u578b',
    col_provider: '\u670d\u52a1\u5546',
    col_input_price: '\u8f93\u5165 $/1M',
    col_output_price: '\u8f93\u51fa $/1M',
    col_reasoning_price: '\u63a8\u7406 $/1M',
    col_context: '\u4e0a\u4e0b\u6587',
    col_max_output: '\u6700\u5927\u8f93\u51fa',
    col_input_mod: '\u8f93\u5165\u6a21\u6001',
    col_output_mod: '\u8f93\u51fa\u6a21\u6001',
    col_params: '\u652f\u6301\u53c2\u6570',
    empty_state: '\u6ca1\u6709\u5339\u914d\u7684\u6a21\u578b\u3002',
    shown_suffix: '\u4e2a\u663e\u793a',
    price_free: '\u514d\u8d39',
    compare_btn: '\u5bf9\u6bd4',
    clear_selection: '\u6e05\u9664',
    compare_title: '\u6a21\u578b\u5bf9\u6bd4',
    selected_suffix: '\u4e2a\u5df2\u9009',
  }}
}};

let currentLang = 'en';
let sortKey = 'provider';
let sortAsc = true;
let showParams = false;

function t(key) {{
  return I18N[currentLang][key] || I18N['en'][key] || key;
}}

function applyI18n() {{
  document.querySelectorAll('[data-i18n]').forEach(el => {{
    const key = el.getAttribute('data-i18n');
    el.textContent = t(key);
  }});
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {{
    const key = el.getAttribute('data-i18n-placeholder');
    el.placeholder = t(key);
  }});
  document.getElementById('langLabel').textContent = currentLang === 'en' ? 'EN / CN' : 'CN / EN';
  document.documentElement.lang = currentLang === 'en' ? 'en' : 'zh-CN';
}}

const providerSel = document.getElementById('providerFilter');
PROVIDERS.forEach(p => {{
  const opt = document.createElement('option');
  opt.value = p;
  opt.textContent = p;
  providerSel.appendChild(opt);
}});

const inputModSel = document.getElementById('inputModFilter');
INPUT_MODS.forEach(m => {{
  const opt = document.createElement('option');
  opt.value = m;
  opt.textContent = m;
  inputModSel.appendChild(opt);
}});

function formatPrice(val) {{
  if (val === 0) return '<span class="price-free">' + t('price_free') + '</span>';
  if (val < 1) return '<span class="price-low">$' + val.toFixed(4) + '</span>';
  if (val < 10) return '<span class="price-mid">$' + val.toFixed(3) + '</span>';
  return '<span class="price-high">$' + val.toFixed(2) + '</span>';
}}

function formatCtx(val) {{
  if (!val) return '<span style="color:var(--text-dim)">\u2014</span>';
  if (val >= 1000000) return (val / 1000000).toFixed(1) + 'M';
  if (val >= 1000) return Math.round(val / 1000) + 'K';
  return val.toString();
}}

function modBadge(mod) {{
  const cls = mod === 'text' ? 'mod-text'
    : mod === 'image' ? 'mod-image'
    : mod === 'audio' ? 'mod-audio'
    : mod === 'video' ? 'mod-video'
    : 'mod-file';
  return '<span class="modality-badge ' + cls + '">' + mod + '</span>';
}}

function renderTable() {{
  const search = document.getElementById('searchInput').value.toLowerCase();
  const provFilter = providerSel.value;
  const inputModF = inputModSel.value;
  const pricingF = document.getElementById('pricingFilter').value;

  let filtered = ALL_MODELS.filter(m => {{
    if (search && !m.name.toLowerCase().includes(search) &&
        !m.id.toLowerCase().includes(search) &&
        !m.provider.toLowerCase().includes(search)) return false;
    if (provFilter && m.provider !== provFilter) return false;
    if (inputModF && !m.input_modalities.includes(inputModF)) return false;
    if (pricingF === 'free' && !m.is_free) return false;
    if (pricingF === 'paid' && m.is_free) return false;
    return true;
  }});

  filtered.sort((a, b) => {{
    let va = a[sortKey], vb = b[sortKey];
    if (typeof va === 'string') va = va.toLowerCase();
    if (typeof vb === 'string') vb = vb.toLowerCase();
    if (va < vb) return sortAsc ? -1 : 1;
    if (va > vb) return sortAsc ? 1 : -1;
    return 0;
  }});

  const tbody = document.getElementById('modelTableBody');
  const empty = document.getElementById('emptyState');
  const paramsDisplay = showParams ? '' : 'display:none;';

  if (filtered.length === 0) {{
    tbody.innerHTML = '';
    empty.style.display = 'block';
  }} else {{
    empty.style.display = 'none';
    tbody.innerHTML = filtered.map(m => `
      <tr class="${{selectedIds.has(m.id) ? 'row-selected' : ''}}" data-model-id="${{m.id}}">
        <td class="cell-check"><input type="checkbox" ${{selectedIds.has(m.id) ? 'checked' : ''}} data-id="${{m.id}}"></td>
        <td class="cell-model">
          <div class="model-name">${{m.name}}</div>
          <div class="model-id">${{m.id}}</div>
        </td>
        <td class="cell-provider">${{m.provider}}</td>
        <td class="cell-price">${{formatPrice(m.prompt_price_1m)}}</td>
        <td class="cell-price">${{formatPrice(m.completion_price_1m)}}</td>
        <td class="cell-price">${{formatPrice(m.reasoning_price_1m)}}</td>
        <td class="cell-ctx">${{formatCtx(m.context_length)}}</td>
        <td class="cell-ctx">${{formatCtx(m.max_completion)}}</td>
        <td>${{m.input_modalities.map(modBadge).join('')}}</td>
        <td>${{m.output_modalities.map(modBadge).join('')}}</td>
        <td class="params-col" style="${{paramsDisplay}}">
          <div class="param-badges">${{m.supported_params.map(p => '<span class="param-badge">' + p + '</span>').join('')}}</div>
        </td>
      </tr>
    `).join('');
  }}

  document.getElementById('countBadge').textContent = filtered.length + ' ' + t('shown_suffix');
  document.getElementById('visibleCount').textContent = filtered.length;

  document.querySelectorAll('thead th').forEach(th => {{
    th.classList.toggle('sorted', th.dataset.sort === sortKey);
    const arrow = th.querySelector('.sort-arrow');
    if (arrow) arrow.textContent = (th.dataset.sort === sortKey)
      ? (sortAsc ? '\u2191' : '\u2193') : '\u2191';
  }});
}}

document.getElementById('themeToggle').addEventListener('click', () => {{
  const html = document.documentElement;
  const next = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  html.setAttribute('data-theme', next);
  localStorage.setItem('or-theme', next);
}});

const savedTheme = localStorage.getItem('or-theme');
if (savedTheme) document.documentElement.setAttribute('data-theme', savedTheme);

document.getElementById('langToggle').addEventListener('click', () => {{
  currentLang = currentLang === 'en' ? 'zh' : 'en';
  localStorage.setItem('or-lang', currentLang);
  applyI18n();
  renderTable();
}});

const savedLang = localStorage.getItem('or-lang');
if (savedLang) currentLang = savedLang;

document.getElementById('searchInput').addEventListener('input', renderTable);
providerSel.addEventListener('change', renderTable);
inputModSel.addEventListener('change', renderTable);
document.getElementById('pricingFilter').addEventListener('change', renderTable);

document.getElementById('toggleParams').addEventListener('click', () => {{
  showParams = !showParams;
  document.getElementById('toggleParams').classList.toggle('active', showParams);
  document.querySelectorAll('.params-col').forEach(el => {{
    el.style.display = showParams ? '' : 'none';
  }});
  renderTable();
}});

document.querySelectorAll('thead th[data-sort]').forEach(th => {{
  th.addEventListener('click', () => {{
    const key = th.dataset.sort;
    if (sortKey === key) {{ sortAsc = !sortAsc; }}
    else {{ sortKey = key; sortAsc = true; }}
    renderTable();
  }});
}});

const selectedIds = new Set();
const modelsById = {{}};
ALL_MODELS.forEach(m => modelsById[m.id] = m);

function updateCompareBar() {{
  const bar = document.getElementById('compareBar');
  const chips = document.getElementById('selectedChips');
  if (selectedIds.size === 0) {{
    bar.classList.remove('visible');
    return;
  }}
  bar.classList.add('visible');
  chips.innerHTML = Array.from(selectedIds).map(id => {{
    const m = modelsById[id];
    const name = m ? m.name : id;
    return '<span class="compare-chip">' + name + '<span class="chip-remove" data-remove-id="' + id + '">&times;</span></span>';
  }}).join('');
  const selAll = document.getElementById('selectAll');
  const visibleCheckboxes = document.querySelectorAll('#modelTableBody input[type="checkbox"]');
  const allChecked = visibleCheckboxes.length > 0 && Array.from(visibleCheckboxes).every(cb => cb.checked);
  selAll.checked = allChecked;
}}

document.getElementById('modelTableBody').addEventListener('change', (e) => {{
  if (e.target.type === 'checkbox') {{
    const id = e.target.dataset.id;
    if (e.target.checked) {{
      selectedIds.add(id);
      e.target.closest('tr').classList.add('row-selected');
    }} else {{
      selectedIds.delete(id);
      e.target.closest('tr').classList.remove('row-selected');
    }}
    updateCompareBar();
  }}
}});

document.getElementById('selectAll').addEventListener('change', (e) => {{
  const cbs = document.querySelectorAll('#modelTableBody input[type="checkbox"]');
  cbs.forEach(cb => {{
    if (e.target.checked) {{
      selectedIds.add(cb.dataset.id);
      cb.checked = true;
      cb.closest('tr').classList.add('row-selected');
    }} else {{
      selectedIds.delete(cb.dataset.id);
      cb.checked = false;
      cb.closest('tr').classList.remove('row-selected');
    }}
  }});
  updateCompareBar();
}});

document.getElementById('selectedChips').addEventListener('click', (e) => {{
  const removeId = e.target.dataset.removeId;
  if (removeId) {{
    selectedIds.delete(removeId);
    const cb = document.querySelector('input[data-id="' + removeId + '"]');
    if (cb) {{ cb.checked = false; cb.closest('tr').classList.remove('row-selected'); }}
    updateCompareBar();
  }}
}});

document.getElementById('btnClearSelection').addEventListener('click', () => {{
  selectedIds.clear();
  document.querySelectorAll('#modelTableBody input[type="checkbox"]').forEach(cb => {{
    cb.checked = false;
    cb.closest('tr').classList.remove('row-selected');
  }});
  document.getElementById('selectAll').checked = false;
  updateCompareBar();
}});

document.getElementById('btnCompare').addEventListener('click', () => {{
  if (selectedIds.size < 2) return;
  const models = Array.from(selectedIds).map(id => modelsById[id]).filter(Boolean);
  openCompareModal(models);
}});

let cmpSortKey = null;
let cmpSortAsc = true;
let cmpModels = [];

function openCompareModal(models) {{
  cmpModels = models.slice();
  cmpSortKey = null;
  cmpSortAsc = true;
  renderCompareTable();
  document.getElementById('modalOverlay').classList.add('open');
}}

function renderCompareTable() {{
  const body = document.getElementById('modalBody');
  const models = cmpModels.slice();

  if (cmpSortKey) {{
    models.sort((a, b) => {{
      let va = a[cmpSortKey], vb = b[cmpSortKey];
      if (typeof va === 'string') va = va.toLowerCase();
      if (typeof vb === 'string') vb = vb.toLowerCase();
      if (va < vb) return cmpSortAsc ? -1 : 1;
      if (va > vb) return cmpSortAsc ? 1 : -1;
      return 0;
    }});
  }}

  const bestCtx = Math.max(...models.map(m => m.context_length));
  const bestMaxOut = Math.max(...models.map(m => m.max_completion));
  const paidInputs = models.filter(m => m.prompt_price_1m > 0).map(m => m.prompt_price_1m);
  const paidOutputs = models.filter(m => m.completion_price_1m > 0).map(m => m.completion_price_1m);
  const minInput = paidInputs.length ? Math.min(...paidInputs) : 0;
  const minOutput = paidOutputs.length ? Math.min(...paidOutputs) : 0;

  function bestPrice(val, min) {{
    if (val === 0) return true;
    return val === min;
  }}

  const cols = [
    {{ key: 'name', label: 'col_model' }},
    {{ key: 'provider', label: 'col_provider' }},
    {{ key: 'prompt_price_1m', label: 'col_input_price' }},
    {{ key: 'completion_price_1m', label: 'col_output_price' }},
    {{ key: 'reasoning_price_1m', label: 'col_reasoning_price' }},
    {{ key: 'context_length', label: 'col_context' }},
    {{ key: 'max_completion', label: 'col_max_output' }},
    {{ key: null, label: 'col_input_mod' }},
    {{ key: null, label: 'col_output_mod' }},
  ];

  let html = '<div class="table-scroll"><table><thead><tr>';
  cols.forEach(c => {{
    const isSorted = c.key && cmpSortKey === c.key;
    const arrow = isSorted ? (cmpSortAsc ? '\u2191' : '\u2193') : '\u2191';
    const cls = isSorted ? ' class="sorted"' : '';
    const sortAttr = c.key ? ' data-cmp-sort="' + c.key + '" style="cursor:pointer"' : '';
    html += '<th' + cls + sortAttr + '>' + t(c.label) + ' ' + (c.key ? '<span class="sort-arrow">' + arrow + '</span>' : '') + '</th>';
  }});
  html += '</tr></thead><tbody>';

  models.forEach(m => {{
    html += '<tr>' +
      '<td class="cell-model"><div class="model-name">' + m.name + '</div><div class="model-id">' + m.id + '</div></td>' +
      '<td class="cell-provider">' + m.provider + '</td>' +
      '<td class="cell-price">' + (bestPrice(m.prompt_price_1m, minInput) ? '<span class="cmp-best">' : '') + formatPrice(m.prompt_price_1m) + (bestPrice(m.prompt_price_1m, minInput) ? '</span>' : '') + '</td>' +
      '<td class="cell-price">' + (bestPrice(m.completion_price_1m, minOutput) ? '<span class="cmp-best">' : '') + formatPrice(m.completion_price_1m) + (bestPrice(m.completion_price_1m, minOutput) ? '</span>' : '') + '</td>' +
      '<td class="cell-price">' + formatPrice(m.reasoning_price_1m) + '</td>' +
      '<td class="cell-ctx">' + (m.context_length === bestCtx ? '<span class="cmp-best">' : '') + formatCtx(m.context_length) + (m.context_length === bestCtx ? '</span>' : '') + '</td>' +
      '<td class="cell-ctx">' + (m.max_completion === bestMaxOut ? '<span class="cmp-best">' : '') + formatCtx(m.max_completion) + (m.max_completion === bestMaxOut ? '</span>' : '') + '</td>' +
      '<td>' + m.input_modalities.map(modBadge).join('') + '</td>' +
      '<td>' + m.output_modalities.map(modBadge).join('') + '</td>' +
    '</tr>';
  }});

  html += '</tbody></table></div>';
  body.innerHTML = html;

  body.querySelectorAll('th[data-cmp-sort]').forEach(th => {{
    th.addEventListener('click', () => {{
      const key = th.dataset.cmpSort;
      if (cmpSortKey === key) {{ cmpSortAsc = !cmpSortAsc; }}
      else {{ cmpSortKey = key; cmpSortAsc = true; }}
      renderCompareTable();
    }});
  }});
}}

document.getElementById('modalClose').addEventListener('click', () => {{
  document.getElementById('modalOverlay').classList.remove('open');
}});

document.getElementById('modalOverlay').addEventListener('click', (e) => {{
  if (e.target === e.currentTarget) {{
    e.currentTarget.classList.remove('open');
  }}
}});

document.addEventListener('keydown', (e) => {{
  if (e.key === 'Escape') {{
    document.getElementById('modalOverlay').classList.remove('open');
  }}
}});

applyI18n();
renderTable();
</script>
</body>
</html>"""
    return html


def select_flashship_variant(models, variant):
    by_id = {m["id"]: m for m in models}

    for preferred_id in variant["preferred_ids"]:
        chosen = by_id.get(preferred_id)
        if chosen and not chosen["id"].endswith(":free"):
            return chosen

    candidates = [
        m for m in models
        if any(m["id"].startswith(prefix) for prefix in variant["fallback_prefixes"])
        and not m["id"].endswith(":free")
    ]
    candidates.sort(key=lambda m: (m["id"], m["context_length"], m["max_completion"]), reverse=True)
    return candidates[0] if candidates else None


def pick_flashship_models(models):
    selected = []

    for target in FLASHSHIP_TARGETS:
        for variant in target["variants"]:
            chosen = select_flashship_variant(models, variant)
            row = {
                "slug": target["slug"],
                "company": target["company"],
                "family_label": target["family_label"],
                "variant_label": variant["label"],
                "available": bool(chosen),
            }
            if chosen:
                row.update(chosen)
            selected.append(row)

    return selected


def format_context(value):
    if not value:
        return "—"
    if value >= 1_000_000:
        formatted = f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{formatted}M"
    if value >= 1000:
        formatted = f"{value / 1000:.0f}" if value % 1000 == 0 else f"{value / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{formatted}K"
    return str(value)


def format_price_html(value):
    if value == 0:
        return '<span class="price-free">FREE</span>'
    if value < 1:
        return f'<span class="price-low">${value:.4f}</span>'
    if value < 10:
        return f'<span class="price-mid">${value:.3f}</span>'
    return f'<span class="price-high">${value:.2f}</span>'


def format_price_text(value):
    if value == 0:
        return "FREE"
    if value < 1:
        return f"${value:.4f}"
    if value < 10:
        return f"${value:.3f}"
    return f"${value:.2f}"


def format_modalities_html(modalities):
    if not modalities:
        return "—"

    labels = {
        "text": "TEXT",
        "image": "IMAGE",
        "audio": "AUDIO",
        "video": "VIDEO",
        "file": "FILE",
    }
    return "".join(
        f'<span class="modality-badge mod-{html_escape(mod)}">{html_escape(labels.get(mod, mod.upper()))}</span>'
        for mod in modalities
    )


def format_params_html(params):
    if not params:
        return '<span class="muted">—</span>'

    shown = params[:4]
    html = "".join(f'<span class="param-badge">{html_escape(param)}</span>' for param in shown)
    extra = len(params) - len(shown)
    if extra > 0:
        html += f'<span class="param-badge">+{extra}</span>'
    return html


def generate_flashship_html(models, fetch_time, explorer_url="/", flashship_url="/flashship"):
    flashship_models = pick_flashship_models(models)
    available_models = [m for m in flashship_models if m["available"]]
    tracked_variants = len(flashship_models)
    available_count = len(available_models)
    lowest_input = min((m["prompt_price_1m"] for m in available_models), default=0)
    max_ctx = max((m["context_length"] for m in available_models), default=0)
    max_output = max((m["max_completion"] for m in available_models), default=0)

    fetch_str = fetch_time.strftime("%Y-%m-%d %H:%M:%S UTC")
    subtitle = "OpenAI / Anthropic / Google / Grok / DeepSeek / Qwen / Kimi / MiniMax / Z.ai"

    paid_inputs = [m["prompt_price_1m"] for m in available_models if m["prompt_price_1m"] > 0]
    paid_outputs = [m["completion_price_1m"] for m in available_models if m["completion_price_1m"] > 0]
    min_input = min(paid_inputs) if paid_inputs else 0
    min_output = min(paid_outputs) if paid_outputs else 0

    rows = []
    for row in flashship_models:
        if not row["available"]:
            rows.append(
                f"""<tr data-company="{html_escape(row["company"])}" data-family="{html_escape(row["family_label"])}" data-variant="{html_escape(row["variant_label"])}" data-model="Unavailable" data-input="" data-output="" data-reasoning="" data-context="" data-max-output="" data-modalities="" data-params="0">
  <td class="cell-provider">{html_escape(row["company"])}</td>
  <td class="cell-family">{html_escape(row["family_label"])}</td>
  <td class="cell-family">{html_escape(row["variant_label"])}</td>
  <td class="cell-model"><div class="model-name">Unavailable</div></td>
  <td class="cell-price"><span class="muted">—</span></td>
  <td class="cell-price"><span class="muted">—</span></td>
  <td class="cell-price"><span class="muted">—</span></td>
  <td class="cell-ctx"><span class="muted">—</span></td>
  <td class="cell-ctx"><span class="muted">—</span></td>
  <td><span class="muted">—</span></td>
  <td><span class="muted">—</span></td>
</tr>"""
            )
            continue

        input_html = format_price_html(row["prompt_price_1m"])
        if row["prompt_price_1m"] == 0 or row["prompt_price_1m"] == min_input:
            input_html = f'<span class="cmp-best">{input_html}</span>'

        output_html = format_price_html(row["completion_price_1m"])
        if row["completion_price_1m"] == 0 or row["completion_price_1m"] == min_output:
            output_html = f'<span class="cmp-best">{output_html}</span>'

        context_html = html_escape(format_context(row["context_length"]))
        if row["context_length"] == max_ctx:
            context_html = f'<span class="cmp-best">{context_html}</span>'

        max_output_html = html_escape(format_context(row["max_completion"]))
        if row["max_completion"] == max_output:
            max_output_html = f'<span class="cmp-best">{max_output_html}</span>'

        modality_sort = " ".join(row["input_modalities"] + row["output_modalities"])
        params_sort = str(len(row["supported_params"]))
        rows.append(
            f"""<tr data-company="{html_escape(row["company"])}" data-family="{html_escape(row["family_label"])}" data-variant="{html_escape(row["variant_label"])}" data-model="{html_escape(row["name"] + ' ' + row["id"])}" data-input="{row["prompt_price_1m"]}" data-output="{row["completion_price_1m"]}" data-reasoning="{row["reasoning_price_1m"]}" data-context="{row["context_length"]}" data-max-output="{row["max_completion"]}" data-modalities="{html_escape(modality_sort)}" data-params="{params_sort}">
  <td class="cell-provider">{html_escape(row["company"])}</td>
  <td class="cell-family">{html_escape(row["family_label"])}</td>
  <td class="cell-family">{html_escape(row["variant_label"])}</td>
  <td class="cell-model">
    <div class="model-name">{html_escape(row["name"])}</div>
    <div class="model-id">{html_escape(row["id"])}</div>
    <div class="model-desc">{html_escape(row["description"])}</div>
  </td>
  <td class="cell-price">{input_html}</td>
  <td class="cell-price">{output_html}</td>
  <td class="cell-price">{format_price_html(row["reasoning_price_1m"])}</td>
  <td class="cell-ctx">{context_html}</td>
  <td class="cell-ctx">{max_output_html}</td>
  <td>
    <div class="modality-stack">
      <div class="modality-row"><span class="muted">IN</span>{format_modalities_html(row["input_modalities"])}</div>
      <div class="modality-row"><span class="muted">OUT</span>{format_modalities_html(row["output_modalities"])}</div>
    </div>
  </td>
  <td><div class="param-badges">{format_params_html(row["supported_params"])}</div></td>
</tr>"""
        )

    rows_html = "\n".join(rows)

    html = f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Flashship — {fetch_time.strftime('%Y-%m-%d %H:%M')}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@300;400;500&family=Instrument+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

[data-theme="dark"] {{
  --bg-deep: #0a0e17;
  --bg-surface: #111825;
  --bg-card: #1a2235;
  --bg-hover: #212d45;
  --border: #2a3550;
  --border-bright: #3d4f6f;
  --text-primary: #e2e8f0;
  --text-secondary: #8892a8;
  --text-dim: #5a6578;
  --accent-cyan: #22d3ee;
  --accent-cyan-dim: rgba(34,211,238,0.12);
  --accent-amber: #fbbf24;
  --accent-amber-dim: rgba(251,191,36,0.10);
  --accent-green: #34d399;
  --accent-green-dim: rgba(52,211,153,0.10);
  --accent-rose: #fb7185;
  --accent-rose-dim: rgba(251,113,133,0.10);
  --accent-violet: #a78bfa;
  --accent-violet-dim: rgba(167,139,250,0.10);
  --grain-opacity: 0.03;
  --glow-opacity: 0.06;
  --scrollbar-track: #0a0e17;
}}

[data-theme="light"] {{
  --bg-deep: #f4f6f9;
  --bg-surface: #eaecf1;
  --bg-card: #ffffff;
  --bg-hover: #f0f2f7;
  --border: #d5d9e2;
  --border-bright: #bfc5d2;
  --text-primary: #1a1d26;
  --text-secondary: #555d6e;
  --text-dim: #8891a0;
  --accent-cyan: #0891b2;
  --accent-cyan-dim: rgba(8,145,178,0.08);
  --accent-amber: #d97706;
  --accent-amber-dim: rgba(217,119,6,0.07);
  --accent-green: #059669;
  --accent-green-dim: rgba(5,150,105,0.07);
  --accent-rose: #e11d48;
  --accent-rose-dim: rgba(225,29,72,0.06);
  --accent-violet: #7c3aed;
  --accent-violet-dim: rgba(124,58,237,0.07);
  --grain-opacity: 0.015;
  --glow-opacity: 0.03;
  --scrollbar-track: #f4f6f9;
}}

:root {{
  --radius: 8px;
  --font-mono: 'DM Mono', 'Fira Code', monospace;
  --font-sans: 'Instrument Sans', system-ui, sans-serif;
}}

html {{ scroll-behavior: smooth; }}

body {{
  font-family: var(--font-sans);
  background: var(--bg-deep);
  color: var(--text-primary);
  min-height: 100vh;
  line-height: 1.5;
  transition: background 0.3s, color 0.3s;
}}

body::before {{
  content: '';
  position: fixed;
  inset: 0;
  z-index: 0;
  opacity: var(--grain-opacity);
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  pointer-events: none;
}}

body::after {{
  content: '';
  position: fixed;
  top: -200px;
  right: -100px;
  width: 600px;
  height: 600px;
  background: radial-gradient(circle, rgba(34,211,238,var(--glow-opacity)) 0%, transparent 70%);
  pointer-events: none;
  z-index: 0;
}}

.container {{
  position: relative;
  z-index: 1;
  max-width: 1600px;
  margin: 0 auto;
  padding: 32px 24px;
}}

.header {{
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 24px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--border);
  animation: fadeDown 0.6s ease-out;
  gap: 16px;
}}

.header-left h1 {{
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.5px;
  background: linear-gradient(135deg, var(--text-primary) 0%, var(--accent-cyan) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}}

.subtitle {{
  margin-top: 8px;
  color: var(--text-secondary);
  font-size: 14px;
}}

.header-right {{
  display: flex;
  align-items: flex-end;
  gap: 16px;
}}

.header .meta {{
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-dim);
  text-align: right;
  line-height: 1.8;
}}

.header .meta span {{
  color: var(--accent-cyan);
}}

.toggle-group {{
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}}

.toggle-pill {{
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  border-radius: 20px;
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--text-dim);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.25s;
  user-select: none;
  text-decoration: none;
}}

.toggle-pill:hover {{
  border-color: var(--accent-cyan);
  color: var(--text-secondary);
}}

.toggle-pill.is-active {{
  border-color: var(--accent-cyan);
  background: var(--accent-cyan-dim);
  color: var(--accent-cyan);
}}

.toggle-pill svg {{
  width: 14px;
  height: 14px;
  transition: transform 0.3s;
}}

[data-theme="light"] .toggle-pill.theme-toggle svg {{ transform: rotate(180deg); }}

.stats-bar {{
  display: flex;
  gap: 16px;
  margin-bottom: 20px;
  flex-wrap: wrap;
  animation: fadeDown 0.6s ease-out 0.1s both;
}}

.stat-card {{
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 20px;
  flex: 1;
  min-width: 180px;
}}

.stat-card .label {{
  font-size: 11px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 1.2px;
  color: var(--text-dim);
  margin-bottom: 4px;
}}

.stat-card .value {{
  font-family: var(--font-mono);
  font-size: 22px;
  font-weight: 500;
  color: var(--accent-cyan);
}}

.stat-card .value.green {{ color: var(--accent-green); }}
.stat-card .value.amber {{ color: var(--accent-amber); }}
.stat-card .value.rose {{ color: var(--accent-rose); }}

.info-card {{
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px 18px;
  margin-bottom: 20px;
  color: var(--text-secondary);
  animation: fadeDown 0.6s ease-out 0.15s both;
}}

.info-card strong {{
  color: var(--text-primary);
}}

.table-wrap {{
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  animation: fadeUp 0.6s ease-out 0.2s both;
}}

.table-scroll {{
  overflow-x: auto;
}}

table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}}

thead th {{
  background: var(--bg-card);
  border-bottom: 2px solid var(--border-bright);
  padding: 12px 16px;
  text-align: left;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--text-dim);
  white-space: nowrap;
}}

thead th.sortable {{
  cursor: pointer;
  user-select: none;
}}

thead th.sortable:hover {{
  color: var(--accent-cyan);
}}

thead th.sorted {{
  color: var(--accent-cyan);
}}

.sort-arrow {{
  display: inline-block;
  margin-left: 4px;
  opacity: 0.4;
  font-size: 10px;
}}

thead th.sorted .sort-arrow {{
  opacity: 1;
}}

tbody tr {{
  border-bottom: 1px solid var(--border);
  transition: background 0.15s;
}}

tbody tr:hover {{
  background: var(--bg-hover);
}}

tbody td {{
  padding: 12px 16px;
  white-space: nowrap;
  vertical-align: top;
}}

.cell-provider {{
  font-weight: 700;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.7px;
}}

.cell-family {{
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-secondary);
}}

.cell-model {{
  min-width: 360px;
  max-width: 420px;
  white-space: normal;
}}

.model-name {{
  font-weight: 600;
  font-size: 13px;
  color: var(--text-primary);
}}

.model-id {{
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-dim);
  margin-top: 3px;
  word-break: break-all;
}}

.model-desc {{
  margin-top: 8px;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.6;
}}

.cell-price, .cell-ctx {{
  font-family: var(--font-mono);
  font-size: 13px;
}}

.price-free {{ color: var(--accent-green); font-weight: 500; }}
.price-low {{ color: var(--accent-green); }}
.price-mid {{ color: var(--accent-amber); }}
.price-high {{ color: var(--accent-rose); }}

.modality-badge {{
  display: inline-block;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 2px 8px;
  border-radius: 4px;
  margin: 1px 2px 1px 0;
}}

.mod-text {{ background: var(--accent-cyan-dim); color: var(--accent-cyan); }}
.mod-image {{ background: var(--accent-violet-dim); color: var(--accent-violet); }}
.mod-audio {{ background: var(--accent-amber-dim); color: var(--accent-amber); }}
.mod-video {{ background: var(--accent-rose-dim); color: var(--accent-rose); }}
.mod-file {{ background: var(--accent-green-dim); color: var(--accent-green); }}

.modality-stack {{
  display: flex;
  flex-direction: column;
  gap: 4px;
}}

.modality-row {{
  display: flex;
  align-items: center;
  gap: 6px;
}}

.param-badges {{
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  max-width: 240px;
}}

.param-badge {{
  font-size: 9px;
  font-family: var(--font-mono);
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  color: var(--text-dim);
}}

.cmp-best {{
  display: inline-block;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--accent-green-dim);
}}

.muted {{
  color: var(--text-dim);
}}

.footer {{
  margin-top: 20px;
  color: var(--text-dim);
  font-size: 12px;
  text-align: right;
}}

@keyframes fadeDown {{
  from {{ opacity: 0; transform: translateY(-12px); }}
  to {{ opacity: 1; transform: translateY(0); }}
}}

@keyframes fadeUp {{
  from {{ opacity: 0; transform: translateY(12px); }}
  to {{ opacity: 1; transform: translateY(0); }}
}}

@media (max-width: 768px) {{
  .container {{ padding: 24px 16px; }}
  .header {{ flex-direction: column; align-items: flex-start; }}
  .header-right {{ width: 100%; flex-direction: column; align-items: flex-start; }}
  .header .meta {{ text-align: left; }}
  .toggle-group {{ justify-content: flex-start; }}
  .stat-card {{ min-width: 140px; }}
  .cell-model {{ min-width: 280px; }}
}}

::-webkit-scrollbar {{ width: 6px; height: 6px; }}
::-webkit-scrollbar-track {{ background: var(--scrollbar-track); }}
::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}
::-webkit-scrollbar-thumb:hover {{ background: var(--border-bright); }}
</style>
</head>
<body>
  <div class="container">
    <header class="header">
      <div class="header-left">
        <h1>Flashship Frontier Table</h1>
        <div class="subtitle">{html_escape(subtitle)}</div>
      </div>
      <div class="header-right">
        <div class="meta">
          Source <span>OpenRouter</span><br>
          Updated <span>{fetch_str}</span>
        </div>
        <div class="toggle-group">
          <a class="toggle-pill" href="{html_escape(explorer_url)}">Explorer</a>
          <a class="toggle-pill is-active" href="{html_escape(flashship_url)}">Flashship</a>
          <button class="toggle-pill theme-toggle" id="themeToggle" type="button" aria-label="Toggle theme">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M12 3v2.5M12 18.5V21M4.93 4.93l1.77 1.77M17.3 17.3l1.77 1.77M3 12h2.5M18.5 12H21M4.93 19.07l1.77-1.77M17.3 6.7l1.77-1.77M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z"/>
            </svg>
            Theme
          </button>
        </div>
      </div>
    </header>

    <section class="stats-bar">
      <div class="stat-card">
        <div class="label">Tracked Companies</div>
        <div class="value">{len(FLASHSHIP_TARGETS)}</div>
      </div>
      <div class="stat-card">
        <div class="label">Tracked Variants</div>
        <div class="value green">{tracked_variants}</div>
      </div>
      <div class="stat-card">
        <div class="label">Available Variants</div>
        <div class="value green">{available_count}</div>
      </div>
      <div class="stat-card">
        <div class="label">Lowest Input</div>
        <div class="value amber">{html_escape(format_price_text(lowest_input))}</div>
      </div>
      <div class="stat-card">
        <div class="label">Largest Context</div>
        <div class="value rose">{format_context(max_ctx)}</div>
      </div>
    </section>

    <section class="info-card">
      <strong>Selection rule:</strong> each company is pinned to its current latest model family, and this page includes all maintained core variants inside that same family, including lighter and fuller tiers when OpenRouter exposes them. All prices, context, max output and supported parameters come directly from the matched OpenRouter payload. Cheapest input/output and largest context/max output are highlighted.
    </section>

    <section class="table-wrap">
      <div class="table-scroll">
        <table id="flashshipTable">
          <thead>
            <tr>
              <th class="sortable" data-sort="company" data-sort-type="text">Company <span class="sort-arrow">↑</span></th>
              <th class="sortable" data-sort="family" data-sort-type="text">Family <span class="sort-arrow">↑</span></th>
              <th class="sortable" data-sort="variant" data-sort-type="text">Variant <span class="sort-arrow">↑</span></th>
              <th class="sortable" data-sort="model" data-sort-type="text">Model <span class="sort-arrow">↑</span></th>
              <th class="sortable" data-sort="input" data-sort-type="number">Input $/1M <span class="sort-arrow">↑</span></th>
              <th class="sortable" data-sort="output" data-sort-type="number">Output $/1M <span class="sort-arrow">↑</span></th>
              <th class="sortable" data-sort="reasoning" data-sort-type="number">Reasoning $/1M <span class="sort-arrow">↑</span></th>
              <th class="sortable" data-sort="context" data-sort-type="number">Context <span class="sort-arrow">↑</span></th>
              <th class="sortable" data-sort="max-output" data-sort-type="number">Max Output <span class="sort-arrow">↑</span></th>
              <th class="sortable" data-sort="modalities" data-sort-type="text">Modalities <span class="sort-arrow">↑</span></th>
              <th class="sortable" data-sort="params" data-sort-type="number">Supported Params <span class="sort-arrow">↑</span></th>
            </tr>
          </thead>
          <tbody id="flashshipTableBody">
            {rows_html}
          </tbody>
        </table>
      </div>
    </section>

    <div class="footer">Max output leader: {html_escape(format_context(max_output))}</div>
  </div>

  <script>
    const root = document.documentElement;
    const toggle = document.getElementById('themeToggle');
    const tableBody = document.getElementById('flashshipTableBody');
    const sortHeaders = Array.from(document.querySelectorAll('#flashshipTable thead th.sortable'));
    const storedTheme = localStorage.getItem('theme') || 'dark';
    root.setAttribute('data-theme', storedTheme);
    toggle.addEventListener('click', () => {{
      const nextTheme = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', nextTheme);
      localStorage.setItem('theme', nextTheme);
    }});

    let sortKey = null;
    let sortAsc = true;

    function compareValues(a, b, type) {{
      const aMissing = a === '';
      const bMissing = b === '';
      if (aMissing && bMissing) return 0;
      if (aMissing) return 1;
      if (bMissing) return -1;

      if (type === 'number') {{
        return Number(a) - Number(b);
      }}
      return String(a).localeCompare(String(b), 'en', {{ numeric: true, sensitivity: 'base' }});
    }}

    function renderFlashshipSort() {{
      const rows = Array.from(tableBody.querySelectorAll('tr'));
      rows.sort((rowA, rowB) => {{
        if (!sortKey) {{
          return Number(rowA.dataset.originalIndex) - Number(rowB.dataset.originalIndex);
        }}

        const type = sortHeaders.find(th => th.dataset.sort === sortKey)?.dataset.sortType || 'text';
        const a = rowA.dataset[sortKey.replace(/-([a-z])/g, (_, c) => c.toUpperCase())] || '';
        const b = rowB.dataset[sortKey.replace(/-([a-z])/g, (_, c) => c.toUpperCase())] || '';
        const result = compareValues(a, b, type);
        if (result !== 0) return sortAsc ? result : -result;

        return Number(rowA.dataset.originalIndex) - Number(rowB.dataset.originalIndex);
      }});
      rows.forEach(row => tableBody.appendChild(row));

      sortHeaders.forEach(th => {{
        const active = th.dataset.sort === sortKey;
        th.classList.toggle('sorted', active);
        const arrow = th.querySelector('.sort-arrow');
        if (arrow) {{
          arrow.textContent = active ? (sortAsc ? '↑' : '↓') : '↑';
        }}
      }});
    }}

    Array.from(tableBody.querySelectorAll('tr')).forEach((row, index) => {{
      row.dataset.originalIndex = String(index);
    }});

    sortHeaders.forEach(th => {{
      th.addEventListener('click', () => {{
        const nextKey = th.dataset.sort;
        if (sortKey === nextKey) {{
          sortAsc = !sortAsc;
        }} else {{
          sortKey = nextKey;
          sortAsc = true;
        }}
        renderFlashshipSort();
      }});
    }});
  </script>
</body>
</html>"""
    return html
