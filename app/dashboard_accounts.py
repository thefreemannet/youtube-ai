"""Administrator account list for J3G YouTube AI."""

from datetime import datetime, timezone
from html import escape


def format_stamp(value):
    if not value:
        return ""
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.strftime("%b %d, %Y, %I:%M %p")


def format_when(value):
    if not value:
        return "Never"
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return "Never"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    elapsed = (now - moment).total_seconds()
    if elapsed < 0:
        return moment.strftime("%b %d, %Y, %I:%M %p")
    if elapsed < 60:
        return "Now"
    if elapsed < 3600:
        return f"{int(elapsed // 60)} min ago"
    if elapsed < 86400:
        return f"{int(elapsed // 3600)} h ago"
    if elapsed < 7 * 86400:
        return f"{int(elapsed // 86400)} d ago"
    return moment.strftime("%b %d, %Y, %I:%M %p")


def _actions(username, status):
    safe = escape(username)
    approve = (
        f'<form method="post" action="/accounts/{safe}/approve">'
        f'<button class="btn" type="submit">Approve</button></form>'
    )
    reject = (
        f'<form method="post" action="/accounts/{safe}/reject">'
        f'<button class="btn secondary" type="submit">Reject</button></form>'
    )
    revoke = (
        f'<form method="post" action="/accounts/{safe}/reject">'
        f'<button class="btn secondary" type="submit">Revoke</button></form>'
    )
    if status == "pending":
        return approve + reject
    if status == "approved":
        return revoke
    return approve


def render_accounts(overview):
    labels = {
        "pending": "Pending",
        "approved": "Approved",
        "rejected": "Rejected",
    }
    cards = (
        (overview["approved"], "approved"),
        (overview["pending"], "pending"),
        (overview["active_now"], "active now"),
        (overview["active_today"], "active today"),
        (overview["logged_in_7d"], "login in 7 days"),
        (overview["videos_week"], "videos this week"),
        (overview["logins_week"], "logins this week"),
        (overview["never_signed_in"], "never signed in"),
    )
    stats = "".join(
        f'<div class="stat"><b>{escape(str(number))}</b><span>{escape(label)}</span></div>'
        for number, label in cards
    )
    users = overview["users"]
    if not users:
        rows = '<tr><td colspan="10" class="muted">No one has registered yet.</td></tr>'
    else:
        rendered = []
        for user in users:
            status = user["status"] if user["status"] in labels else "rejected"
            activity = user["activity"]
            activity_class = {
                "Active": "status-approved",
                "Active today": "status-approved",
                "Never": "status-pending",
            }.get(activity, "muted")
            login_times = f" · {user['login_count']} times" if user["login_count"] else ""
            usage = f"{user['videos_created']} videos · {user['login_count']} logins"
            rendered.append(
                "<tr>"
                f"<td>{escape(user['name'])}</td>"
                f"<td>{escape(user['username'])}</td>"
                f"<td>{escape(user['email'])}</td>"
                f'<td class="status-{escape(status)}">{escape(labels[status])}</td>'
                f'<td class="{activity_class}">{escape(activity)}</td>'
                f"<td>{escape(format_when(user['last_login_utc']) + login_times)}</td>"
                f"<td>{escape(format_when(user['last_seen_utc']))}</td>"
                f"<td>{escape(usage)}</td>"
                f"<td>{escape(format_stamp(user['created_utc']))}</td>"
                f'<td class="actions">{_actions(user["username"], status)}</td>'
                "</tr>"
            )
        rows = "".join(rendered)
    return PAGE.replace("__STATS__", stats).replace("__ROWS__", rows)


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Accounts — J3G YouTube AI</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,650&family=Outfit:wght@400;500;650&display=swap" rel="stylesheet">
<style>
:root { --bg:#f3eee4; --paper:#fffdf8; --ink:#1a2421; --muted:#5c6b66; --line:#d9d0c3; --teal:#0d5c56; --ok:#1b7a4a; --bad:#b42318; --gold:#b8892d; }
* { box-sizing: border-box; }
body { margin:0; min-height:100vh; color:var(--ink); font-family:Outfit, "Segoe UI", sans-serif;
  background: radial-gradient(900px 420px at 8% -10%, #dceee8 0%, transparent 55%), radial-gradient(700px 380px at 100% 0%, #f3e2cf 0%, transparent 50%), var(--bg); }
.top { position:sticky; top:0; z-index:2; display:flex; justify-content:space-between; gap:16px; align-items:center; flex-wrap:wrap; padding:14px 22px; background:rgba(243,238,228,.92); border-bottom:1px solid var(--line); }
.brand { display:flex; align-items:center; gap:10px; color:inherit; text-decoration:none; }
.brand-mark { display:grid; place-items:center; width:44px; height:44px; border-radius:12px; background:var(--teal); color:#f7f3ea; font-family:Fraunces, Georgia, serif; font-weight:700; }
.brand-text { display:flex; flex-direction:column; line-height:1.1; }
.brand-text em { font-style:normal; color:var(--muted); font-size:.78rem; }
.nav { display:flex; gap:8px; align-items:center; }
.nav a { color:var(--ink); text-decoration:none; padding:8px 12px; border-radius:999px; }
.nav a.active { background:#fff; }
button, .btn { font:inherit; }
.nav form { margin:0; }
.nav button, .btn { border:0; border-radius:12px; padding:8px 12px; cursor:pointer; background:#fff; color:var(--ink); border:1px solid var(--line); }
.btn { background:var(--teal); color:#fff; border:0; font-weight:650; }
.btn.secondary { background:#fff; color:var(--ink); border:1px solid var(--line); }
main { padding:28px; }
.kicker { color:var(--teal); font-weight:650; letter-spacing:.08em; text-transform:uppercase; font-size:.75rem; }
h1 { font-family:Fraunces, Georgia, serif; font-weight:650; font-size:2.4rem; margin:8px 0; }
.muted { color:var(--muted); }
.stat-grid { display:grid; grid-template-columns:repeat(4, 1fr); gap:14px; margin:18px 0; }
.stat, .panel { background:var(--paper); border:1px solid var(--line); border-radius:18px; box-shadow:0 18px 40px rgba(26,36,33,.08); }
.stat { padding:16px; }
.stat b { display:block; font-size:1.35rem; }
.stat span { color:var(--muted); }
.panel { padding:8px 16px 16px; overflow:auto; }
table { width:100%; border-collapse:collapse; }
th, td { text-align:left; padding:10px; border-bottom:1px solid var(--line); vertical-align:middle; white-space:nowrap; }
.actions { display:flex; gap:8px; }
.actions form { margin:0; }
.status-approved { color:var(--ok); font-weight:650; }
.status-pending { color:var(--gold); font-weight:650; }
.status-rejected { color:var(--bad); font-weight:650; }
@media (max-width: 900px) { .stat-grid { grid-template-columns:1fr 1fr; } }
</style>
</head>
<body>
<header class="top">
  <a class="brand" href="/">
    <span class="brand-mark">YT</span>
    <span class="brand-text"><strong>Admin</strong><em>accounts and activity</em></span>
  </a>
  <nav class="nav">
    <a href="/">Studio</a>
    <a href="/accounts" class="active">Accounts</a>
    <form method="post" action="/logout"><button type="submit">Sign out</button></form>
  </nav>
</header>
<main>
  <div class="kicker">Administration</div>
  <h1>Accounts and activity</h1>
  <p class="muted">New accounts stay closed until thefreemannet approves them. Active means the person used the studio in the last 15 minutes.</p>
  <div class="stat-grid">__STATS__</div>
  <div class="panel">
    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>Username</th>
          <th>Email</th>
          <th>Status</th>
          <th>Active</th>
          <th>Last login</th>
          <th>Last activity</th>
          <th>Use</th>
          <th>Created</th>
          <th></th>
        </tr>
      </thead>
      <tbody>__ROWS__</tbody>
    </table>
  </div>
</main>
</body>
</html>
"""
