"""Selected-video dashboard. The page shell is static; job text is inserted in the browser."""

import json
from html import escape


def render_dashboard(jobs, publishing_status, platforms):
    payload = json.dumps({"jobs": jobs, "platforms": platforms}, ensure_ascii=False)
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    status = escape(publishing_status)
    return PAGE.replace("__STATUS__", status).replace("__DATA__", payload)


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>J3G YouTube AI Business</title>
<style>
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; background: #0b1220; color: #e8eef7; font-family: "Segoe UI", Arial, sans-serif; }
button, input, textarea { font: inherit; }
header { display: flex; justify-content: space-between; gap: 16px; align-items: center; padding: 18px 22px; border-bottom: 1px solid #24344a; }
header h1 { margin: 0; font-size: 22px; color: #7dd3fc; }
header p { margin: 4px 0 0; color: #93a4b8; font-size: 14px; }
header button { background: transparent; color: #e8eef7; border: 1px solid #3d5168; border-radius: 8px; padding: 8px 12px; cursor: pointer; }
.shell { display: grid; grid-template-columns: 300px minmax(0, 1fr) 340px; gap: 18px; align-items: start; padding: 18px; }
.pane { background: #121a2b; border: 1px solid #2a3b52; border-radius: 16px; padding: 16px; min-width: 0; }
.sidebar, .review-pane { position: sticky; top: 16px; }
.sidebar h2, .stage h2, .review-pane h2 { margin: 0 0 12px; font-size: 16px; }
label { display: block; margin: 10px 0 6px; font-size: 13px; font-weight: 700; }
input[type=text], textarea { width: 100%; padding: 10px 12px; border-radius: 8px; border: 1px solid #3d5168; background: #0b1220; color: white; }
textarea { min-height: 88px; resize: vertical; }
button.primary, button.secondary, button.quiet { border: 0; border-radius: 8px; padding: 11px 14px; font-weight: 700; cursor: pointer; }
button.primary { background: #0f766e; color: white; width: 100%; margin-top: 12px; }
button.secondary { background: #0369a1; color: white; width: 100%; }
button.quiet { background: #9a3412; color: white; }
button:disabled { opacity: .55; cursor: not-allowed; }
.history { max-height: 62vh; overflow: auto; margin-top: 16px; }
.day { margin: 14px 0 8px; color: #7dd3fc; font-size: 12px; letter-spacing: .04em; text-transform: uppercase; }
.history-item { display: block; width: 100%; text-align: left; margin: 0 0 8px; padding: 10px; border-radius: 10px; border: 1px solid #2a3b52; background: #0b1220; color: inherit; cursor: pointer; }
.history-item.active { border-color: #38bdf8; }
.history-item strong, .history-item small { display: block; }
.history-item small { color: #93a4b8; margin-top: 4px; }
.stage { min-height: 70vh; }
.meta { color: #93a4b8; }
.error { color: #fda4af; white-space: pre-wrap; }
video { display: block; width: min(100%, 360px); aspect-ratio: 9 / 16; background: #05080f; border-radius: 18px; margin: 16px auto; }
a.download { display: block; width: min(100%, 360px); margin: 0 auto; text-align: center; text-decoration: none; background: #0369a1; color: white; border-radius: 8px; padding: 11px 14px; font-weight: 700; }
a.download[hidden] { display: none; }
.check { display: flex; gap: 10px; align-items: flex-start; font-weight: 500; margin: 10px 0; }
.check input { margin-top: 3px; }
.note, .result { white-space: pre-wrap; color: #bfdbfe; }
.blocked { color: #fcd34d; }
details { margin-top: 14px; border-top: 1px solid #2a3b52; padding-top: 10px; }
summary { cursor: pointer; color: #7dd3fc; font-weight: 700; }
@media (max-width: 980px) {
  .shell { grid-template-columns: 1fr; }
  .sidebar, .review-pane { position: static; }
  .sidebar { order: 1; }
  .stage { order: 2; }
  .review-pane { order: 3; }
  .history { max-height: 280px; }
}
</style>
</head>
<body>
<header>
  <div>
    <h1>J3G YouTube AI Business</h1>
    <p id="app-status">__STATUS__</p>
  </div>
  <form method="post" action="/logout"><button type="submit">Sign out</button></form>
</header>
<main class="shell">
  <aside class="pane sidebar">
    <h2>Create a video</h2>
    <form id="create-form">
      <label for="topic">Topic</label>
      <input id="topic" type="text" minlength="5" maxlength="180" required placeholder="How does a condensate trap protect an air handler?">
      <button class="secondary" id="create-button" type="submit">Create video</button>
    </form>
    <p id="create-message" class="note" role="status"></p>
    <h2>Video history</h2>
    <div id="history" class="history"></div>
  </aside>
  <section class="pane stage" id="stage" aria-live="polite">
    <h2 id="video-title">Select a video</h2>
    <p id="video-status" class="meta">Choose a job from the history.</p>
    <p id="video-duration" class="meta"></p>
    <p id="video-error" class="error"></p>
    <video id="player" controls preload="metadata" hidden></video>
    <a id="download-video" class="download" hidden>Download video</a>
  </section>
  <aside class="pane review-pane">
    <h2>Review and publish</h2>
    <div id="review-root"></div>
  </aside>
</main>
<script type="application/json" id="job-data">__DATA__</script>
<script>
const initial = JSON.parse(document.getElementById('job-data').textContent);
let jobs = initial.jobs || [];
const platforms = initial.platforms || {};
const LOCKED = new Set(['20261110-225615-919b89']);
const ACTIVE = new Set(['QUEUED','RESEARCHING','SCRIPTWRITING','QUALITY_REVIEW','RENDERING_PREVIEW']);
const JOB_ID = /^\d{8}-\d{6}-[a-f0-9]{6}$/;
let selectedId = '';
let reviewBuiltFor = '';

function jobById(id) { return jobs.find(job => job.job_id === id); }
function labelState(state) {
  if (state === 'UPLOADED_PRIVATE') return 'Private';
  if (state === 'PUBLISHED') return 'Published';
  if (state === 'NOT_UPLOADED') return 'Not uploaded';
  if (!state) return 'Unknown';
  return String(state).split('_').join(' ');
}
function errorText(data, fallback) {
  if (!data) return fallback;
  if (typeof data.detail === 'string') return data.detail;
  if (Array.isArray(data.detail)) return data.detail.map(item => item.msg || 'Invalid request').join('; ');
  return fallback;
}
async function api(path, method, payload) {
  const options = {method: method || 'GET', credentials: 'same-origin'};
  if (payload !== undefined) {
    options.headers = {'Content-Type': 'application/json'};
    options.body = JSON.stringify(payload);
  }
  const response = await fetch(path, options);
  if (response.status === 401) {
    location.href = '/login';
    throw new Error('Sign in again to continue.');
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(errorText(data, 'Request failed'));
  return data;
}
function renderHistory() {
  const root = document.getElementById('history');
  root.replaceChildren();
  if (!jobs.length) {
    const empty = document.createElement('p');
    empty.className = 'meta';
    empty.textContent = 'No videos yet.';
    root.appendChild(empty);
    return;
  }
  let day = '';
  for (const job of jobs) {
    if (job.day !== day) {
      day = job.day || 'Unknown date';
      const heading = document.createElement('h3');
      heading.className = 'day';
      heading.textContent = day;
      root.appendChild(heading);
    }
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'history-item' + (job.job_id === selectedId ? ' active' : '');
    const title = document.createElement('strong');
    title.textContent = job.topic || 'Untitled';
    const meta = document.createElement('small');
    meta.textContent = (job.status || 'Unknown') + ' · YouTube ' + labelState(job.youtube_state) + ' · Instagram ' + labelState(job.instagram_state);
    button.append(title, meta);
    button.addEventListener('click', () => selectJob(job.job_id));
    root.appendChild(button);
  }
}
function renderStage() {
  const job = jobById(selectedId);
  const title = document.getElementById('video-title');
  const status = document.getElementById('video-status');
  const duration = document.getElementById('video-duration');
  const error = document.getElementById('video-error');
  const player = document.getElementById('player');
  const download = document.getElementById('download-video');
  if (!job) {
    title.textContent = 'Select a video';
    status.textContent = 'Choose a job from the history.';
    duration.textContent = '';
    error.textContent = '';
    player.hidden = true;
    player.removeAttribute('src');
    download.hidden = true;
    download.removeAttribute('href');
    return;
  }
  title.textContent = job.topic || 'Untitled';
  status.textContent = 'Status: ' + (job.status || 'Unknown');
  duration.textContent = job.duration === null || job.duration === undefined ? 'Duration: not available yet' : 'Duration: ' + Number(job.duration).toFixed(2) + ' seconds';
  error.textContent = job.error || '';
  let src = '';
  if (JOB_ID.test(job.job_id)) {
    if (job.preview_ready) src = '/videos/' + job.job_id + '/preview';
    else if (job.video_ready) src = '/videos/' + job.job_id;
  }
  if (src && player.dataset.src !== src) {
    player.dataset.src = src;
    player.src = src;
  }
  player.hidden = !src;
  if (!src) player.removeAttribute('src');
  download.hidden = !src;
  if (src) download.href = src + '?download=1';
  else download.removeAttribute('href');
}
function field(parent, labelText, id, element) {
  const label = document.createElement('label');
  label.htmlFor = id;
  label.textContent = labelText;
  element.id = id;
  parent.append(label, element);
}
function renderReview() {
  const root = document.getElementById('review-root');
  const job = jobById(selectedId);
  root.replaceChildren();
  reviewBuiltFor = selectedId;
  if (!job) {
    const note = document.createElement('p');
    note.className = 'meta';
    note.textContent = 'Select a video to review it.';
    root.appendChild(note);
    return;
  }
  const summary = document.createElement('p');
  summary.className = 'meta';
  summary.id = 'platform-summary';
  summary.textContent = 'YouTube: ' + labelState(job.youtube_state) + ' · Instagram: ' + labelState(job.instagram_state);
  root.appendChild(summary);
  if (LOCKED.has(job.job_id)) {
    const locked = document.createElement('p');
    locked.className = 'blocked';
    locked.textContent = 'This video was already uploaded. It cannot be approved or published again.';
    root.appendChild(locked);
    return;
  }
  if (job.status === 'CHANGES_REQUESTED') {
    const held = document.createElement('p');
    held.className = 'blocked';
    held.textContent = 'Changes were requested. This video cannot be published until a new preview is approved.';
    root.appendChild(held);
  }
  const checks = document.createElement('div');
  for (const item of [
    ['watched_video', 'I watched the complete video.'],
    ['checked_technical_claims', 'I checked the factual and technical claims.'],
    ['checked_media_licenses', 'I have the rights to publish the narration, music, and any other included material.']
  ]) {
    const line = document.createElement('label');
    line.className = 'check';
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.id = item[0];
    const text = document.createElement('span');
    text.textContent = item[1];
    line.append(box, text);
    checks.appendChild(line);
  }
  root.appendChild(checks);
  const youtubeLine = document.createElement('label');
  youtubeLine.className = 'check';
  const youtube = document.createElement('input');
  youtube.type = 'checkbox';
  youtube.id = 'publish-youtube';
  youtube.disabled = !platforms.youtube || job.youtube_state !== 'NOT_UPLOADED' || job.youtube_request !== 'NOT_REQUESTED';
  youtubeLine.append(youtube, document.createTextNode('YouTube — upload as private'));
  const instagramLine = document.createElement('label');
  instagramLine.className = 'check';
  const instagram = document.createElement('input');
  instagram.type = 'checkbox';
  instagram.id = 'publish-instagram';
  instagram.disabled = !platforms.instagram || job.instagram_state !== 'NOT_UPLOADED' || job.instagram_request !== 'NOT_REQUESTED';
  instagramLine.append(instagram, document.createTextNode('Instagram — publish this Reel publicly'));
  root.append(youtubeLine, instagramLine);
  const action = document.createElement('button');
  action.className = 'primary';
  action.id = 'approve-publish';
  action.type = 'button';
  action.textContent = 'Approve & Publish';
  action.disabled = job.status === 'CHANGES_REQUESTED';
  action.addEventListener('click', approveAndPublish);
  root.appendChild(action);
  const result = document.createElement('p');
  result.id = 'publish-result';
  result.className = 'result';
  result.setAttribute('role', 'status');
  root.appendChild(result);
  if (job.status === 'FAILED') {
    const retry = document.createElement('button');
    retry.className = 'secondary';
    retry.type = 'button';
    retry.textContent = 'Retry failed production';
    retry.addEventListener('click', retryJob);
    root.appendChild(retry);
  }
  const advanced = document.createElement('details');
  const advancedSummary = document.createElement('summary');
  advancedSummary.textContent = 'Edit publishing text (optional)';
  const title = document.createElement('input');
  title.type = 'text';
  title.maxLength = 100;
  const description = document.createElement('textarea');
  description.maxLength = 5000;
  const caption = document.createElement('textarea');
  caption.maxLength = 2200;
  advanced.appendChild(advancedSummary);
  field(advanced, 'YouTube title', 'meta-title', title);
  field(advanced, 'YouTube description', 'meta-description', description);
  field(advanced, 'Instagram caption', 'meta-caption', caption);
  const hint = document.createElement('p');
  hint.className = 'meta';
  hint.textContent = 'Leave these blank to generate text from this video. Draft notices and another video’s caption are rejected.';
  advanced.appendChild(hint);
  root.appendChild(advanced);
  const changes = document.createElement('details');
  const changeSummary = document.createElement('summary');
  changeSummary.textContent = 'Request changes';
  const note = document.createElement('textarea');
  note.maxLength = 2000;
  const changeButton = document.createElement('button');
  changeButton.className = 'quiet';
  changeButton.type = 'button';
  changeButton.textContent = 'Request changes';
  changeButton.addEventListener('click', requestChanges);
  changes.appendChild(changeSummary);
  field(changes, 'What should be corrected?', 'change-note', note);
  changes.appendChild(changeButton);
  root.appendChild(changes);
}
function selectJob(id) {
  if (!jobById(id)) return;
  selectedId = id;
  history.replaceState(null, '', '#job=' + id);
  renderHistory();
  renderStage();
  renderReview();
}
async function approveAndPublish() {
  const job = jobById(selectedId);
  const result = document.getElementById('publish-result');
  const button = document.getElementById('approve-publish');
  if (!job || LOCKED.has(job.job_id)) return;
  const watched = document.getElementById('watched_video').checked;
  const technical = document.getElementById('checked_technical_claims').checked;
  const rights = document.getElementById('checked_media_licenses').checked;
  const youtube = document.getElementById('publish-youtube').checked;
  const instagram = document.getElementById('publish-instagram').checked;
  if (!watched || !technical || !rights) {
    result.textContent = 'Confirm the video, the technical claims, and your rights before approval.';
    return;
  }
  if (youtube || instagram) {
    const lines = ['Approve this video and queue the selected upload?'];
    if (youtube) lines.push('YouTube: PRIVATE');
    if (instagram) lines.push('Instagram: PUBLIC Reel');
    lines.push('Platforms that already have an upload record are skipped.');
    if (!confirm(lines.join('\n'))) return;
  } else if (!confirm('Record video approval without uploading to any platform?')) {
    return;
  }
  button.disabled = true;
  result.textContent = 'Saving approval...';
  try {
    const data = await api('/api/jobs/' + job.job_id + '/approve-and-publish', 'POST', {
      watched_video: watched,
      checked_technical_claims: technical,
      checked_media_licenses: rights,
      publish_youtube: youtube,
      publish_instagram: instagram,
      confirm_publish: youtube || instagram,
      title: document.getElementById('meta-title').value,
      description: document.getElementById('meta-description').value,
      caption: document.getElementById('meta-caption').value
    });
    await refreshJobs();
    const fresh = document.getElementById('publish-result');
    if (fresh) fresh.textContent = data.message || 'Saved.';
  } catch (err) {
    result.textContent = err.message;
    button.disabled = false;
  }
}
async function requestChanges() {
  const job = jobById(selectedId);
  const result = document.getElementById('publish-result');
  const note = document.getElementById('change-note').value.trim();
  if (note.length < 10) {
    result.textContent = 'Describe the required changes in at least 10 characters.';
    return;
  }
  try {
    const data = await api('/api/jobs/' + job.job_id + '/review/request-changes', 'POST', {note: note});
    await refreshJobs();
    const fresh = document.getElementById('publish-result');
    if (fresh) fresh.textContent = 'Saved: ' + data.status + '. Nothing was published.';
  } catch (err) {
    result.textContent = err.message;
  }
}
async function retryJob() {
  const job = jobById(selectedId);
  const result = document.getElementById('publish-result');
  if (!confirm('Retry production for this failed job? Approved videos and existing uploads are not changed.')) return;
  try {
    await api('/api/jobs/' + job.job_id + '/retry', 'POST', {});
    await refreshJobs();
    const fresh = document.getElementById('publish-result');
    if (fresh) fresh.textContent = 'Retry queued.';
  } catch (err) {
    result.textContent = err.message;
  }
}
async function refreshJobs() {
  const data = await api('/api/jobs');
  const previous = jobById(selectedId);
  jobs = data;
  if (selectedId && !jobById(selectedId)) selectedId = jobs[0] ? jobs[0].job_id : '';
  renderHistory();
  renderStage();
  const updated = jobById(selectedId);
  if (!updated || !previous || updated.status !== previous.status || updated.youtube_state !== previous.youtube_state || updated.instagram_state !== previous.instagram_state) {
    renderReview();
  }
}
document.getElementById('create-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = document.getElementById('create-button');
  const message = document.getElementById('create-message');
  button.disabled = true;
  message.textContent = 'Creating the video job...';
  try {
    const data = await api('/api/jobs', 'POST', {topic: document.getElementById('topic').value});
    location.href = '/#job=' + data.job_id;
    location.reload();
  } catch (err) {
    message.textContent = err.message;
    button.disabled = false;
  }
});
const hash = location.hash.match(/^#job=(\d{8}-\d{6}-[a-f0-9]{6})$/);
selectedId = hash && jobById(hash[1]) ? hash[1] : (jobs[0] ? jobs[0].job_id : '');
renderHistory();
renderStage();
renderReview();
setInterval(async () => {
  const current = jobById(selectedId);
  if (!current || !ACTIVE.has(current.status)) return;
  try { await refreshJobs(); } catch (err) { /* leave the current video on screen */ }
}, 4000);
</script>
</body>
</html>
"""
