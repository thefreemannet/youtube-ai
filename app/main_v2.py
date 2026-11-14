"""J3G YouTube AI dashboard v2: safe LAN demo topic submission.

Deliberately leaves publishing disabled. A token protects new job creation;
existing read-only dashboard and video endpoints remain compatible.
"""
import hmac
import json
import os
import re
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel, Field

app = FastAPI(title="J3G YouTube AI Business")
ROOT = Path(os.environ.get("J3G_ROOT", "/opt/j3g-youtube-ai"))
JOBS = ROOT / "data" / "jobs"
TOKEN_FILE = ROOT / "data" / "dashboard_token"
JOB_PATTERN = re.compile(r"\d{8}-\d{6}-[a-f0-9]{6}")
CREATE_LOCK = threading.Lock()
ACTIVE_STATES = {
    "QUEUED", "RESEARCHING", "SCRIPTWRITING", "QUALITY_REVIEW",
    "RENDERING_PREVIEW",
}


class NewJob(BaseModel):
    topic: str = Field(min_length=5, max_length=180)


def read_json(path):
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path, content):
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(content, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)


def valid_job(job_id):
    if JOB_PATTERN.fullmatch(job_id) is None:
        raise HTTPException(400, "Invalid job ID")
    return JOBS / job_id


def require_token(value):
    if not TOKEN_FILE.is_file():
        raise HTTPException(503, "Dashboard token not configured on VM 111")
    secret = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not secret or not hmac.compare_digest(value or "", secret):
        raise HTTPException(401, "Invalid dashboard token")


@app.get("/api/health")
def health():
    return {
        "status": "online",
        "application": "J3G YouTube AI Business",
        "version": "0.2.0-demo",
        "publishing": "disabled",
    }


@app.get("/api/jobs")
def get_jobs():
    results = []
    if not JOBS.exists():
        return results
    for folder in sorted(JOBS.iterdir(), reverse=True):
        if not folder.is_dir() or not JOB_PATTERN.fullmatch(folder.name):
            continue
        data = read_json(folder / "job.json")
        if not data:
            continue
        production = read_json(folder / "production_report_auto.json")
        if not production:
            production = read_json(folder / "production_report.json")
        results.append({
            "job_id": folder.name,
            "topic": data.get("topic"),
            "status": data.get("status", "UNKNOWN"),
            "video_ready": (folder / "video.mp4").is_file(),
            "preview_ready": (folder / "video_auto_preview.mp4").is_file(),
            "duration": production.get("video_duration_seconds", production.get("duration_seconds")),
            "published": False,
            "error": data.get("error"),
        })
    return results


@app.post("/api/jobs", status_code=202)
def create_job(body: NewJob, x_admin_token: str | None = Header(default=None)):
    require_token(x_admin_token)
    topic = " ".join(body.topic.split())
    if not (5 <= len(topic) <= 180):
        raise HTTPException(422, "Topic length must be 5-180 characters")
    with CREATE_LOCK:
        for job in get_jobs():
            if job["status"] in ACTIVE_STATES:
                raise HTTPException(409, "A video job is already running or awaiting a stage transition")
        JOBS.mkdir(parents=True, exist_ok=True)
        job_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        folder = JOBS / job_id
        folder.mkdir(mode=0o750)
        write_json_atomic(folder / "job.json", {
            "job_id": job_id,
            "topic": topic,
            "status": "QUEUED",
            "created_utc": datetime.now(timezone.utc).isoformat(),
        })
        try:
            with (folder / "worker.log").open("ab") as log:
                subprocess.Popen(
                    [sys.executable, "-m", "app.job_worker", job_id],
                    cwd=str(ROOT),
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )
        except Exception as exc:
            data = read_json(folder / "job.json")
            data.update({"status": "FAILED", "error": "Could not launch worker: " + str(exc)[:200]})
            write_json_atomic(folder / "job.json", data)
            raise HTTPException(500, "Could not start job") from exc
        return {"job_id": job_id, "status": "QUEUED", "published": False}


@app.get("/videos/{job_id}")
def get_video(job_id: str):
    folder = valid_job(job_id)
    video = folder / "video.mp4"
    if not video.is_file():
        raise HTTPException(404, "Video not found")
    return FileResponse(video, media_type="video/mp4")


@app.get("/videos/{job_id}/preview")
def get_preview(job_id: str):
    folder = valid_job(job_id)
    video = folder / "video_auto_preview.mp4"
    if not video.is_file():
        raise HTTPException(404, "Preview not found")
    return FileResponse(video, media_type="video/mp4")


@app.get("/", response_class=HTMLResponse)
def dashboard():
    cards = []
    for record in get_jobs():
        job_id = record["job_id"]
        folder = JOBS / job_id
        job = read_json(folder / "job.json")
        topic = escape(str(record["topic"] or "Untitled"))
        status = escape(str(record["status"]))
        script = escape(str(job.get("script", {}).get("result", "")))
        quality = escape(str(job.get("quality", {}).get("result", "")))
        error = escape(str(job.get("error", "")))
        duration = record.get("duration")
        duration_text = f"{duration} seconds" if duration is not None else "Not available yet"
        video_html = ""
        if record["preview_ready"]:
            video_html = f'<video controls preload="metadata" width="300"><source src="/videos/{job_id}/preview" type="video/mp4"></video>'
        elif record["video_ready"]:
            video_html = f'<video controls preload="metadata" width="300"><source src="/videos/{job_id}" type="video/mp4"></video>'
        error_html = f'<p class="error">{error}</p>' if error else ''
        cards.append(f'''
        <section class="card">
          <h2>{topic}</h2>
          <p class="meta">Job: {job_id}</p>
          <p><strong>Status:</strong> {status}</p>
          <p>Duration: {escape(duration_text)}</p>
          <p class="meta">Local preview only — not published</p>
          {error_html}
          {video_html}
          <details><summary>Generated Script</summary><p>{script}</p></details>
          <details><summary>AI Quality Review</summary><p>{quality}</p></details>
        </section>''')
    content = "\n".join(cards) or "<p>No jobs created yet.</p>"
    page = '''<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>J3G YouTube AI Business</title>
<style>
body{background:#0c1424;color:#f1f5f9;font-family:Arial,sans-serif;margin:0;padding:26px}
.container{max-width:1050px;margin:auto}h1{color:#38bdf8}.subtitle,.meta{color:#94a3b8}
.card{background:#172337;padding:24px;border:1px solid #304158;border-radius:14px;margin:20px 0}
.status{display:inline-block;background:#13392c;color:#86efac;padding:8px 12px;border-radius:8px}
label{display:block;margin:12px 0 6px;font-weight:bold}input{box-sizing:border-box;width:100%;padding:12px;border-radius:8px;border:1px solid #40566c;background:#0c1424;color:white}
button{margin:16px 0;padding:12px 20px;background:#0284c7;color:white;border:0;border-radius:8px;font-weight:bold;cursor:pointer}button:disabled{opacity:.5}
video{display:block;max-width:100%;border-radius:12px;margin:18px 0}
details{border-top:1px solid #304158;padding:14px 0;white-space:pre-wrap}summary{cursor:pointer;color:#38bdf8;font-weight:bold}
.error{color:#fda4af}#msg{white-space:pre-wrap}
</style></head><body><main class="container">
<h1>J3G YouTube AI Business</h1><p class="subtitle">Multi-Agent Automated Content Creation System</p>
<div class="status">Application Online — Publishing Disabled</div>
<section class="card"><h2>Create video preview from a topic</h2>
<form id="createForm">
<label for="topic">Video topic</label><input id="topic" maxlength="180" minlength="5" placeholder="e.g., How does a VAV box work?" required>
<label for="token">Dashboard admin token</label><input id="token" type="password" autocomplete="off" required placeholder="Paste token from VM 111">
<button id="submit" type="submit">Create video preview</button>
</form><p id="msg" role="status"></p>
<p class="meta">One job at a time. Review technical claims and media licenses before publishing.</p>
</section>
<h2>Video Production Dashboard</h2>
<!-- JOB_CONTENT -->
</main><script>
const form=document.getElementById('createForm'),message=document.getElementById('msg'),button=document.getElementById('submit');
form.addEventListener('submit', async e => {
 e.preventDefault();button.disabled=true;message.textContent='Creating job...';
 try {
   const resp=await fetch('/api/jobs', {method:'POST',headers:{'Content-Type':'application/json','X-Admin-Token':document.getElementById('token').value},body:JSON.stringify({topic:document.getElementById('topic').value})});
   const data=await resp.json();
   if(!resp.ok) throw new Error(data.detail || 'Submission failed');
   message.textContent='Job queued: '+data.job_id+'. Reloading dashboard...';
   window.setTimeout(()=>location.reload(),1500);
 } catch(err) {message.textContent='Error: '+err.message;} finally {button.disabled=false;}
});
</script></body></html>'''
    return HTMLResponse(page.replace("<!-- JOB_CONTENT -->", content))
