"""Phone-first demo UI for Hack the World."""

from __future__ import annotations

import base64
import mimetypes
import os

from flask import Flask, redirect, render_template_string, request, url_for

from agent.baseten import BasetenMuseProvider
from agent.loop import AgentLoop
from diagnostic_core.engine import DiagnosticSession
from diagnostic_core.models import Rejected

app = Flask(__name__)

STATE = {"loop": None, "last_result": None, "error": None}

PAGE = r"""
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hack the World</title>
<style>
:root { font-family: system-ui, sans-serif; color-scheme: dark; }
body { margin:0; background:#0b0f14; color:#e9eef5; }
main { max-width:760px; margin:auto; padding:18px; }
h1 { margin-bottom:4px; }
.sub { color:#9fb0c2; margin-top:0; }
.card { background:#131a22; border:1px solid #273342; border-radius:16px; padding:16px; margin:14px 0; }
label { display:block; margin:10px 0 5px; font-weight:650; }
textarea,input[type=file] { width:100%; box-sizing:border-box; }
textarea { min-height:100px; border-radius:10px; padding:10px; background:#0e141b; color:#fff; border:1px solid #344254; }
button { width:100%; padding:13px; border-radius:12px; border:0; font-weight:800; font-size:16px; background:#e8eef7; color:#10151b; margin-top:12px; }
.badge { display:inline-block; padding:5px 9px; border:1px solid #42536a; border-radius:999px; margin-right:6px; color:#c7d5e5; }
.item { border-left:3px solid #4b6078; padding-left:10px; margin:10px 0; }
small, .muted { color:#91a1b2; }
.error { border-color:#8e3f47; background:#241316; }
.action { border-color:#536f91; background:#101923; }
</style>
</head>
<body>
<main>
<h1>Hack the World</h1>
<p class="sub">Observe → Hypothesize → Ask → Verify → Recommend</p>

{% if error %}<div class="card error"><strong>Error</strong><div>{{ error }}</div></div>{% endif %}

{% if not session %}
<div class="card">
<form method="post" action="{{ url_for('start') }}" enctype="multipart/form-data">
<label>What is wrong with the device?</label>
<textarea name="problem" required placeholder="Example: Laptop powers on, fan spins, but the screen stays black."></textarea>
<label>Photo (optional but recommended)</label>
<input type="file" name="image" accept="image/*">
<button type="submit">Start investigation</button>
</form>
</div>
{% else %}

<div class="card">
<span class="badge">{{ session.status }}</span>
<span class="badge">{{ session.turn_count }} diagnostic turns</span>
<span class="badge">{{ result.steps_used if result else 0 }} model steps</span>
<h3>Problem</h3><div>{{ session.problem }}</div>
</div>

<div class="card">
<h3>Evidence ledger</h3>
{% if session.evidence %}
  {% for e in session.evidence %}
  <div class="item"><strong>{{ e.id.split(':')[-1] }}</strong> — {{ e.statement }}<br><small>{{ e.source }}</small></div>
  {% endfor %}
{% else %}<div class="muted">No evidence recorded yet.</div>{% endif %}
</div>

<div class="card">
<h3>Competing hypotheses</h3>
{% if session.hypotheses %}
  {% for h in session.hypotheses %}
  <div class="item"><strong>{{ h.cause }}</strong><br><span class="badge">{{ h.status }}</span>{% if h.rationale %}<div>{{ h.rationale }}</div>{% endif %}</div>
  {% endfor %}
{% else %}<div class="muted">The agent has not proposed a cause yet.</div>{% endif %}
</div>

{% if session.next_action %}
<div class="card action">
<h3>Next diagnostic step</h3>
<p><strong>{{ session.next_action.action }}</strong></p>
{% if session.next_action.observations %}<ul>{% for o in session.next_action.observations %}<li>{{ o }}</li>{% endfor %}</ul>{% endif %}
<form method="post" action="{{ url_for('resume') }}">
<label>What happened?</label>
<textarea name="answer" required placeholder="Report exactly what you observed."></textarea>
<button type="submit">Submit evidence and continue</button>
</form>
</div>
{% endif %}

{% if session.recommendation %}
<div class="card action"><h3>Verified recommendation</h3><p>{{ session.recommendation.action }}</p><small>Grounded in: {{ session.recommendation.evidence_ids|join(', ') }}</small></div>
{% endif %}

<div class="card"><form method="post" action="{{ url_for('reset') }}"><button type="submit">Start over</button></form></div>
{% endif %}
</main>
</body>
</html>
"""


def image_to_data_url(upload):
    if not upload or not upload.filename:
        return None
    data = upload.read()
    if not data:
        return None
    if len(data) > 8 * 1024 * 1024:
        raise ValueError("Please use an image smaller than 8 MB for the demo.")
    mime = upload.mimetype or mimetypes.guess_type(upload.filename)[0] or "image/jpeg"
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def current_context():
    loop = STATE["loop"]
    return {
        "session": loop.session.snapshot if loop else None,
        "result": STATE["last_result"],
        "error": STATE["error"],
    }


@app.get("/")
def index():
    return render_template_string(PAGE, **current_context())


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
        session.execute(
            "record_evidence",
            {
                "source": "user_text",
                "statement": problem,
                "provenance": {"channel": "phone_ui", "kind": "initial_problem"},
            },
        )
        provider = BasetenMuseProvider(image_data_url=image_data_url)
        loop = AgentLoop(session, provider, max_provider_steps=14)
        STATE["loop"] = loop
        STATE["last_result"] = loop.run()
    except Exception as exc:
        STATE["loop"] = None
        STATE["last_result"] = None
        STATE["error"] = str(exc)

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
        loop.resume_with_result(
            answer,
            {"channel": "phone_ui", "kind": "diagnostic_observation"},
        )
        STATE["last_result"] = loop.run()
    except Rejected as exc:
        STATE["error"] = f"Evidence rejected: {exc}"
    except Exception as exc:
        STATE["error"] = str(exc)

    return redirect(url_for("index"))


@app.post("/reset")
def reset():
    STATE["loop"] = None
    STATE["last_result"] = None
    STATE["error"] = None
    return redirect(url_for("index"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False)
