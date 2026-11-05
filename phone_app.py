"""Phone-first demo UI for Hack the World."""

from __future__ import annotations

import base64
import os

from flask import Flask, redirect, render_template_string, request, url_for

from agent.factory import create_provider
from agent.loop import AgentLoop, LoopOutcome, LoopResult
from agent.providers import ProviderError
from diagnostic_core.engine import DiagnosticSession
from diagnostic_core.models import Rejected, SessionStatus as S
from history_store import HistoryStore

app = Flask(__name__)

STATE = {"loop": None, "last_result": None, "error": None, "provider": None,
         "provider_label": None, "images": {}, "advance_note": None,
         "timeline": [], "draft_problem": "", "draft_answer": "",
         "history_session_id": None, "active_id": None, "cases": {}}

CHECKPOINT_BUNDLE_VERSION = 1

# Per-round decision allowance vs session-wide billed-step cap. Each user
# result grants a fresh advance; the session cap keeps retries bounded.
ADVANCE_STEP_BUDGET = 14
SESSION_STEP_BUDGET = 60

# Factual timeline entries are derived only from real snapshot diffs and
# real user inputs; the UI never invents conversation history.
TIMELINE_LIMIT = 60

_STORE = None


def get_store():
    """Process-wide history store, created lazily so imports stay side-effect free."""
    global _STORE
    if _STORE is None:
        default = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "history.db")
        _STORE = HistoryStore(os.environ.get("HTW_HISTORY_DB", default))
    return _STORE

PAGE = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#060a12">
<title>Hack the World</title>
<style>
:root { font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; color-scheme: dark; --bg:#060a12; --panel:#0d141e; --line:#23364d; --text:#eef5ff; --muted:#93a7bd; --accent:#66d9ff; --accent2:#8b7cff; --good:#6fe7b0; --bad:#ff7d8a; }
* { box-sizing:border-box; }
body { margin:0; min-height:100vh; background:radial-gradient(1100px 480px at 50% -140px, rgba(83,116,255,.16), transparent 60%), radial-gradient(800px 420px at 85% 10%, rgba(69,208,255,.07), transparent 60%), var(--bg); color:var(--text); }
body::before { content:""; position:fixed; inset:0; pointer-events:none; background-image:linear-gradient(rgba(120,170,220,.05) 1px, transparent 1px), linear-gradient(90deg, rgba(120,170,220,.05) 1px, transparent 1px); background-size:44px 44px; mask-image:radial-gradient(900px 520px at 50% 0%, #000 30%, transparent 75%); }
main { max-width:1240px; margin:auto; padding:20px 18px 60px; }
:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
header.top { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:14px; }
.brand { font-weight:800; letter-spacing:.2px; font-size:21px; line-height:1.15; }
.brand small { display:block; font-size:12px; font-weight:500; color:var(--muted); letter-spacing:.6px; }
.meta { font-size:12px; color:#b8c8da; border:1px solid #29415b; background:#0c1520; border-radius:999px; padding:7px 12px; white-space:nowrap; }
.layout { display:grid; gap:14px; grid-template-columns:minmax(0,1fr); }
.zone-assistant { min-width:0; display:grid; gap:14px; align-content:start; }
@media (min-width:1024px) { .layout { grid-template-columns:295px minmax(0,1fr) 305px; grid-template-areas:"timeline assistant tech"; align-items:start; } .zone-timeline { grid-area:timeline; } .zone-assistant { grid-area:assistant; } .zone-tech { grid-area:tech; } .sticky { position:sticky; top:12px; } }
.card { background:rgba(13,20,30,.94); border:1px solid var(--line); border-radius:18px; padding:18px; margin:0; animation:rise .35s ease both; }
@keyframes rise { from { opacity:0; transform:translateY(8px); } }
.card h2 { margin:0 0 12px; font-size:19px; }
.card h3 { margin:18px 0 10px; font-size:14px; color:#c9d9e8; text-transform:uppercase; letter-spacing:.8px; }
.strip { max-width:860px; margin:0 auto 12px; }
.error { border-color:#753d47; background:#211116; }
.next { border-color:#365b79; background:linear-gradient(180deg,#101c29,#0d1621); }
.final { border-color:#39715f; background:linear-gradient(180deg,#10231d,#0d1916); }
.hero { text-align:center; padding:6px 0 2px; }
.orb-wrap { width:248px; height:248px; margin:0 auto; position:relative; display:grid; place-items:center; }
.orb-svg { width:100%; height:100%; overflow:visible; transition:transform .12s ease; }
.orb-spin-a { animation:orbSpin 9s linear infinite; transform-box:view-box; transform-origin:120px 120px; }
.orb-spin-b { animation:orbSpin 14s linear infinite reverse; transform-box:view-box; transform-origin:120px 120px; }
.orb-spin-c { animation:orbSpin 5s linear infinite; transform-box:view-box; transform-origin:120px 120px; }
.orb-breathe { animation:breathe 3.4s ease-in-out infinite; transform-box:fill-box; transform-origin:center; }
.orb-sweep { position:absolute; width:196px; height:196px; border-radius:50%; background:conic-gradient(from 0deg, transparent 0deg, rgba(140,220,255,.4) 24deg, transparent 60deg); -webkit-mask:radial-gradient(closest-side, transparent 76%, #000 77%); mask:radial-gradient(closest-side, transparent 76%, #000 77%); animation:orbSpin 7s linear infinite; pointer-events:none; }
.orb-p1 { animation:drift 4.2s ease-in-out infinite alternate; }
.orb-p2 { animation:drift 5.1s ease-in-out infinite alternate-reverse; }
.orb-p3 { animation:drift 4.7s ease-in-out infinite alternate; }
.orb-p4 { animation:drift 5.6s ease-in-out infinite alternate-reverse; }
@keyframes orbSpin { to { transform:rotate(360deg); } }
@keyframes breathe { 50% { transform:scale(1.06); opacity:.75; } }
@keyframes drift { from { transform:translateY(-3px); opacity:.5; } to { transform:translateY(3px); opacity:1; } }
.orb-core { transform-box:fill-box; transform-origin:center; transition:filter .25s ease; }
body.listening .orb-core { filter:brightness(1.18) saturate(1.25); }
body.listening .orb-spin-a { animation-duration:1.4s; }
body.thinking .orb-spin-a { animation-duration:1s; }
body.thinking .orb-spin-c { animation-duration:1.6s; }
body.thinking .orb-core { animation:corePulse 1.1s ease-in-out infinite; }
body.speaking .orb-core { animation:speakPulse .65s ease-in-out infinite alternate; }
body.speaking .orb-spin-a circle { stroke:var(--good); }
body.error .orb-core { fill:url(#orbCoreError); }
body.error .orb-spin-a { animation-duration:.6s; }
body.error .orb-spin-a circle { stroke:var(--bad); }
@keyframes corePulse { 50% { transform:scale(.93); } }
@keyframes speakPulse { from { transform:scale(.96); } to { transform:scale(1.07); } }
.orb-label { position:absolute; bottom:2px; left:0; right:0; font-size:12px; letter-spacing:2px; text-transform:uppercase; color:#8fb4cf; }
.orb-sub { margin:2px 0 10px; font-size:14px; color:var(--muted); }
.bubble { position:relative; max-width:640px; margin:0 auto 14px; text-align:left; background:linear-gradient(180deg, rgba(18,29,43,.94), rgba(12,20,31,.94)); border:1px solid #263b53; border-radius:20px; padding:16px 18px; box-shadow:0 14px 50px rgba(0,0,0,.22); }
.bubble .state { color:var(--accent); font-size:12px; font-weight:800; letter-spacing:.8px; text-transform:uppercase; margin-bottom:6px; }
.bubble .message { font-size:18px; line-height:1.45; }
.controls { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px,1fr)); gap:10px; max-width:640px; margin:0 auto 16px; }
button { appearance:none; border:0; cursor:pointer; touch-action:manipulation; border-radius:12px; min-height:48px; padding:12px 14px; font-weight:700; font-size:15px; background:linear-gradient(135deg, #d8f5ff, #bbcbff); color:#0a1018; }
button.secondary { background:#121d2a; color:#dce9f7; border:1px solid #2a4058; }
button.mic-active { background:linear-gradient(135deg, #c7ffe5, #a6e9ff); }
button:disabled { opacity:.55; cursor:wait; }
label { display:block; margin:10px 0 6px; font-weight:700; }
textarea, input[type=file] { width:100%; }
textarea { min-height:96px; resize:vertical; border-radius:12px; padding:12px; background:#09111a; color:#fff; border:1px solid #2b3e52; font:inherit; }
.composer textarea { min-height:110px; border-radius:16px; }
.composer-row { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:10px; }
.filebox { border:1px dashed #36516d; border-radius:12px; padding:12px; background:#0a131d; }
.badges { display:flex; flex-wrap:wrap; gap:7px; margin:4px 0 10px; }
.badge { display:inline-flex; padding:5px 10px; border:1px solid #334a63; border-radius:999px; color:#bed0e2; font-size:12px; }
.progress { display:grid; grid-template-columns:repeat(5,1fr); gap:6px; margin:9px 0 2px; }
.step { text-align:center; font-size:11px; color:#71859a; padding-top:8px; border-top:2px solid #1f3042; }
.step.active { color:#d9f5ff; border-color:var(--accent); }
.step.done { color:#a8d8c3; border-color:var(--good); }
.timeline { list-style:none; margin:0; padding:0; }
.t-event { display:flex; gap:10px; position:relative; padding:0 0 14px 4px; }
.t-event::before { content:""; position:absolute; left:14px; top:24px; bottom:-2px; width:2px; background:#22364d; }
.t-event:last-child::before { display:none; }
.t-glyph { flex:none; width:22px; height:22px; border-radius:50%; display:grid; place-items:center; font-size:11px; color:var(--accent); border:1px solid #2c435b; background:#0a141f; }
.t-body strong { display:block; font-size:14px; }
.t-body .muted { font-size:13px; }
.evidence-grid { display:flex; flex-wrap:wrap; gap:8px; }
.evidence-chip { border:1px solid #2c435b; background:#0a141f; border-radius:12px; padding:8px 10px; font-size:13px; }
.hypothesis { position:relative; padding:7px 0 7px 18px; margin:10px 0; }
.hypothesis::before { content:""; position:absolute; left:0; top:13px; width:8px; height:8px; border-radius:50%; background:var(--accent2); }
.hypothesis strong { display:block; line-height:1.3; }
.muted, small { color:var(--muted); }
details summary { cursor:pointer; font-weight:700; color:#c9d9e8; }
details[open] summary { margin-bottom:12px; }
.voice-note { font-size:12px; color:#7f94aa; text-align:center; margin-top:-5px; }
.fab { position:fixed; right:18px; bottom:18px; width:60px; height:60px; border-radius:50%; padding:0; display:grid; place-items:center; font-size:12px; font-weight:800; letter-spacing:1px; box-shadow:0 12px 32px rgba(0,0,0,.4); }
.big-action { font-size:19px; line-height:1.45; }
@media (max-width:520px) { main { padding-left:14px; padding-right:14px; } .orb-wrap { width:212px; height:212px; } .orb-sweep { width:168px; height:168px; } .composer-row { grid-template-columns:1fr; } button { width:100%; } .progress { gap:3px; } .step { font-size:9px; } }
.sessions { list-style:none; margin:0; padding:0; }
.sessions li { padding:8px 0; border-top:1px solid #1c2c40; }
.sessions li:first-child { border-top:0; padding-top:0; }
.sessions a { color:var(--accent); font-weight:700; text-decoration:none; }
input[type=text] { width:100%; border-radius:12px; padding:10px 12px; background:#09111a; color:#fff; border:1px solid #2b3e52; font:inherit; }
.rename-row { display:flex; gap:8px; margin-top:8px; }
.rename-row button { white-space:nowrap; }
.orb-spin-d { animation:orbSpin 22s linear infinite; transform-box:view-box; transform-origin:120px 120px; }
.orb-spin-a circle,.orb-spin-b circle,.orb-spin-d circle { transition:stroke .3s ease; }
.orb-inner { animation:shimmer 3s ease-in-out infinite alternate; transform-box:fill-box; transform-origin:center; }
@keyframes shimmer { from { opacity:.4; } to { opacity:.7; } }
.orb-scanline { position:absolute; left:8%; right:8%; top:50%; height:2px; border-radius:2px; background:linear-gradient(90deg, transparent, rgba(140,220,255,.8), transparent); opacity:0; pointer-events:none; }
body.thinking .orb-scanline { opacity:1; animation:scanY 1.3s ease-in-out infinite alternate; }
@keyframes scanY { from { transform:translateY(-52px); } to { transform:translateY(52px); } }
body.completed .orb-core { animation:completeBurst 2.2s ease-out 1; }
body.completed .orb-spin-a circle { stroke:var(--good); }
@keyframes completeBurst { 0% { transform:scale(1); filter:brightness(1); } 30% { transform:scale(1.22); filter:brightness(1.6); } 100% { transform:scale(1); filter:brightness(1.1); } }
.word-pop .orb-svg { transform:scale(1.03); }
.bg-glow-a,.bg-glow-b { position:fixed; border-radius:50%; pointer-events:none; z-index:-1; }
.bg-glow-a { width:520px; height:520px; left:-160px; top:-120px; background:radial-gradient(circle, rgba(83,116,255,.12), transparent 65%); animation:glowDrift 26s ease-in-out infinite alternate; }
.bg-glow-b { width:620px; height:620px; right:-220px; top:30%; background:radial-gradient(circle, rgba(69,208,255,.09), transparent 65%); animation:glowDrift 34s ease-in-out infinite alternate-reverse; }
@keyframes glowDrift { from { transform:translate(0,0); } to { transform:translate(60px,40px); } }
.bubble { animation:bubblePop .45s cubic-bezier(.2,.9,.3,1.15) both; }
@keyframes bubblePop { from { opacity:0; transform:scale(.96) translateY(6px); } }
.recents { display:grid; gap:8px; max-width:640px; margin:0 auto 14px; }
.recent-bubble { display:block; text-align:left; opacity:.72; border:1px solid #22364d; border-radius:14px; padding:9px 12px; color:var(--text); text-decoration:none; background:rgba(13,20,30,.7); animation:rise .4s ease both; font-size:13px; }
.recent-bubble strong { display:block; font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.6px; margin-bottom:2px; }
.recent-bubble span { display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.recent-user { border-color:#2f5a4c; }
.recent-user strong { color:var(--good); }
body { line-height:1.5; }
.drawer { border:0; padding:0; margin:0; }
.drawer>summary { list-style:none; cursor:pointer; font-weight:800; color:#c9d9e8; background:rgba(13,20,30,.94); border:1px solid var(--line); border-radius:14px; padding:12px 14px; margin-bottom:10px; }
.drawer>summary::-webkit-details-marker { display:none; }
.drawer-body { display:grid; gap:14px; align-content:start; }
@media (min-width:1024px) { body.js .drawer>summary { display:none; } .drawer:not([open])>.drawer-body { display:grid; } }
.hypothesis[data-status="supported"]::before,.hypothesis[data-status="confirmed"]::before { background:var(--good); }
.hypothesis[data-status="weakened"]::before { background:#ffcf7d; }
.hypothesis[data-status="eliminated"]::before { background:var(--bad); }
@media (prefers-reduced-motion:reduce) { .orb-svg *, .orb-sweep, .card, .bubble, .recent-bubble, .bg-glow-a, .bg-glow-b, .orb-scanline { animation:none !important; } .orb-core, .orb-svg { transition:none; } .orb-scanline { opacity:0 !important; } }
</style>
</head>
<body class="idle">
<div class="bg-glow-a"></div><div class="bg-glow-b"></div>
{% macro assistant_hero() %}<div class="card"><div class="hero">
<div class="orb-wrap" role="img" aria-label="Assistant status"><div class="orb-sweep"></div><div class="orb-scanline"></div><svg class="orb-svg" viewBox="0 0 240 240" aria-hidden="true"><defs><radialGradient id="orbCore" cx="38%" cy="32%" r="75%"><stop offset="0%" stop-color="#e8fbff"/><stop offset="18%" stop-color="#7fdcff"/><stop offset="45%" stop-color="#4f79e8"/><stop offset="72%" stop-color="#232a55"/><stop offset="100%" stop-color="#0c1226"/></radialGradient><radialGradient id="orbCoreError" cx="38%" cy="32%" r="75%"><stop offset="0%" stop-color="#ffe8ec"/><stop offset="25%" stop-color="#ff8b98"/><stop offset="55%" stop-color="#a83a4a"/><stop offset="100%" stop-color="#2a0e14"/></radialGradient><radialGradient id="orbHalo" cx="50%" cy="50%" r="50%"><stop offset="0%" stop-color="#66d9ff" stop-opacity=".28"/><stop offset="55%" stop-color="#8b7cff" stop-opacity=".1"/><stop offset="100%" stop-color="#8b7cff" stop-opacity="0"/></radialGradient><linearGradient id="orbArc" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#66d9ff"/><stop offset="100%" stop-color="#8b7cff"/></linearGradient></defs><circle cx="120" cy="120" r="112" fill="url(#orbHalo)" class="orb-breathe"/><g class="orb-spin-a"><circle cx="120" cy="120" r="86" fill="none" stroke="url(#orbArc)" stroke-width="2.5" stroke-dasharray="52 26 12 26" stroke-linecap="round" opacity=".9"/></g><g class="orb-spin-b"><circle cx="120" cy="120" r="70" fill="none" stroke="#66d9ff" stroke-width="1.5" stroke-dasharray="4 10" opacity=".55"/></g><g class="orb-spin-d"><circle cx="120" cy="120" r="98" fill="none" stroke="#8b7cff" stroke-width="1" stroke-dasharray="26 18 6 18" opacity=".4"/></g><g class="orb-spin-c"><circle cx="120" cy="34" r="7" fill="#8fe9ff" opacity=".25"/><circle cx="120" cy="34" r="3.5" fill="#8fe9ff"/><circle cx="120" cy="206" r="6" fill="#8fe9ff" opacity=".2"/><circle cx="120" cy="206" r="3" fill="#8fe9ff"/></g><circle cx="120" cy="120" r="46" fill="url(#orbCore)" class="orb-core"/><circle cx="120" cy="120" r="29" fill="url(#orbCore)" class="orb-inner"/><ellipse cx="104" cy="102" rx="20" ry="12" fill="#ffffff" opacity=".28" transform="rotate(-24 104 102)"/><g fill="#9fdcff"><circle cx="52" cy="88" r="1.6" class="orb-p1"/><circle cx="188" cy="96" r="1.3" class="orb-p2"/><circle cx="60" cy="160" r="1.4" class="orb-p3"/><circle cx="182" cy="162" r="1.7" class="orb-p4"/></g></svg><div class="orb-label" id="orbLabel">Ready</div></div>
<div class="orb-sub" id="orbSub">{% if error %}Needs attention{% elif session.next_action %}Next test ready{% elif session.recommendation %}Verified recommendation ready{% elif session.inconclusive %}Handoff ready{% elif session %}Reviewing evidence{% else %}Ready{% endif %}</div>
<div class="bubble" id="assistantBubble" aria-live="polite"><div class="state" id="assistantState">{% if error %}Attention{% elif session and session.recommendation %}Verified{% elif session and session.next_action %}Next diagnostic step{% elif session and session.inconclusive %}Inconclusive{% elif session %}Investigating{% else %}Ready{% endif %}</div><div class="message" id="assistantMessage">{% if error %}{{ error }}{% elif session and session.recommendation %}{{ session.recommendation.action }}{% elif session and session.next_action %}{{ session.next_action.action }}{% elif session and session.inconclusive %}{{ session.inconclusive.summary }}{% elif session %}I am reviewing the evidence and testing competing causes.{% else %}Tell me what the device is doing. You can speak, type, or add a photo.{% endif %}</div></div>
{% if recents %}<div class="recents">{% for pos, entry in recents %}<a class="recent-bubble{% if entry.kind == 'user' %} recent-user{% endif %}" href="#t-{{ pos }}"><strong>{{ entry.title }}</strong><span>{{ entry.detail }}</span></a>{% endfor %}</div>{% endif %}
<div class="controls"><button type="button" class="secondary" id="speakButton" onclick="speakCurrent()">Hear instruction</button><button type="button" class="secondary" id="stopButton" onclick="stopSpeech()">Stop</button><button type="button" class="secondary" id="handsFreeButton" onclick="toggleHandsFree()">Hands-free: off</button></div>
<div class="voice-note" id="voiceSupport" role="status"></div>
</div></div>{% endmacro %}
{% macro session_list(title) %}<h2>{{ title }}</h2><ul class="sessions">{% for s in sessions %}<li><a href="{{ url_for('view_history', session_id=s.id) }}">{{ s.name }}</a> <span class="badge">{% if s.archived %}archived{% elif s.case_status == "solved" %}solved{% elif s.case_status == "awaiting" %}awaiting result{% elif s.case_status == "inconclusive" %}inconclusive{% else %}open{% endif %}</span>{% if s.id == active_id %} <span class="badge">current</span>{% endif %}{% if not s.archived and s.id != active_id %}<form method="post" action="{{ url_for('switch_case', hid=s.id) }}" style="display:inline;margin-left:6px"><button type="submit" class="secondary" style="min-height:0;padding:4px 10px;font-size:12px">Open</button></form>{% endif %}<div class="muted">{{ s.updated_at[:16].replace("T", " ") }} UTC</div></li>{% endfor %}</ul>{% endmacro %}
<main>
<header class="top"><div class="brand">Hack the World<small>Evidence-driven field diagnostics</small></div><div class="meta">{{ provider_label or "Meta Muse" }}</div></header>
{% if error %}<div class="strip"><div class="card error" id="errorCard" tabindex="-1"><strong>Something needs attention</strong><div>{{ error }}</div></div></div>{% endif %}
{% if advance_note %}<div class="strip"><div class="card next">{{ advance_note }}</div></div>{% endif %}
{% if result and case_status != "solved" and (result.outcome.value == "provider_error" or result.outcome.value == "advance_exhausted") %}<div class="strip"><form method="post" action="{{ url_for('retry') }}"><input type="hidden" name="case_id" value="{{ active_id }}"><button type="submit" class="secondary" style="width:100%">Try again</button></form></div>{% endif %}
{% if viewing %}
<div class="strip"><div class="card"><h2>{{ viewing.session.name }}</h2><div class="badges"><span class="badge">{% if viewing.session.archived %}archived · read-only{% elif viewing.session.case_status == "solved" %}solved{% elif viewing.session.case_status == "awaiting" %}awaiting result{% elif viewing.session.case_status == "inconclusive" %}inconclusive{% else %}open{% endif %}</span><span class="badge">{{ viewing.events|length }} events</span></div><div class="muted">{{ viewing.session.problem }}</div><form method="post" action="{{ url_for('rename_history', session_id=viewing.session.id) }}"><div class="rename-row"><input type="text" name="name" value="{{ viewing.session.name }}" maxlength="80" aria-label="Session name"><button type="submit" class="secondary">Rename</button></div></form>{% if can_resume %}<form method="post" action="{{ url_for('switch_case', hid=viewing.session.id) }}"><button type="submit" style="width:100%;margin-top:10px">Resume investigation</button></form>{% endif %}{% if viewing.session.case_status == "solved" and not viewing.session.archived %}<form method="post" action="{{ url_for('reopen_case', hid=viewing.session.id) }}"><button type="submit" class="secondary" style="width:100%;margin-top:10px">Reopen case</button></form>{% endif %}<div style="margin-top:10px"><a href="{{ url_for('index') }}">{% if session %}Back to live investigation{% else %}Back{% endif %}</a></div></div></div>
<div class="strip"><div class="card"><h2>Timeline</h2>{% if viewing.events %}<ol class="timeline">{% for entry in viewing.events %}<li class="t-event"><span class="t-glyph" aria-hidden="true">{{ entry.glyph }}</span><div class="t-body"><strong>#{{ entry.seq }} · {{ entry.title }}</strong><div class="muted">{{ entry.detail }}</div><div class="muted">{{ entry.created_at[:16].replace("T", " ") }} UTC</div></div></li>{% endfor %}</ol>{% else %}<div class="muted">No events recorded yet.</div>{% endif %}</div></div>
{% elif not session %}
<div class="strip">{{ assistant_hero() }}</div>
<div class="strip"><div class="card"><form id="startForm" method="post" action="{{ url_for('start') }}" enctype="multipart/form-data"><h2>Start an investigation</h2><label>Describe the problem</label><textarea id="problemInput" name="problem" required placeholder="Example: Laptop powers on, fan spins, but the screen stays black.">{{ draft_problem }}</textarea><div class="controls" style="margin:10px 0 4px"><button type="button" class="secondary" onclick="startDictation('problemInput', this)">Speak symptoms</button><button type="button" class="secondary" onclick="document.getElementById('imageInput').click()">Add photo</button></div><div class="filebox"><input id="imageInput" type="file" name="image" accept="image/*" capture="environment"><small>A clear device photo is optional, but makes the demo visibly multimodal.</small></div><button type="submit" style="width:100%;margin-top:12px">Begin investigation</button></form></div></div>
{% if sessions %}<div class="strip"><div class="card">{{ session_list("Previous investigations") }}</div></div>{% endif %}
{% else %}
<div class="layout">
<section class="zone-assistant" aria-label="Assistant">
<div class="card"><div class="badges"><span class="badge">{{ session.status }}</span><span class="badge">{{ session.turn_count }} diagnostic turns</span><span class="badge">{{ result.steps_used if result else 0 }} Muse steps</span><span class="badge">{{ result.advance_steps if result else 0 }} steps this round</span><span class="badge">{{ result.outcome.value if result else "started" }}</span></div><div class="progress"><div class="step done">Observe</div><div class="step {% if session.hypotheses %}done{% else %}active{% endif %}">Hypothesize</div><div class="step {% if session.next_action %}active{% elif session.recommendation %}done{% endif %}">Test</div><div class="step {% if session.recommendation %}done{% elif session.hypotheses and not session.next_action %}active{% endif %}">Verify</div><div class="step {% if session.recommendation %}active{% endif %}">Fix</div></div><h3>Device problem</h3><div>{{ session.problem }}</div></div>
{{ assistant_hero() }}
{% if session.next_action %}<div class="card next"><h2>Do this next</h2><p class="big-action"><strong>{{ session.next_action.action }}</strong></p>{% if session.next_action.observations %}<div class="muted">Report:</div><ul>{% for o in session.next_action.observations %}<li>{{ o }}</li>{% endfor %}</ul>{% endif %}{% if case_status != "solved" %}<form id="resumeForm" class="composer" method="post" action="{{ url_for('resume') }}" enctype="multipart/form-data"><input type="hidden" name="case_id" value="{{ active_id }}"><label>What happened?</label><textarea id="answerInput" name="answer" required placeholder="Tell me exactly what you observed.">{{ draft_answer }}</textarea><div class="filebox" style="margin-top:10px"><input id="answerImageInput" type="file" name="image" accept="image/*" capture="environment"><small>Optional follow-up photo of what you observed.</small></div><div class="composer-row"><button type="button" id="answerMic" class="secondary" onclick="startDictation('answerInput', this)">Speak result</button><button type="submit">Submit & continue</button></div></form>{% endif %}</div>{% endif %}
{% if session.recommendation %}<div class="card final"><h2>Verified recommendation</h2><p class="big-action">{{ session.recommendation.action }}</p><small>Grounded in {{ session.recommendation.evidence_ids|length }} recorded evidence item(s).</small></div>{% endif %}
{% if session.inconclusive %}<div class="card"><h2>Inconclusive handoff</h2><p class="big-action">{{ session.inconclusive.summary }}</p><div class="muted">Checked {{ session.inconclusive.checked_evidence_ids|length }} recorded evidence item(s); this is not a verified diagnosis.</div><h3>Still possible</h3><div>{{ session.inconclusive.remaining_possibilities }}</div><h3>Safe next steps</h3><div>{{ session.inconclusive.safe_next_steps }}</div></div>{% endif %}
{% if case_status == "solved" %}<div class="card"><h2>Case solved</h2><div class="muted">{{ solved_note or "The technician marked this case solved." }}</div><form method="post" action="{{ url_for('reopen_case', hid=active_id) }}"><button type="submit" class="secondary" style="width:100%;margin-top:10px">Reopen case</button></form></div>{% elif session %}<form method="post" action="{{ url_for('solve_case', hid=active_id) }}"><div class="rename-row"><input type="text" name="note" maxlength="200" placeholder="Repair note (optional)" aria-label="Repair note"><button type="submit" class="secondary">Mark solved</button></div></form>{% endif %}
<form method="post" action="{{ url_for('reset') }}"><button type="submit" class="secondary" style="width:100%">Start a new investigation</button></form>
</section>
<section class="zone-timeline" aria-label="Investigation history"><details class="drawer"><summary>History & timeline</summary><div class="drawer-body">{% if sessions %}<div class="card sticky">{{ session_list("Investigations") }}</div>{% endif %}{% if timeline %}<div class="card"><h2>Timeline</h2><ol class="timeline">{% for entry in timeline %}<li class="t-event" id="t-{{ loop.index }}"><span class="t-glyph" aria-hidden="true">{{ entry.glyph }}</span><div class="t-body"><strong>{{ entry.title }}</strong><div class="muted">{{ entry.detail }}</div></div></li>{% endfor %}</ol></div>{% endif %}</div></details></section>
<section class="zone-tech" aria-label="Technical details"><div class="card sticky"><details><summary>Evidence & technical details</summary><h3>Evidence</h3>{% if session.evidence %}<div class="evidence-grid">{% for e in session.evidence %}<details class="evidence-chip"><summary><strong>{{ e.id.split(':')[-1] }}</strong> · {{ e.statement }}</summary><div class="muted">Source: {{ e.source }}</div>{% for pair in e.provenance %}<div class="muted">{{ pair[0] }}: {{ pair[1] }}</div>{% endfor %}</details>{% endfor %}</div>{% else %}<div class="muted">No evidence recorded yet.</div>{% endif %}<h3>Competing hypotheses</h3>{% if session.hypotheses %}{% for h in session.hypotheses %}<div class="hypothesis" data-status="{{ h.status }}"><strong>{{ h.cause }}</strong><div class="badges"><span class="badge">{{ h.status }}</span></div>{% if h.rationale %}<small>{{ h.rationale }}</small>{% endif %}</div>{% endfor %}{% else %}<div class="muted">No cause proposed yet.</div>{% endif %}</details></div></section>
</div>
{% endif %}
</main>
<button type="button" class="fab" id="floatingMic" onclick="floatingMic()" title="Voice input" aria-label="Voice input">MIC</button>
<script>
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let activeRecognition = null;
let wordTimer = null;
let handsFree = localStorage.getItem("htwHandsFree") === "1";
function setOrbState(state,label,bubbleText,subText){document.body.classList.remove("idle","listening","thinking","speaking","error");/* completed lingers as a tint, never removed here */document.body.classList.add(state);document.getElementById("orbLabel").textContent=label||state;if(bubbleText)document.getElementById("assistantMessage").textContent=bubbleText;const sub=document.getElementById("orbSub");if(sub){if(subText)sub.textContent=subText;else if(state==="idle"&&sub.dataset.base)sub.textContent=sub.dataset.base;}}
function updateHandsFreeButton(){const btn=document.getElementById("handsFreeButton");if(btn)btn.textContent=handsFree?"Hands-free: on":"Hands-free: off";}
function toggleHandsFree(){handsFree=!handsFree;localStorage.setItem("htwHandsFree",handsFree?"1":"0");updateHandsFreeButton();if(handsFree)speakCurrent();else if("speechSynthesis" in window)window.speechSynthesis.cancel();}
function chooseProfessionalVoice(){const voices=window.speechSynthesis?window.speechSynthesis.getVoices():[];return voices.find(v=>/Google UK English Male|Microsoft.*(David|Ryan|George)/i.test(v.name))||voices.find(v=>/^en-GB/i.test(v.lang))||voices.find(v=>/^en-US/i.test(v.lang))||voices[0];}
function speak(text){if(!("speechSynthesis" in window)||!text)return;window.speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(text);const voice=chooseProfessionalVoice();if(voice)u.voice=voice;u.rate=.94;u.pitch=.92;u.volume=1;u.onstart=()=>setOrbState("speaking","Speaking",null,"Speaking…");u.onboundary=(e)=>{if(e&&e.name==="word"){document.body.classList.add("word-pop");clearTimeout(wordTimer);wordTimer=setTimeout(()=>document.body.classList.remove("word-pop"),130);}};u.onend=()=>setOrbState("idle","Ready");u.onerror=()=>{setOrbState("error","Error","Spoken instructions hit a playback problem.","Needs attention");setTimeout(()=>{if(document.body.classList.contains("error"))setOrbState("idle","Ready");},4000);};window.speechSynthesis.speak(u);}
function stopSpeech(){if("speechSynthesis" in window)window.speechSynthesis.cancel();setOrbState("idle","Ready");}
function speakCurrent(){const text=document.getElementById("assistantMessage")?.innerText?.trim();speak(text);}
function startDictation(targetId,button){const target=document.getElementById(targetId);if(!target)return;if(!SpeechRecognition){document.getElementById("voiceSupport").textContent="Voice recognition is not available in this browser. You can still type and use spoken instructions.";return;}if(activeRecognition){try{activeRecognition.stop();}catch(_){}}const recognition=new SpeechRecognition();activeRecognition=recognition;recognition.lang="en-US";recognition.interimResults=true;recognition.continuous=false;const original=target.value.trim();let finalText="";recognition.onstart=()=>{setOrbState("listening","Listening","Listening. Tell me exactly what you observe.","Listening…");if(button)button.classList.add("mic-active");};recognition.onresult=(event)=>{let interim="";finalText="";for(let i=event.resultIndex;i<event.results.length;i++){const chunk=event.results[i][0].transcript;if(event.results[i].isFinal)finalText+=chunk;else interim+=chunk;}const spoken=(finalText||interim).trim();target.value=[original,spoken].filter(Boolean).join(original&&spoken?" ":"");};recognition.onerror=(event)=>{setOrbState("error","Error","I couldn't hear that clearly. You can try again or type the result.","Needs attention");setTimeout(()=>{if(document.body.classList.contains("error"))setOrbState("idle","Ready");},4000);document.getElementById("voiceSupport").textContent="Microphone: "+event.error;};recognition.onend=()=>{activeRecognition=null;if(button)button.classList.remove("mic-active");if(!document.body.classList.contains("error"))setOrbState("idle","Ready");};recognition.start();}
function floatingMic(){const answer=document.getElementById("answerInput");const problem=document.getElementById("problemInput");if(answer)startDictation("answerInput",document.getElementById("floatingMic"));else if(problem)startDictation("problemInput",document.getElementById("floatingMic"));else speakCurrent();}
for(const form of document.querySelectorAll("form")){form.addEventListener("submit",(event)=>{if(form.dataset.submitted){event.preventDefault();return;}form.dataset.submitted="1";if(form.id==="startForm"||form.id==="resumeForm"){localStorage.setItem("htwSpeakAfterLoad",handsFree?"1":"0");setOrbState("thinking","Thinking","Analyzing the evidence and deciding the safest next diagnostic step.","Analyzing evidence…");for(const btn of form.querySelectorAll("button[type=submit]")){btn.disabled=true;btn.textContent="Working…";}}});}
document.addEventListener("DOMContentLoaded",()=>{updateHandsFreeButton();document.body.classList.add("js");const drawer=document.querySelector(".drawer");if(drawer&&window.matchMedia){const mq=window.matchMedia("(min-width:1024px)");const syncDrawer=()=>{if(mq.matches)drawer.open=true;};syncDrawer();if(mq.addEventListener)mq.addEventListener("change",syncDrawer);}const support=document.getElementById("voiceSupport");support.textContent=SpeechRecognition?"Tap the microphone to speak; spoken instructions can continue hands-free.":"Spoken instructions are available. Voice input depends on browser support.";if(navigator.permissions&&navigator.permissions.query){const baseNote=support.textContent;navigator.permissions.query({name:"microphone"}).then(p=>{const show=()=>{support.textContent=baseNote+" Microphone permission: "+p.state+".";};show();p.onchange=show;}).catch(()=>{});}const sub=document.getElementById("orbSub");if(sub)sub.dataset.base=sub.textContent;if(document.querySelector(".card.error"))setOrbState("error","Error");if(document.querySelector(".card.final"))document.body.classList.add("completed");const errCard=document.getElementById("errorCard");if(errCard)errCard.focus({preventScroll:true});const shouldSpeak=localStorage.getItem("htwSpeakAfterLoad")==="1";localStorage.removeItem("htwSpeakAfterLoad");if(shouldSpeak&&handsFree)setTimeout(speakCurrent,350);});
</script>
</body>
</html>
"""


MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}


def _require_image_mime(data):
    """Return the image MIME type for recognized content, else raise ValueError."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"BM"):
        return "image/bmp"
    raise ValueError("Photo content is not a recognized image.")


def image_to_data_url(upload):
    if not upload or not upload.filename:
        return None
    filename = upload.filename or ""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Photo must be a PNG, JPEG, GIF, WebP, or BMP image.")
    data = upload.read()
    if not data:
        return None
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Please use an image smaller than 8 MB for the demo.")
    mime = _require_image_mime(data)
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _friendly_error(exc):
    """Browser-safe message: config guidance shown, API payloads withheld."""
    text = str(exc)
    if "API key" in text or "_API_KEY" in text or "HTW_PROVIDER" in text:
        return text
    if isinstance(exc, ProviderError):
        return "The diagnostic service had trouble reaching the model. The session is preserved; try again."
    if isinstance(exc, Rejected):
        return f"Evidence rejected: {exc}"
    return text


def _record_error(exc):
    """Full detail goes to the server console only; browser gets safe text."""
    print(f"[phone_app] {type(exc).__name__}: {exc}", flush=True)
    STATE["error"] = _friendly_error(exc)


def _append_entry(kind, glyph, title, detail, record=None):
    """Append one timeline entry to memory and to durable history."""
    STATE["timeline"].append(
        {"glyph": glyph, "kind": kind, "title": title, "detail": detail, "record": record})
    hid = STATE["history_session_id"]
    if hid is not None:
        get_store().record_event(hid, kind, glyph, title, detail, record)


def _record_timeline(before, after, user_text=None):
    """Append factual entries derived from real snapshot diffs.

    `before` is None only for a fresh session start. Every entry quotes a
    real record id, user input, or model action; nothing is invented.
    """
    if user_text is not None:
        _append_entry("user", "◉", "You reported", user_text)
    old_evidence = {item.id for item in before.evidence} if before is not None else set()
    old_status = {item.id: item.status for item in before.hypotheses} if before is not None else {}
    if before is None:
        _append_entry("session", "●", "Session started", after.problem)
    else:
        for item in after.evidence:
            if item.id not in old_evidence:
                _append_entry("evidence", "▣", f"Evidence recorded ({item.id})", item.statement, item.id)
    for hypo in after.hypotheses:
        if hypo.id not in old_status:
            _append_entry("hypothesis", "◇", f"New cause considered ({hypo.id})", hypo.cause, hypo.id)
        elif hypo.status != old_status[hypo.id]:
            _append_entry("update", "↻", f"Cause {hypo.id} is now {hypo.status}",
                          hypo.rationale or hypo.cause, hypo.id)
    upcoming = after.next_action
    if upcoming is not None and (
        before is None or before.next_action is None or before.next_action.id != upcoming.id
    ):
        _append_entry("test", "▷", "Test requested", upcoming.action, upcoming.id)
    if after.recommendation is not None and (before is None or before.recommendation is None):
        _append_entry("recommendation", "✓", "Verified recommendation",
                      after.recommendation.action, after.recommendation.hypothesis_id)
    if after.inconclusive is not None and (
        before is None or before.inconclusive != after.inconclusive
    ):
        _append_entry("handoff", "⚐", "Inconclusive handoff",
                      after.inconclusive.summary)
    del STATE["timeline"][:-TIMELINE_LIMIT]


def _record_photo_event(record_id):
    """Note that a photo informed one round. Image bytes are never stored."""
    _append_entry("photo", "◈", f"Photo attached ({record_id})",
                  "Shown to the model for this round; image bytes are not stored.", record_id)
    del STATE["timeline"][:-TIMELINE_LIMIT]


def _recent_entries():
    """Last two live timeline entries with 1-based positions for anchor links."""
    tail = STATE["timeline"][-2:]
    start = len(STATE["timeline"]) - len(tail) + 1
    return [(start + index, entry) for index, entry in enumerate(tail)]


def _park_active():
    """Stash the live view into the case registry; the case stays open."""
    hid = STATE["history_session_id"]
    if hid is None:
        return
    STATE["cases"][hid] = {
        "loop": STATE["loop"], "provider": STATE["provider"],
        "provider_label": STATE["provider_label"], "images": STATE["images"],
        "timeline": STATE["timeline"], "last_result": STATE["last_result"],
        "advance_note": STATE["advance_note"], "draft_answer": STATE["draft_answer"],
    }


def _load_case(hid):
    """Make a registered case the live view."""
    bundle = STATE["cases"][hid]
    STATE["loop"] = bundle["loop"]
    STATE["provider"] = bundle["provider"]
    STATE["provider_label"] = bundle["provider_label"]
    STATE["images"] = bundle["images"]
    STATE["timeline"] = bundle["timeline"]
    STATE["last_result"] = bundle["last_result"]
    STATE["advance_note"] = bundle["advance_note"]
    STATE["draft_answer"] = bundle["draft_answer"]
    STATE["draft_problem"] = ""
    STATE["error"] = None
    STATE["history_session_id"] = hid
    STATE["active_id"] = hid


def _clear_flats():
    STATE["loop"] = None
    STATE["last_result"] = None
    STATE["error"] = None
    STATE["provider"] = None
    STATE["provider_label"] = None
    STATE["images"] = {}
    STATE["advance_note"] = None
    STATE["timeline"] = []
    STATE["draft_problem"] = ""
    STATE["draft_answer"] = ""
    STATE["history_session_id"] = None
    STATE["active_id"] = None


def _checkpoint_bundle():
    result = STATE["last_result"]
    return {
        "version": CHECKPOINT_BUNDLE_VERSION,
        "session": STATE["loop"].session.to_checkpoint(),
        "loop": STATE["loop"].capture_bookkeeping(),
        "timeline": [dict(entry) for entry in STATE["timeline"]],
        "provider_label": STATE["provider_label"],
        "last_outcome": (
            None if result is None else {
                "outcome": result.outcome.value,
                "steps_used": result.steps_used,
                "message": result.message,
                "advance_steps": result.advance_steps,
            }
        ),
        "advance_note": STATE["advance_note"],
        "draft_answer": STATE["draft_answer"],
    }


def _save_case_checkpoint(hid):
    get_store().save_checkpoint(hid, _checkpoint_bundle())


def _sync_case_status(hid, result):
    """Mirror the AI outcome in the case row; never touch solved cases.

    Diagnostic states map explicitly; transient provider/advance/budget
    outcomes leave the current status alone so a retryable failure cannot
    erase an informative state like "awaiting result".
    """
    if result is None:
        return
    row = get_store().get_session(hid)
    if row is None or row["case_status"] == "solved":
        return
    status = {
        LoopOutcome.NEEDS_INPUT: "awaiting",
        LoopOutcome.INCONCLUSIVE: "inconclusive",
        LoopOutcome.COMPLETED: "open",
        LoopOutcome.PAUSED: "open",
    }.get(result.outcome)
    if status is None:
        return
    get_store().set_case_status(hid, status)


def _case_is_solved(hid):
    row = get_store().get_session(hid)
    return row is not None and row["case_status"] == "solved"


def _restore_timeline(entries):
    if not isinstance(entries, list):
        raise Rejected("Checkpoint timeline is invalid")
    restored = []
    for entry in entries:
        if (not isinstance(entry, dict)
                or any(not isinstance(entry.get(key), str)
                       for key in ("glyph", "kind", "title", "detail"))
                or (entry.get("record") is not None
                    and not isinstance(entry.get("record"), str))):
            raise Rejected("Checkpoint timeline is invalid")
        restored.append({
            "glyph": entry["glyph"], "kind": entry["kind"],
            "title": entry["title"], "detail": entry["detail"],
            "record": entry["record"],
        })
    return restored[-TIMELINE_LIMIT:]


def _restore_result(data, snapshot):
    if data is None:
        return None
    try:
        outcome = LoopOutcome(data["outcome"])
    except (KeyError, ValueError):
        raise Rejected("Checkpoint outcome is invalid") from None
    for key in ("steps_used", "advance_steps"):
        if type(data.get(key)) is not int or data[key] < 0:
            raise Rejected("Checkpoint outcome is invalid")
    if not isinstance(data.get("message"), str):
        raise Rejected("Checkpoint outcome is invalid")
    return LoopResult(outcome, snapshot, data["steps_used"], data["message"],
                      data["advance_steps"])


def _restore_case(hid):
    """Rebuild a parked case from its checkpoint. Returns an error or None."""
    store = get_store()
    row = store.get_session(hid)
    if row is None:
        return "Investigation not found."
    if row["archived"]:
        return "That investigation is archived and read-only."
    try:
        bundle = store.load_checkpoint(hid)
    except ValueError as exc:
        print(f"[phone_app] checkpoint undecodable for {hid}: {exc}", flush=True)
        return ("Saved state for that investigation failed validation; "
                "its history is preserved read-only.")
    if bundle is None:
        return ("No restorable state for that investigation; "
                "its history is preserved read-only.")
    try:
        if not isinstance(bundle, dict) or bundle.get("version") != CHECKPOINT_BUNDLE_VERSION:
            raise Rejected("Checkpoint bundle version is invalid")
        session = DiagnosticSession.from_checkpoint(bundle["session"])
        provider, label = create_provider(None)
        loop = AgentLoop(
            session, provider,
            max_provider_steps=SESSION_STEP_BUDGET,
            max_advance_steps=ADVANCE_STEP_BUDGET,
        )
        loop.apply_bookkeeping(bundle["loop"])
        timeline = _restore_timeline(bundle["timeline"])
        last_result = _restore_result(bundle["last_outcome"], session.snapshot)
        advance_note = bundle["advance_note"]
        draft_answer = bundle["draft_answer"]
        provider_label = bundle["provider_label"]
        if advance_note is not None and not isinstance(advance_note, str):
            raise Rejected("Checkpoint note is invalid")
        if not isinstance(draft_answer, str) or not isinstance(provider_label, str):
            raise Rejected("Checkpoint view state is invalid")
    except ProviderError as exc:
        print(f"[phone_app] restore needs provider: {exc}", flush=True)
        return _friendly_error(exc)
    except (Rejected, ValueError, KeyError, TypeError) as exc:
        print(f"[phone_app] restore rejected for {hid}: {exc}", flush=True)
        return ("Saved state for that investigation failed validation; "
                "its history is preserved read-only.")
    store.adopt_session(hid)
    STATE["cases"][hid] = {
        "loop": loop, "provider": provider, "provider_label": provider_label,
        "images": {}, "timeline": timeline, "last_result": last_result,
        "advance_note": advance_note, "draft_answer": draft_answer,
    }
    _load_case(hid)
    _append_entry("session", "●", "Case resumed", "Restored from the saved checkpoint.")
    return None


def _live_case(hid):
    """Park the current view and ensure hid is live. Returns an error or None."""
    _park_active()
    parked = STATE["cases"].get(hid)
    if parked is not None and parked["loop"] is not None:
        _load_case(hid)
        return None
    return _restore_case(hid)


def _restore_previous_or_clear(previous):
    if previous is not None and previous in STATE["cases"]:
        _load_case(previous)
    else:
        STATE["loop"] = None
        STATE["last_result"] = None


def current_context():
    loop = STATE["loop"]
    hid = STATE["history_session_id"]
    row = get_store().get_session(hid) if hid is not None else None
    return {"session": loop.session.snapshot if loop else None, "result": STATE["last_result"], "error": STATE["error"], "provider_label": STATE["provider_label"], "advance_note": STATE["advance_note"], "timeline": STATE["timeline"], "draft_problem": STATE["draft_problem"], "draft_answer": STATE["draft_answer"], "sessions": get_store().list_sessions(), "viewing": None, "recents": _recent_entries(), "active_id": hid, "case_status": row["case_status"] if row else None, "solved_note": row["solved_note"] if row else ""}


@app.get("/")
def index():
    return render_template_string(PAGE, **current_context())


def _outcome_error(result):
    """Browser-safe message for terminal loop outcomes; None when on track."""
    if result is None:
        return None
    if result.outcome in (LoopOutcome.NEEDS_INPUT, LoopOutcome.COMPLETED,
                          LoopOutcome.INCONCLUSIVE):
        return None
    if result.outcome is LoopOutcome.PAUSED:
        return f"Diagnosis paused ({result.session.pause_reason}). Start a new investigation to continue."
    if result.outcome is LoopOutcome.PROVIDER_ERROR:
        return "The diagnostic service had trouble reaching the model. You can try again."
    if result.outcome is LoopOutcome.ADVANCE_EXHAUSTED:
        return "The assistant paused mid-investigation. You can try again to continue."
    return "The session used its full step budget. Start a new investigation to continue."


@app.post("/start")
def start():
    STATE["error"] = None
    problem = (request.form.get("problem") or "").strip()
    if not problem:
        STATE["error"] = "Describe the device problem first."
        return redirect(url_for("index"))
    previous = STATE["history_session_id"]
    created = None
    try:
        _park_active()
        image_data_url = image_to_data_url(request.files.get("image"))
        session = DiagnosticSession(problem, max_turns=30, max_completion_attempts=3)
        initial = session.execute("record_evidence", {"source": "user_text", "statement": problem, "provenance": {"channel": "phone_ui", "kind": "initial_problem"}})
        provider, label = create_provider(image_data_url)
        loop = AgentLoop(
            session, provider,
            max_provider_steps=SESSION_STEP_BUDGET,
            max_advance_steps=ADVANCE_STEP_BUDGET,
        )
        STATE["loop"] = loop
        STATE["advance_note"] = None
        STATE["timeline"] = []
        STATE["draft_problem"] = ""
        hid = loop.session.snapshot.id
        count = len(get_store().list_sessions()) + 1
        get_store().create_session(hid, f"Investigation {count} — {problem[:36]}", problem)
        created = hid
        STATE["history_session_id"] = hid
        STATE["active_id"] = hid
        STATE["provider"] = provider
        STATE["provider_label"] = label
        STATE["images"] = {initial.record_id: image_data_url} if image_data_url else {}
        STATE["last_result"] = loop.run()
        STATE["error"] = _outcome_error(STATE["last_result"])
        _record_timeline(None, loop.session.snapshot)
        if image_data_url:
            _record_photo_event(initial.record_id)
        _park_active()
        _save_case_checkpoint(hid)
        _sync_case_status(hid, STATE["last_result"])
    except (ValueError, Rejected, ProviderError) as exc:
        if created is not None:
            get_store().delete_session(created)
            created = None
        _restore_previous_or_clear(previous)
        _record_error(exc)
        STATE["draft_problem"] = problem
    except Exception:  # noqa: BLE001 - demo surface reports failures inline
        if created is not None:
            get_store().delete_session(created)
        _restore_previous_or_clear(previous)
        STATE["draft_problem"] = problem
        STATE["error"] = "Unexpected failure starting the session. Please try again."
    return redirect(url_for("index"))


@app.post("/resume")
def resume():
    STATE["error"] = None
    loop = STATE["loop"]
    if loop is None:
        return redirect(url_for("index"))
    if request.form.get("case_id") != STATE["history_session_id"]:
        STATE["error"] = "That submission belongs to a different case; nothing was changed."
        return redirect(url_for("index"))
    if _case_is_solved(STATE["history_session_id"]):
        STATE["error"] = "That case is solved; reopen it to continue."
        return redirect(url_for("index"))
    answer = (request.form.get("answer") or "").strip()
    if not answer:
        STATE["error"] = "Report what you observed before continuing."
        return redirect(url_for("index"))
    before = loop.session.snapshot
    try:
        image_data_url = image_to_data_url(request.files.get("image"))
        ingested = loop.resume_with_result(answer, {"channel": "phone_ui", "kind": "diagnostic_observation"})
        if image_data_url:
            STATE["images"][ingested.record_id] = image_data_url
            if STATE["provider"] is not None:
                STATE["provider"].set_image(image_data_url)
        STATE["last_result"] = loop.run()
        STATE["error"] = _outcome_error(STATE["last_result"])
        advanced = STATE["last_result"]
        STATE["advance_note"] = (
            f"New evidence recorded ({ingested.record_id}) → reassessed "
            f"({advanced.advance_steps} steps this round, "
            f"{advanced.steps_used} total)."
        )
        STATE["draft_answer"] = ""
        _record_timeline(before, loop.session.snapshot, user_text=answer)
        if image_data_url:
            _record_photo_event(ingested.record_id)
        hid = STATE["history_session_id"]
        _park_active()
        _save_case_checkpoint(hid)
        _sync_case_status(hid, STATE["last_result"])
    except (ValueError, Rejected, ProviderError) as exc:
        _record_error(exc)
        STATE["draft_answer"] = answer
    except Exception:  # noqa: BLE001 - demo surface reports failures inline
        STATE["loop"] = None
        STATE["last_result"] = None
        STATE["error"] = "Unexpected failure while resuming. Please restart the diagnosis."
    return redirect(url_for("index"))


@app.post("/retry")
def retry():
    STATE["error"] = None
    loop = STATE["loop"]
    if loop is None:
        return redirect(url_for("index"))
    if request.form.get("case_id") != STATE["history_session_id"]:
        STATE["error"] = "That submission belongs to a different case; nothing was changed."
        return redirect(url_for("index"))
    if _case_is_solved(STATE["history_session_id"]):
        STATE["error"] = "That case is solved; reopen it to continue."
        return redirect(url_for("index"))
    before = loop.session.snapshot
    try:
        # Same loop: feedback and session-wide spend carry over, so a retry
        # grants one fresh advance instead of unlimited billed steps.
        STATE["last_result"] = loop.run()
        STATE["error"] = _outcome_error(STATE["last_result"])
        STATE["advance_note"] = None
        _record_timeline(before, loop.session.snapshot)
        hid = STATE["history_session_id"]
        _park_active()
        _save_case_checkpoint(hid)
        _sync_case_status(hid, STATE["last_result"])
    except (ValueError, Rejected, ProviderError) as exc:
        _record_error(exc)
    except Exception:  # noqa: BLE001 - demo surface reports failures inline
        STATE["loop"] = None
        STATE["last_result"] = None
        STATE["error"] = "Unexpected failure while retrying. Please restart the diagnosis."
    return redirect(url_for("index"))


@app.post("/reset")
def reset():
    _park_active()
    _clear_flats()
    return redirect(url_for("index"))


@app.post("/case/<hid>/switch")
def switch_case(hid):
    STATE["error"] = None
    if hid == STATE["history_session_id"] and STATE["loop"] is not None:
        return redirect(url_for("index"))
    previous = STATE["history_session_id"]
    failure = _live_case(hid)
    if failure is not None:
        _restore_previous_or_clear(previous)
        STATE["error"] = failure
        return redirect(url_for("view_history", session_id=hid))
    return redirect(url_for("index"))


@app.post("/case/<hid>/solve")
def solve_case(hid):
    STATE["error"] = None
    row = get_store().get_session(hid)
    if row is None or row["archived"]:
        STATE["error"] = "Investigation not found."
        return redirect(url_for("index"))
    if row["case_status"] == "solved":
        return redirect(url_for("index"))
    previous = STATE["history_session_id"]
    if hid != previous or STATE["loop"] is None:
        failure = _live_case(hid)
        if failure is not None:
            _restore_previous_or_clear(previous)
            STATE["error"] = failure
            return redirect(url_for("view_history", session_id=hid))
    note = (request.form.get("note") or "").strip()
    get_store().set_case_status(hid, "solved", note)
    _append_entry("case", "●", "Marked solved",
                  note or "Technician marked this case solved.")
    _park_active()
    _save_case_checkpoint(hid)
    return redirect(url_for("index"))


@app.post("/case/<hid>/reopen")
def reopen_case(hid):
    STATE["error"] = None
    row = get_store().get_session(hid)
    if row is None or row["archived"]:
        STATE["error"] = "Investigation not found."
        return redirect(url_for("index"))
    previous = STATE["history_session_id"]
    if hid != previous or STATE["loop"] is None:
        failure = _live_case(hid)
        if failure is not None:
            _restore_previous_or_clear(previous)
            STATE["error"] = failure
            return redirect(url_for("view_history", session_id=hid))
    note = (request.form.get("note") or "").strip() or "Technician reopened the case."
    loop = STATE["loop"]
    try:
        before = loop.session.snapshot
        if before.status in (S.COMPLETED, S.INCONCLUSIVE):
            loop.session.execute("reopen_investigation", {"reason": note})
            _append_entry("case", "○", "Case reopened", note)
            get_store().set_case_status(hid, "open")
            _park_active()
            _save_case_checkpoint(hid)
            mid = loop.session.snapshot
            try:
                STATE["last_result"] = loop.run()
            except Exception as exc:  # noqa: BLE001 - reopen already persisted
                print(f"[phone_app] reopen run failed for {hid}: {exc}", flush=True)
                STATE["last_result"] = None
                STATE["error"] = (
                    "The case was reopened, but continuing failed. Please try again.")
                _park_active()
                _save_case_checkpoint(hid)
                return redirect(url_for("index"))
            STATE["error"] = _outcome_error(STATE["last_result"])
            _record_timeline(mid, loop.session.snapshot)
        else:
            _append_entry("case", "○", "Case reopened", note)
        get_store().set_case_status(hid, "open")
        _sync_case_status(hid, STATE["last_result"])
        _park_active()
        _save_case_checkpoint(hid)
    except (ValueError, Rejected, ProviderError) as exc:
        _record_error(exc)
    except Exception:  # noqa: BLE001 - demo surface reports failures inline
        STATE["error"] = "Unexpected failure while reopening. Please try again."
    return redirect(url_for("index"))


@app.get("/history/<session_id>")
def view_history(session_id):
    session = get_store().get_session(session_id)
    if session is None:
        STATE["error"] = "Investigation not found."
        return redirect(url_for("index"))
    context = current_context()
    context["viewing"] = {
        "session": session, "events": get_store().get_events(session_id)}
    try:
        checkpoint = get_store().load_checkpoint(session_id)
    except ValueError:
        checkpoint = "corrupt"
    context["can_resume"] = not session["archived"] and checkpoint not in (None, "corrupt")
    return render_template_string(PAGE, **context)


@app.post("/history/<session_id>/rename")
def rename_history(session_id):
    if get_store().get_session(session_id) is None:
        STATE["error"] = "Investigation not found."
        return redirect(url_for("index"))
    name = (request.form.get("name") or "").strip()
    if not name:
        STATE["error"] = "Session name must not be empty."
        return redirect(url_for("view_history", session_id=session_id))
    try:
        get_store().rename_session(session_id, name)
    except ValueError as exc:
        STATE["error"] = str(exc)
        return redirect(url_for("view_history", session_id=session_id))
    STATE["error"] = None
    return redirect(url_for("view_history", session_id=session_id))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    host = (os.environ.get("HTW_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    app.run(host=host, port=port, debug=False)
