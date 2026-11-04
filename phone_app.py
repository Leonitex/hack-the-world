"""Phone-first demo UI for Hack the World."""

from __future__ import annotations

import base64
import os

from flask import Flask, redirect, render_template_string, request, url_for

from agent.factory import create_provider
from agent.loop import AgentLoop, LoopOutcome
from agent.providers import ProviderError
from diagnostic_core.engine import DiagnosticSession
from diagnostic_core.models import Rejected

app = Flask(__name__)

STATE = {"loop": None, "last_result": None, "error": None, "provider": None,
         "provider_label": None, "images": {}}

PAGE = r"""
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#070b11">
<title>Hack the World</title>
<style>
:root { font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color-scheme: dark; --bg:#070b11; --panel:#0d141e; --line:#223247; --text:#eef5ff; --muted:#8fa2b8; --accent:#66d9ff; --accent2:#8b7cff; --good:#6fe7b0; }
* { box-sizing:border-box; }
body { margin:0; min-height:100vh; background:radial-gradient(circle at 50% -20%, rgba(83,116,255,.18), transparent 38%), radial-gradient(circle at 50% 30%, rgba(69,208,255,.06), transparent 32%), var(--bg); color:var(--text); }
main { max-width:760px; margin:auto; padding:18px 16px 52px; }
header { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:12px; }
.brand { font-weight:900; letter-spacing:.2px; font-size:20px; }
.meta { font-size:12px; color:#b8c8da; border:1px solid #29415b; background:#0c1520; border-radius:999px; padding:7px 10px; white-space:nowrap; }
.hero { text-align:center; padding:14px 0 4px; }
.orb-wrap { width:230px; height:230px; margin:0 auto 4px; position:relative; display:grid; place-items:center; }
.orb-halo,.orb-ring,.orb-core,.orb-scan { position:absolute; border-radius:50%; }
.orb-halo { width:208px; height:208px; background:radial-gradient(circle, rgba(102,217,255,.14), rgba(139,124,255,.04) 52%, transparent 70%); filter:blur(2px); animation:breathe 3.2s ease-in-out infinite; }
.orb-ring { width:158px; height:158px; border:1px solid rgba(130,217,255,.34); box-shadow:0 0 26px rgba(102,217,255,.13), inset 0 0 22px rgba(139,124,255,.08); }
.orb-ring::before,.orb-ring::after { content:""; position:absolute; inset:-13px; border-radius:50%; border:2px solid transparent; border-top-color:rgba(102,217,255,.72); border-right-color:rgba(139,124,255,.34); animation:spin 5s linear infinite; }
.orb-ring::after { inset:9px; animation-duration:3.3s; animation-direction:reverse; opacity:.65; }
.orb-core { width:104px; height:104px; background:radial-gradient(circle at 35% 30%, #d9f7ff 0%, #70dcff 13%, #4f79e8 43%, #1d2550 72%, #10172a 100%); box-shadow:0 0 25px rgba(102,217,255,.35), 0 0 65px rgba(83,97,255,.2); transition:.25s ease; }
.orb-core::after { content:""; position:absolute; inset:18px; border-radius:50%; background:radial-gradient(circle at 40% 35%, rgba(255,255,255,.6), rgba(255,255,255,.08) 35%, transparent 65%); }
.orb-scan { width:184px; height:184px; border:1px solid rgba(102,217,255,.1); }
.orb-scan::before { content:""; position:absolute; left:50%; top:50%; width:4px; height:4px; border-radius:50%; background:var(--accent); box-shadow:0 0 14px var(--accent); transform-origin:-78px 0; animation:orbit 4s linear infinite; }
.orb-label { position:absolute; bottom:8px; left:0; right:0; font-size:12px; letter-spacing:1.5px; text-transform:uppercase; color:#88a7c0; }
body.listening .orb-ring::before { animation-duration:.8s; border-top-color:var(--good); }
body.listening .orb-core { transform:scale(1.08); box-shadow:0 0 35px rgba(111,231,176,.5), 0 0 80px rgba(102,217,255,.24); }
body.thinking .orb-ring::before { animation-duration:.7s; border-top-color:var(--accent); border-right-color:var(--accent2); }
body.thinking .orb-ring::after { animation-duration:1.1s; }
body.thinking .orb-core { animation:thinkPulse 1.1s ease-in-out infinite; }
body.speaking .orb-core { animation:speakPulse .65s ease-in-out infinite alternate; }
body.speaking .orb-ring::after { border-top-color:var(--good); animation-duration:1.2s; }
body.error .orb-ring::before { border-top-color:var(--bad); animation-duration:.5s; }
body.error .orb-core { box-shadow:0 0 35px rgba(255,90,110,.5),0 0 80px rgba(255,90,110,.2); }
@keyframes spin { to { transform:rotate(360deg); } }
@keyframes orbit { from { transform:rotate(0deg) translateX(78px); } to { transform:rotate(360deg) translateX(78px); } }
@keyframes breathe { 50% { transform:scale(1.08); opacity:.7; } }
@keyframes thinkPulse { 50% { transform:scale(.92); filter:brightness(1.25); } }
@keyframes speakPulse { from { transform:scale(.96); } to { transform:scale(1.08); } }
.bubble { position:relative; max-width:610px; margin:0 auto 14px; text-align:left; background:linear-gradient(180deg, rgba(18,29,43,.94), rgba(12,20,31,.94)); border:1px solid #263b53; border-radius:20px; padding:15px 16px; box-shadow:0 14px 50px rgba(0,0,0,.22); }
.bubble .state { color:var(--accent); font-size:12px; font-weight:800; letter-spacing:.8px; text-transform:uppercase; margin-bottom:6px; }
.bubble .message { font-size:17px; line-height:1.42; }
.controls { display:grid; grid-template-columns:1fr 1fr; gap:10px; max-width:610px; margin:0 auto 16px; }
button { appearance:none; border:0; cursor:pointer; border-radius:14px; min-height:48px; padding:12px 14px; font-weight:800; font-size:15px; background:linear-gradient(135deg, #d8f5ff, #bbcbff); color:#0a1018; }
button.secondary { background:#121d2a; color:#dce9f7; border:1px solid #2a4058; }
button.mic-active { background:linear-gradient(135deg, #c7ffe5, #a6e9ff); }
.card { background:rgba(13,20,30,.93); border:1px solid var(--line); border-radius:18px; padding:16px; margin:13px 0; }
.card h2,.card h3 { margin:0 0 12px; }
label { display:block; margin:10px 0 6px; font-weight:750; }
textarea,input[type=file] { width:100%; }
textarea { min-height:96px; resize:vertical; border-radius:13px; padding:12px; background:#09111a; color:#fff; border:1px solid #2b3e52; font:inherit; }
.filebox { border:1px dashed #36516d; border-radius:13px; padding:12px; background:#0a131d; }
.badges { display:flex; flex-wrap:wrap; gap:7px; margin:4px 0 10px; }
.badge { display:inline-flex; padding:5px 9px; border:1px solid #334a63; border-radius:999px; color:#bed0e2; font-size:12px; }
.progress { display:grid; grid-template-columns:repeat(5,1fr); gap:6px; margin:9px 0 2px; }
.step { text-align:center; font-size:11px; color:#71859a; padding-top:8px; border-top:2px solid #1f3042; }
.step.active { color:#d9f5ff; border-color:var(--accent); }
.step.done { color:#a8d8c3; border-color:var(--good); }
.evidence-grid { display:flex; flex-wrap:wrap; gap:8px; }
.evidence-chip { border:1px solid #2c435b; background:#0a141f; border-radius:12px; padding:8px 10px; font-size:13px; }
.hypothesis { border-left:3px solid #486784; padding:7px 0 7px 11px; margin:10px 0; }
.hypothesis strong { display:block; line-height:1.3; }
.muted,small { color:var(--muted); }
.error { border-color:#753d47; background:#211116; }
.next { border-color:#365b79; background:linear-gradient(180deg,#101c29,#0d1621); }
.final { border-color:#39715f; background:linear-gradient(180deg,#10231d,#0d1916); }
details summary { cursor:pointer; font-weight:800; color:#c9d9e8; }
details[open] summary { margin-bottom:12px; }
.voice-note { font-size:12px; color:#7f94aa; text-align:center; margin-top:-5px; }
.fab { position:fixed; right:18px; bottom:18px; width:58px; height:58px; border-radius:50%; padding:0; display:grid; place-items:center; font-size:23px; box-shadow:0 12px 32px rgba(0,0,0,.4); }
@media (max-width:520px) { main { padding-left:14px; padding-right:14px; } .orb-wrap { width:210px; height:210px; } .controls { grid-template-columns:1fr; } .progress { gap:3px; } .step { font-size:9px; } }
@media (min-width:900px) { main { max-width:860px; } .orb-wrap { width:250px; height:250px; } }
@media (prefers-reduced-motion:reduce) { .orb-halo,.orb-ring::before,.orb-ring::after,.orb-scan::before,.orb-core { animation:none !important; } }
</style>
</head>
<body class="idle">
<main>
<header><div class="brand">Hack the World</div><div class="meta">{{ provider_label or "Meta Muse" }}</div></header>
<section class="hero">
<div class="orb-wrap" aria-label="Assistant status"><div class="orb-halo"></div><div class="orb-scan"></div><div class="orb-ring"></div><div class="orb-core"></div><div class="orb-label" id="orbLabel">Ready</div></div>
<div class="bubble" id="assistantBubble" aria-live="polite"><div class="state" id="assistantState">{% if error %}Attention{% elif session and session.recommendation %}Verified{% elif session and session.next_action %}Next diagnostic step{% elif session %}Investigating{% else %}Ready{% endif %}</div><div class="message" id="assistantMessage">{% if error %}{{ error }}{% elif session and session.recommendation %}{{ session.recommendation.action }}{% elif session and session.next_action %}{{ session.next_action.action }}{% elif session %}I am reviewing the evidence and testing competing causes.{% else %}Tell me what the device is doing. You can speak, type, or add a photo.{% endif %}</div></div>
<div class="controls"><button type="button" class="secondary" id="speakButton" onclick="speakCurrent()">🔊 Hear instruction</button><button type="button" class="secondary" id="handsFreeButton" onclick="toggleHandsFree()">🎙 Hands-free: off</button></div>
<div class="voice-note" id="voiceSupport" role="status"></div>
</section>
{% if error %}<div class="card error"><strong>Something needs attention</strong><div>{{ error }}</div></div>{% endif %}
{% if result and (result.outcome.value == "provider_error" or result.outcome.value == "budget_exhausted") %}<form method="post" action="{{ url_for('retry') }}"><button type="submit" class="secondary" style="width:100%">Try again</button></form>{% endif %}
{% if not session %}
<div class="card"><form id="startForm" method="post" action="{{ url_for('start') }}" enctype="multipart/form-data"><label>Describe the problem</label><textarea id="problemInput" name="problem" required placeholder="Example: Laptop powers on, fan spins, but the screen stays black."></textarea><div class="controls" style="margin:10px 0 4px"><button type="button" class="secondary" onclick="startDictation('problemInput', this)">🎙 Speak symptoms</button><button type="button" class="secondary" onclick="document.getElementById('imageInput').click()">📷 Add photo</button></div><div class="filebox"><input id="imageInput" type="file" name="image" accept="image/*" capture="environment"><small>A clear device photo is optional, but makes the demo visibly multimodal.</small></div><button type="submit" style="width:100%;margin-top:12px">Begin investigation</button></form></div>
{% else %}
<div class="card"><div class="badges"><span class="badge">{{ session.status }}</span><span class="badge">{{ session.turn_count }} diagnostic turns</span><span class="badge">{{ result.steps_used if result else 0 }} Muse steps</span></div><div class="progress"><div class="step done">Observe</div><div class="step {% if session.hypotheses %}done{% else %}active{% endif %}">Hypothesize</div><div class="step {% if session.next_action %}active{% elif session.recommendation %}done{% endif %}">Test</div><div class="step {% if session.recommendation %}done{% elif session.hypotheses and not session.next_action %}active{% endif %}">Verify</div><div class="step {% if session.recommendation %}active{% endif %}">Fix</div></div><h3 style="margin-top:16px">Device problem</h3><div>{{ session.problem }}</div></div>
{% if session.next_action %}<div class="card next"><h2>Do this next</h2><p style="font-size:18px;line-height:1.45"><strong>{{ session.next_action.action }}</strong></p>{% if session.next_action.observations %}<div class="muted">Report:</div><ul>{% for o in session.next_action.observations %}<li>{{ o }}</li>{% endfor %}</ul>{% endif %}<form id="resumeForm" method="post" action="{{ url_for('resume') }}" enctype="multipart/form-data"><label>What happened?</label><textarea id="answerInput" name="answer" required placeholder="Tell me exactly what you observed."></textarea><div class="filebox" style="margin-top:10px"><input id="answerImageInput" type="file" name="image" accept="image/*" capture="environment"><small>Optional follow-up photo of what you observed.</small></div><div class="controls" style="margin:10px 0 0"><button type="button" id="answerMic" class="secondary" onclick="startDictation('answerInput', this)">🎙 Speak result</button><button type="submit">Submit & continue</button></div></form></div>{% endif %}
{% if session.recommendation %}<div class="card final"><h2>✓ Verified recommendation</h2><p style="font-size:18px;line-height:1.45">{{ session.recommendation.action }}</p><small>Grounded in {{ session.recommendation.evidence_ids|length }} recorded evidence item(s).</small></div>{% endif %}
<details class="card"><summary>Evidence & technical details</summary><h3>Evidence</h3>{% if session.evidence %}<div class="evidence-grid">{% for e in session.evidence %}<details class="evidence-chip"><summary><strong>{{ e.id.split(':')[-1] }}</strong> · {{ e.statement }}</summary><div class="muted">Source: {{ e.source }}</div>{% for pair in e.provenance %}<div class="muted">{{ pair[0] }}: {{ pair[1] }}</div>{% endfor %}</details>{% endfor %}</div>{% else %}<div class="muted">No evidence recorded yet.</div>{% endif %}<h3 style="margin-top:18px">Competing hypotheses</h3>{% if session.hypotheses %}{% for h in session.hypotheses %}<div class="hypothesis"><strong>{{ h.cause }}</strong><div class="badges"><span class="badge">{{ h.status }}</span></div>{% if h.rationale %}<small>{{ h.rationale }}</small>{% endif %}</div>{% endfor %}{% else %}<div class="muted">No cause proposed yet.</div>{% endif %}</details>
<form method="post" action="{{ url_for('reset') }}"><button type="submit" class="secondary" style="width:100%">Start a new investigation</button></form>
{% endif %}
</main>
<button type="button" class="fab" id="floatingMic" onclick="floatingMic()" title="Voice input" aria-label="Voice input">🎙</button>
<script>
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let activeRecognition = null;
let handsFree = localStorage.getItem("htwHandsFree") === "1";
function setOrbState(state,label,bubbleText){document.body.classList.remove("idle","listening","thinking","speaking","error");document.body.classList.add(state);document.getElementById("orbLabel").textContent=label||state;if(bubbleText)document.getElementById("assistantMessage").textContent=bubbleText;}
function updateHandsFreeButton(){const btn=document.getElementById("handsFreeButton");if(btn)btn.textContent=handsFree?"🎙 Hands-free: on":"🎙 Hands-free: off";}
function toggleHandsFree(){handsFree=!handsFree;localStorage.setItem("htwHandsFree",handsFree?"1":"0");updateHandsFreeButton();if(handsFree)speakCurrent();else window.speechSynthesis?.cancel();}
function chooseProfessionalVoice(){const voices=window.speechSynthesis?window.speechSynthesis.getVoices():[];return voices.find(v=>/Google UK English Male|Microsoft.*(David|Ryan|George)/i.test(v.name))||voices.find(v=>/^en-GB/i.test(v.lang))||voices.find(v=>/^en-US/i.test(v.lang))||voices[0];}
function speak(text){if(!("speechSynthesis" in window)||!text)return;window.speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(text);const voice=chooseProfessionalVoice();if(voice)u.voice=voice;u.rate=.94;u.pitch=.92;u.volume=1;u.onstart=()=>setOrbState("speaking","Speaking");u.onend=()=>setOrbState("idle","Ready");u.onerror=()=>{setOrbState("error","Error","Spoken instructions hit a playback problem.");setTimeout(()=>{if(document.body.classList.contains("error"))setOrbState("idle","Ready");},4000);};window.speechSynthesis.speak(u);}
function speakCurrent(){const text=document.getElementById("assistantMessage")?.innerText?.trim();speak(text);}
function startDictation(targetId,button){const target=document.getElementById(targetId);if(!target)return;if(!SpeechRecognition){document.getElementById("voiceSupport").textContent="Voice recognition is not available in this browser. You can still type and use spoken instructions.";return;}if(activeRecognition){try{activeRecognition.stop();}catch(_){}}const recognition=new SpeechRecognition();activeRecognition=recognition;recognition.lang="en-US";recognition.interimResults=true;recognition.continuous=false;const original=target.value.trim();let finalText="";recognition.onstart=()=>{setOrbState("listening","Listening","Listening. Tell me exactly what you observe.");if(button)button.classList.add("mic-active");};recognition.onresult=(event)=>{let interim="";finalText="";for(let i=event.resultIndex;i<event.results.length;i++){const chunk=event.results[i][0].transcript;if(event.results[i].isFinal)finalText+=chunk;else interim+=chunk;}const spoken=(finalText||interim).trim();target.value=[original,spoken].filter(Boolean).join(original&&spoken?" ":"");};recognition.onerror=(event)=>{setOrbState("error","Error","I couldn't hear that clearly. You can try again or type the result.");setTimeout(()=>{if(document.body.classList.contains("error"))setOrbState("idle","Ready");},4000);document.getElementById("voiceSupport").textContent="Microphone: "+event.error;};recognition.onend=()=>{activeRecognition=null;if(button)button.classList.remove("mic-active");if(!document.body.classList.contains("error"))setOrbState("idle","Ready");};recognition.start();}
function floatingMic(){const answer=document.getElementById("answerInput");const problem=document.getElementById("problemInput");if(answer)startDictation("answerInput",document.getElementById("floatingMic"));else if(problem)startDictation("problemInput",document.getElementById("floatingMic"));else speakCurrent();}
for(const form of document.querySelectorAll("form")){form.addEventListener("submit",()=>{if(form.id==="startForm"||form.id==="resumeForm"){localStorage.setItem("htwSpeakAfterLoad",handsFree?"1":"0");setOrbState("thinking","Thinking","Analyzing the evidence and deciding the safest next diagnostic step.");}});}
document.addEventListener("DOMContentLoaded",()=>{updateHandsFreeButton();const support=document.getElementById("voiceSupport");support.textContent=SpeechRecognition?"Tap the microphone to speak; spoken instructions can continue hands-free.":"Spoken instructions are available. Voice input depends on browser support.";if(navigator.permissions&&navigator.permissions.query){const baseNote=support.textContent;navigator.permissions.query({name:"microphone"}).then(p=>{const show=()=>{support.textContent=baseNote+" Microphone permission: "+p.state+".";};show();p.onchange=show;}).catch(()=>{});}if(document.querySelector(".card.error"))setOrbState("error","Error");const shouldSpeak=localStorage.getItem("htwSpeakAfterLoad")==="1";localStorage.removeItem("htwSpeakAfterLoad");if(shouldSpeak&&handsFree)setTimeout(speakCurrent,350);});
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


def current_context():
    loop = STATE["loop"]
    return {"session": loop.session.snapshot if loop else None, "result": STATE["last_result"], "error": STATE["error"], "provider_label": STATE["provider_label"]}


@app.get("/")
def index():
    return render_template_string(PAGE, **current_context())


def _outcome_error(result):
    """Browser-safe message for terminal loop outcomes; None when on track."""
    if result is None:
        return None
    if result.outcome in (LoopOutcome.NEEDS_INPUT, LoopOutcome.COMPLETED):
        return None
    if result.outcome is LoopOutcome.PAUSED:
        return f"Diagnosis paused ({result.session.pause_reason}). Start a new investigation to continue."
    if result.outcome is LoopOutcome.PROVIDER_ERROR:
        return "The diagnostic service had trouble reaching the model. You can try again."
    return "The assistant ran out of steps. You can try again to continue."


@app.post("/start")
def start():
    STATE["error"] = None
    problem = (request.form.get("problem") or "").strip()
    if not problem:
        STATE["error"] = "Describe the device problem first."
        return redirect(url_for("index"))
    try:
        image_data_url = image_to_data_url(request.files.get("image"))
        session = DiagnosticSession(problem, max_turns=30, max_completion_attempts=3)
        initial = session.execute("record_evidence", {"source": "user_text", "statement": problem, "provenance": {"channel": "phone_ui", "kind": "initial_problem"}})
        provider, label = create_provider(image_data_url)
        loop = AgentLoop(session, provider, max_provider_steps=14)
        STATE["loop"] = loop
        STATE["provider"] = provider
        STATE["provider_label"] = label
        STATE["images"] = {initial.record_id: image_data_url} if image_data_url else {}
        STATE["last_result"] = loop.run()
        STATE["error"] = _outcome_error(STATE["last_result"])
    except (ValueError, Rejected, ProviderError) as exc:
        _record_error(exc)
        STATE["loop"] = None
        STATE["last_result"] = None
    except Exception:  # noqa: BLE001 - demo surface reports failures inline
        STATE["loop"] = None
        STATE["last_result"] = None
        STATE["error"] = "Unexpected failure starting the session. Please try again."
    return redirect(url_for("index"))


@app.post("/resume")
def resume():
    STATE["error"] = None
    loop = STATE["loop"]
    if loop is None:
        return redirect(url_for("index"))
    answer = (request.form.get("answer") or "").strip()
    if not answer:
        STATE["error"] = "Report what you observed before continuing."
        return redirect(url_for("index"))
    try:
        image_data_url = image_to_data_url(request.files.get("image"))
        result = loop.resume_with_result(answer, {"channel": "phone_ui", "kind": "diagnostic_observation"})
        if image_data_url:
            STATE["images"][result.record_id] = image_data_url
            if STATE["provider"] is not None:
                STATE["provider"].set_image(image_data_url)
        STATE["last_result"] = loop.run()
        STATE["error"] = _outcome_error(STATE["last_result"])
    except (ValueError, Rejected, ProviderError) as exc:
        _record_error(exc)
    except Exception:  # noqa: BLE001 - demo surface reports failures inline
        STATE["loop"] = None
        STATE["last_result"] = None
        STATE["error"] = "Unexpected failure while resuming. Please restart the diagnosis."
    return redirect(url_for("index"))


@app.post("/retry")
def retry():
    STATE["error"] = None
    loop = STATE["loop"]
    provider = STATE["provider"]
    if loop is None or provider is None:
        return redirect(url_for("index"))
    try:
        fresh = AgentLoop(loop.session, provider, max_provider_steps=14)
        STATE["loop"] = fresh
        STATE["last_result"] = fresh.run()
        STATE["error"] = _outcome_error(STATE["last_result"])
    except (ValueError, Rejected, ProviderError) as exc:
        _record_error(exc)
    except Exception:  # noqa: BLE001 - demo surface reports failures inline
        STATE["loop"] = None
        STATE["last_result"] = None
        STATE["error"] = "Unexpected failure while retrying. Please restart the diagnosis."
    return redirect(url_for("index"))


@app.post("/reset")
def reset():
    STATE["loop"] = None
    STATE["last_result"] = None
    STATE["error"] = None
    STATE["provider"] = None
    STATE["provider_label"] = None
    STATE["images"] = {}
    return redirect(url_for("index"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    host = (os.environ.get("HTW_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    app.run(host=host, port=port, debug=False)
