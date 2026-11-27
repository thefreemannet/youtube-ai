"""Selected-video dashboard. The page shell is static; job text is inserted in the browser."""

import json
from html import escape


def render_dashboard(jobs, publishing_status, platforms, is_admin=False):
    payload = json.dumps({"jobs": jobs, "platforms": platforms}, ensure_ascii=False)
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    status = escape(publishing_status)
    admin_link = '<a class="nav-accounts" href="/accounts">Accounts</a>' if is_admin else ""
    return (
        PAGE.replace("__STATUS__", status)
        .replace("__DATA__", payload)
        .replace("__ADMIN_LINK__", admin_link)
        .replace("__CATEGORIES__", _category_options())
    )


def _category_options():
    from app.categories import CATEGORIES
    parts = []
    for item in CATEGORIES:
        selected = " selected" if item["id"] == "hvac" else ""
        parts.append(
            f'<option value="{escape(item["id"])}"{selected}>{escape(item["label"])}</option>'
        )
    return "".join(parts)


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
header button, header a.nav-accounts { background: transparent; color: #e8eef7; border: 1px solid #3d5168; border-radius: 8px; padding: 8px 12px; cursor: pointer; text-decoration: none; }
.header-actions { display: flex; gap: 10px; align-items: center; }
.shell { display: grid; grid-template-columns: 420px 10px minmax(360px, 1fr) 10px 420px; gap: 0; align-items: stretch; width: 100%; padding: 18px 22px; }
.shell.resizing, .shell.resizing .splitter { cursor: col-resize; user-select: none; }
.splitter { position: relative; cursor: col-resize; touch-action: none; }
.splitter::before { content: ""; position: absolute; top: 24px; bottom: 24px; left: 4px; width: 2px; border-radius: 2px; background: #3d5168; }
.pane { background: #121a2b; border: 1px solid #2a3b52; border-radius: 16px; padding: 16px; min-width: 0; }
.sidebar, .review-pane { position: sticky; top: 16px; }
.sidebar h2, .stage h2, .review-pane h2 { margin: 0 0 12px; font-size: 16px; }
label { display: block; margin: 10px 0 6px; font-size: 13px; font-weight: 700; }
input[type=text], textarea, select { width: 100%; padding: 10px 12px; border-radius: 8px; border: 1px solid #3d5168; background: #0b1220; color: white; }
textarea { min-height: 88px; resize: vertical; }
button.primary, button.secondary, button.quiet { border: 0; border-radius: 8px; padding: 11px 14px; font-weight: 700; cursor: pointer; }
button.primary { background: #0f766e; color: white; width: 100%; margin-top: 12px; }
button.secondary { background: #0369a1; color: white; width: 100%; }
#create-three { margin-top: 8px; }
button.quiet { background: #9a3412; color: white; }
button:disabled { opacity: .55; cursor: not-allowed; }
.history { max-height: 62vh; overflow: auto; margin-top: 16px; }
.day { margin: 14px 0 8px; color: #7dd3fc; font-size: 12px; letter-spacing: .04em; text-transform: uppercase; }
.history-row { display: flex; gap: 6px; align-items: stretch; margin: 0 0 8px; }
.history-item { display: block; width: 100%; text-align: left; margin: 0; padding: 10px; border-radius: 10px; border: 1px solid #2a3b52; background: #0b1220; color: inherit; cursor: pointer; }
button.history-delete { border: 1px solid #7f1d1d; background: transparent; color: #fda4af; border-radius: 10px; padding: 8px; cursor: pointer; }
.history-item.active { border-color: #38bdf8; }
.history-item strong, .history-item small { display: block; }
.history-item small { color: #93a4b8; margin-top: 4px; }
.stage { min-height: 70vh; }
.meta { color: #93a4b8; }
.error { color: #fda4af; white-space: pre-wrap; }
video { display: block; width: min(100%, 360px); aspect-ratio: 9 / 16; background: #05080f; border-radius: 18px; margin: 16px auto; }
a.download { display: block; width: min(100%, 360px); margin: 0 auto; text-align: center; text-decoration: none; background: #0369a1; color: white; border-radius: 8px; padding: 11px 14px; font-weight: 700; }
a.download[hidden] { display: none; }
a.platform-link { display: block; margin: 8px 0; }
.check { display: flex; gap: 10px; align-items: flex-start; font-weight: 500; margin: 10px 0; }
.check input { margin-top: 3px; }
.note, .result, .script { white-space: pre-wrap; color: #bfdbfe; }
.script { background: #0b1220; border-radius: 12px; padding: 12px; color: #e8eef7; }
.blocked { color: #fcd34d; }
details { margin-top: 14px; border-top: 1px solid #2a3b52; padding-top: 10px; }
summary { cursor: pointer; color: #7dd3fc; font-weight: 700; }
@media (max-width: 1100px) {
  .shell { grid-template-columns: 1fr; }
  .splitter { display: none; }
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
  <div class="header-actions">__ADMIN_LINK__<form method="post" action="/logout"><button type="submit">Sign out</button></form></div>
</header>
<main class="shell">
  <aside class="pane sidebar">
    <h2>Create a video</h2>
    <form id="create-form">
      <label for="topic">Topic</label>
      <input id="topic" type="text" minlength="5" maxlength="180" required placeholder="What should this video explain?">
      <label for="script">Script</label>
      <textarea id="script" maxlength="4000" placeholder="Optional. Write or paste the words to be spoken."></textarea>
      <p class="meta">Leave the script empty and the studio writes it. A script that would last under a minute is expanded past one minute, and the idea stays the same.</p>
      <label for="picture">Picture</label>
      <input id="picture" type="file" accept="image/jpeg,image/png,image/webp">
      <p class="meta">Optional. The studio looks at the picture and makes the video about what it shows.</p>
      <label for="category">Category</label>
      <select id="category">__CATEGORIES__</select>
      <p class="meta">A video starts when you ask for it here. The category applies to that video.</p>
      <label for="language">Language</label>
      <select id="language">
        <option value="en">English</option>
        <option value="es">Spanish, same voice</option>
        <option value="both">Both, English and Spanish</option>
      </select>
      <button class="secondary" id="create-button" type="submit">Create video</button>
      <button class="secondary" id="create-three" type="button">Create 3 videos</button>
    </form>
    <p id="create-message" class="note" role="status"></p>
    <button class="secondary" id="generate-three" type="button">Generate 3 videos in English and Spanish</button>
    <p id="generate-message" class="note" role="status"></p>
    <h2>Video history</h2>
    <p class="meta">Videos show up here after someone asks for them on this page.</p>
    <div id="history" class="history"></div>
  </aside>
  <div class="splitter" data-edge="left" role="separator" aria-orientation="vertical" aria-label="Drag to resize the side list" title="Drag to resize"></div>
  <section class="pane stage" id="stage" aria-live="polite">
    <h2 id="video-title">Select a video</h2>
    <p id="video-status" class="meta">Choose a job from the history.</p>
    <p id="video-duration" class="meta"></p>
    <p id="video-error" class="error"></p>
    <pre id="script-review" class="script" hidden></pre>
    <video id="player" controls preload="metadata" hidden></video>
    <a id="download-video" class="download" hidden>Download video</a>
  </section>
  <div class="splitter" data-edge="right" role="separator" aria-orientation="vertical" aria-label="Drag to resize the review panel" title="Drag to resize"></div>
  <aside class="pane review-pane">
    <h2>Review and publish</h2>
    <div id="review-root"></div>
  </aside>
</main>
<script type="application/json" id="job-data">__DATA__</script>
<script>
const initial = JSON.parse(document.getElementById('job-data').textContent);
setupPaneResize();
let jobs = initial.jobs || [];
const platforms = initial.platforms || {};
const LOCKED = new Set(['20261110-225615-919b89']);
const ACTIVE = new Set(['QUEUED','RESEARCHING','SCRIPTWRITING','QUALITY_REVIEW','RENDERING_PREVIEW']);
const JOB_ID = /^\d{8}-\d{6}-[a-f0-9]{6}$/;
function setupPaneResize() {
  const shell = document.querySelector('.shell');
  if (!shell) return;
  const key = 'j3g-pane-widths';
  const min = 280;
  let left = 420;
  let right = 420;
  try {
    const saved = JSON.parse(localStorage.getItem(key) || '{}');
    if (saved.left >= min && saved.left <= 900) left = saved.left;
    if (saved.right >= min && saved.right <= 900) right = saved.right;
  } catch (err) { /* keep the starting widths */ }
  function apply() {
    shell.style.gridTemplateColumns = left + 'px 10px minmax(360px, 1fr) 10px ' + right + 'px';
  }
  apply();
  document.querySelectorAll('.splitter').forEach(bar => {
    bar.addEventListener('pointerdown', (event) => {
      if (window.matchMedia('(max-width: 1100px)').matches) return;
      event.preventDefault();
      const edge = bar.dataset.edge;
      const startX = event.clientX;
      const startLeft = left;
      const startRight = right;
      shell.classList.add('resizing');
      function move(ev) {
        const dx = ev.clientX - startX;
        const max = Math.max(min, shell.clientWidth - 360 - min - 20);
        if (edge === 'left') left = Math.min(max, Math.max(min, startLeft + dx));
        else right = Math.min(max, Math.max(min, startRight - dx));
        apply();
      }
      function up() {
        shell.classList.remove('resizing');
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        localStorage.setItem(key, JSON.stringify({left: Math.round(left), right: Math.round(right)}));
      }
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    });
  });
}
let selectedId = '';
let reviewBuiltFor = '';

function jobById(id) { return jobs.find(job => job.job_id === id); }
function videoTitle(job) {
  return (job.title || job.topic || 'Untitled') + (job.language === 'es' ? ' · Spanish' : '');
}
function instagramLabel(job) {
  if (job.instagram_reel_confirmed) return 'Reel confirmed';
  return labelState(job.instagram_state);
}
function platformSelectable(enabled, state, requestState, retry) {
  if (!enabled) return false;
  if (retry) return true;
  return state === 'NOT_UPLOADED' && requestState === 'NOT_REQUESTED';
}
function publishing(job) {
  const busy = new Set(['QUEUED','RUNNING','STARTED','CONTAINER_CREATED','UPLOADED_PROCESSING','PUBLISH_REQUESTED']);
  return busy.has(job.youtube_request) || busy.has(job.instagram_request) || busy.has(job.tiktok_request) || busy.has(job.youtube_state) || busy.has(job.instagram_state) || busy.has(job.tiktok_state);
}
function labelState(state) {
  if (state === 'SCHEDULED') return 'Scheduled';
  if (state === 'UPLOADED_PRIVATE') return 'Private';
  if (state === 'UPLOADED_PUBLIC') return 'Public';
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
    const row = document.createElement('div');
    row.className = 'history-row';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'history-item' + (job.job_id === selectedId ? ' active' : '');
    const title = document.createElement('strong');
    title.textContent = videoTitle(job);
    const meta = document.createElement('small');
    const categoryName = job.category_label || 'HVAC, BAS and building controls';
    if (job.awaiting_approval) {
      meta.textContent = categoryName + ' · Waiting for approval' + (job.carried_over ? ' · moved to this day' : '') + ' · ' + labelState(job.status);
    } else {
      meta.textContent = categoryName + ' · ' + (job.status || 'Unknown') + ' · YouTube ' + labelState(job.youtube_state) + ' · Instagram ' + instagramLabel(job) + ' · TikTok ' + labelState(job.tiktok_state);
    }
    button.append(title, meta);
    button.addEventListener('click', () => selectJob(job.job_id));
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'history-delete';
    remove.textContent = 'Delete';
    remove.addEventListener('click', () => deleteJob(job.job_id));
    row.append(button, remove);
    root.appendChild(row);
  }
}
function renderStage() {
  const job = jobById(selectedId);
  const title = document.getElementById('video-title');
  const status = document.getElementById('video-status');
  const duration = document.getElementById('video-duration');
  const error = document.getElementById('video-error');
  const script = document.getElementById('script-review');
  const player = document.getElementById('player');
  const download = document.getElementById('download-video');
  function clearPlayer() {
    player.hidden = true;
    player.pause();
    player.removeAttribute('src');
    player.dataset.src = '';
    player.load();
  }
  if (!job) {
    title.textContent = 'Select a video';
    status.textContent = 'Choose a job from the history.';
    duration.textContent = '';
    error.textContent = '';
    script.hidden = true;
    script.textContent = '';
    clearPlayer();
    download.hidden = true;
    download.removeAttribute('href');
    return;
  }
  title.textContent = videoTitle(job);
  status.textContent = (job.category_label || 'HVAC, BAS and building controls') + ' · ' + (job.awaiting_approval ? 'Waiting for approval. ' : '') + 'Status: ' + (job.status || 'Unknown');
  duration.textContent = job.duration === null || job.duration === undefined ? 'Duration: not available yet' : 'Duration: ' + Number(job.duration).toFixed(2) + ' seconds';
  error.textContent = job.error || '';
  let src = '';
  if (JOB_ID.test(job.job_id)) {
    if (job.preview_ready) src = '/videos/' + job.job_id + '/preview';
    else if (job.video_ready) src = '/videos/' + job.job_id;
  }
  script.hidden = true;
  script.textContent = '';
  if (src) {
    if (player.dataset.src !== src) {
      player.dataset.src = src;
      player.src = src;
    }
    player.hidden = false;
  } else {
    clearPlayer();
    const parts = [];
    if (job.quality_note) parts.push(job.quality_note);
    if (job.narration) parts.push(job.narration);
    if (parts.length) {
      script.hidden = false;
      script.textContent = parts.join('\n\n');
    }
  }
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
  summary.textContent = 'YouTube: ' + labelState(job.youtube_state) + ' · Instagram: ' + instagramLabel(job) + ' · TikTok: ' + labelState(job.tiktok_state);
  root.appendChild(summary);
  const reel = document.createElement('p');
  reel.className = job.instagram_reel_confirmed ? 'meta' : (job.instagram_note ? 'error' : 'meta');
  reel.id = 'reel-status';
  if (job.instagram_reel_confirmed) {
    reel.textContent = 'Instagram Reel: uploaded correctly.';
  } else if (publishing(job) && (job.instagram_state !== 'NOT_UPLOADED' || job.instagram_request !== 'NOT_REQUESTED')) {
    reel.textContent = 'Instagram Reel: upload in progress. The confirmation appears here when Instagram accepts it.';
  } else if (job.instagram_note) {
    reel.textContent = 'Instagram Reel: not confirmed. ' + job.instagram_note;
  } else if (job.instagram_state === 'PUBLISHED') {
    reel.textContent = 'Instagram Reel: published, but the confirmation was not recorded.';
  } else {
    reel.textContent = 'Instagram Reel: not uploaded yet. After you publish, this line changes to uploaded correctly or shows the problem.';
  }
  root.appendChild(reel);
  const retryNames = [];
  if (job.youtube_retry) retryNames.push('YouTube');
  if (job.instagram_retry) retryNames.push('Instagram');
  if (job.youtube_reconnect) {
    const expired = document.createElement('p');
    expired.className = 'error';
    expired.textContent = 'YouTube rejected the saved login. Reconnect YouTube before checking it again. Instagram can still be published on its own.';
    root.appendChild(expired);
  }
  if (retryNames.length) {
    const again = document.createElement('p');
    again.className = 'meta';
    again.textContent = retryNames.join(' and ') + ' did not finish uploading. Check it again, then use Approve & Publish.';
    root.appendChild(again);
  }
  if (job.instagram_reel_confirmed && /^https:\/\/(www\.)?instagram\.com\//.test(job.instagram_reel_url || '')) {
    const link = document.createElement('a');
    link.href = job.instagram_reel_url;
    link.target = '_blank';
    link.rel = 'noopener';
    link.className = 'platform-link';
    link.textContent = 'Open the confirmed Instagram Reel';
    root.appendChild(link);
  }
  if (/^https:\/\/www\.youtube\.com\/watch\?v=[A-Za-z0-9_-]{11}$/.test(job.youtube_url || '')) {
    const watch = document.createElement('a');
    watch.href = job.youtube_url;
    watch.target = '_blank';
    watch.rel = 'noopener';
    watch.className = 'platform-link';
    watch.textContent = 'Open the YouTube video';
    root.appendChild(watch);
  }
  if (/^https:\/\/www\.tiktok\.com\/@[A-Za-z0-9._]{2,24}\/video\/\d+$/.test(job.tiktok_url || '')) {
    const tiktokLink = document.createElement('a');
    tiktokLink.className = 'platform-link';
    tiktokLink.href = job.tiktok_url;
    tiktokLink.target = '_blank';
    tiktokLink.rel = 'noopener';
    tiktokLink.textContent = 'Open the TikTok video';
    root.appendChild(tiktokLink);
  }
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
  youtube.disabled = !platformSelectable(platforms.youtube, job.youtube_state, job.youtube_request, job.youtube_retry);
  youtubeLine.append(youtube, document.createTextNode('YouTube — upload as public'));
  const instagramLine = document.createElement('label');
  instagramLine.className = 'check';
  const instagram = document.createElement('input');
  instagram.type = 'checkbox';
  instagram.id = 'publish-instagram';
  instagram.disabled = !platformSelectable(platforms.instagram, job.instagram_state, job.instagram_request, job.instagram_retry);
  instagramLine.append(instagram, document.createTextNode('Instagram — publish this Reel publicly'));
  const tiktokLine = document.createElement('label');
  tiktokLine.className = 'check';
  const tiktok = document.createElement('input');
  tiktok.type = 'checkbox';
  tiktok.id = 'publish-tiktok';
  tiktok.disabled = !platformSelectable(platforms.tiktok, job.tiktok_state, job.tiktok_request, job.tiktok_retry);
  tiktokLine.append(tiktok, document.createTextNode('TikTok — public after TikTok approves the app'));
  const tags = document.createElement('p');
  tags.className = 'meta';
  tags.textContent = job.tiktok_hashtags || '';
  root.append(youtubeLine, instagramLine, tiktokLine, tags);
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
  const tiktok = document.getElementById('publish-tiktok').checked;
  if (!watched || !technical || !rights) {
    result.textContent = 'Confirm the video, the technical claims, and your rights before approval.';
    return;
  }
  if (youtube || instagram || tiktok) {
    const lines = ['Approve this video and queue the selected upload?'];
    if (youtube) lines.push('YouTube: PUBLIC');
    if (instagram) lines.push('Instagram: PUBLIC Reel');
    if (tiktok) lines.push('TikTok: ' + (job.tiktok_hashtags || 'your account'));
    lines.push('A platform that already has the video is skipped. A failed attempt can be sent again.');
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
      publish_tiktok: tiktok,
      confirm_publish: youtube || instagram || tiktok,
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
  if (!updated || !previous || updated.status !== previous.status || updated.youtube_state !== previous.youtube_state || updated.instagram_state !== previous.instagram_state || updated.instagram_reel_confirmed !== previous.instagram_reel_confirmed || updated.tiktok_state !== previous.tiktok_state) {
    renderReview();
  }
}
async function deleteJob(id) {
  const job = jobById(id);
  const message = document.getElementById('generate-message');
  const name = job ? videoTitle(job) : 'this video';
  if (!confirm('Delete "' + name + '" from the side list? A preview is removed too.')) return;
  try {
    jobs = jobs.filter(job => job.job_id !== id);
    renderHistory();
    if (selectedId === id) {
      selectedId = '';
      renderStage();
    }
    try {
      const data = await api('/api/jobs/' + id, 'DELETE');
      await refreshJobs();
      if (jobById(id)) {
        if (message) message.textContent = 'That video is still in the side list.';
        return;
      }
      if (message) {
        message.textContent = data.platform_copy_kept
          ? 'Removed from the side list. A copy already on Instagram or YouTube stays there.'
          : 'Deleted from the side list.';
      }
    } catch (err) {
      await refreshJobs().catch(() => {});
      if (message) message.textContent = err.message;
    }
  } catch (err) {
    if (message) message.textContent = err.message;
  }
}
document.getElementById('create-three').addEventListener('click', async () => {
  const button = document.getElementById('create-three');
  const message = document.getElementById('create-message');
  const language = document.getElementById('language').value;
  const label = language === 'es' ? 'Spanish' : (language === 'both' ? 'English and Spanish' : 'English');
  if (!confirm('Create 3 HVAC videos in ' + label + '?')) return;
  button.disabled = true;
  message.textContent = 'Creating 3 videos in ' + label + '...';
  try {
    await api('/api/automation/generate-language', 'POST', {language: language});
    location.reload();
  } catch (err) {
    message.textContent = err.message;
    button.disabled = false;
  }
});
document.getElementById('generate-three').addEventListener('click', async () => {
  const button = document.getElementById('generate-three');
  const message = document.getElementById('generate-message');
  if (!confirm('Generate 3 topics in English and Spanish? Each topic is made twice. Videos still waiting for review stay in the side list under their day.')) return;
  button.disabled = true;
  message.textContent = 'Creating 3 topics in English and Spanish...';
  try {
    await api('/api/automation/generate', 'POST', {});
    location.reload();
  } catch (err) {
    message.textContent = err.message;
    button.disabled = false;
  }
});
document.getElementById('create-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = document.getElementById('create-button');
  const message = document.getElementById('create-message');
  const both = document.getElementById('language').value === 'both';
  button.disabled = true;
  message.textContent = both ? 'Creating the English and Spanish videos...' : 'Creating the video job...';
  try {
    const picture = document.getElementById('picture').files[0];
    let data;
    if (picture) {
      const body = new FormData();
      body.append('topic', document.getElementById('topic').value);
      body.append('language', document.getElementById('language').value);
      body.append('category', document.getElementById('category').value);
      body.append('script', document.getElementById('script').value);
      body.append('picture', picture);
      const response = await fetch('/api/jobs/with-picture', {method: 'POST', credentials: 'same-origin', body: body});
      if (response.status === 401) {
        location.href = '/login';
        throw new Error('Sign in again to continue.');
      }
      data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(errorText(data, 'Request failed'));
    } else {
      data = await api('/api/jobs', 'POST', {
        topic: document.getElementById('topic').value,
        language: document.getElementById('language').value,
        category: document.getElementById('category').value,
        script: document.getElementById('script').value
      });
    }
    location.href = '/#job=' + data.job_id;
    location.reload();
  } catch (err) {
    message.textContent = err.message;
    button.disabled = false;
  }
});
const hash = location.hash.match(/^#job=(\d{8}-\d{6}-[a-f0-9]{6})$/);
const waiting = firstWaiting();
selectedId = hash && jobById(hash[1]) ? hash[1] : (waiting ? waiting.job_id : (jobs[0] ? jobs[0].job_id : ''));
renderHistory();
renderStage();
renderReview();
function firstWaiting() {
  return jobs.find(job => job.awaiting_approval && (job.preview_ready || job.video_ready))
    || jobs.find(job => job.awaiting_approval);
}
setInterval(async () => {
  const busy = jobs.some(job => ACTIVE.has(job.status) || publishing(job) || job.status === 'SCHEDULED');
  if (!busy) return;
  try { await refreshJobs(); } catch (err) { /* leave the current video on screen */ }
}, 4000);
</script>
</body>
</html>
"""
