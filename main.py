# app.py — JUBAYER HOSTING (Multi-Server + Templates + Files + Accounts)
from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify, send_file
import os, sys, json, subprocess, threading, time, shutil, zipfile, hashlib, re, uuid, io
from datetime import datetime
import psutil
from functools import wraps

app = Flask(__name__)
app.secret_key = 'jubayer-super-secret-key-2026'
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024

# ============================================
# PATHS / CONFIG
# ============================================
DATA_DIR      = 'data'
SERVERS_DIR   = 'servers'
SHARED_LIBS   = 'shared_libs'
TEMPLATES_BOT = 'templates_bot'
CONFIG_FILE   = os.path.join(DATA_DIR, 'config.json')
SERVERS_FILE  = os.path.join(DATA_DIR, 'servers.json')
MAX_SERVERS   = 40

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(SERVERS_DIR, exist_ok=True)
os.makedirs(SHARED_LIBS, exist_ok=True)
os.makedirs(TEMPLATES_BOT, exist_ok=True)

MASTER_USERNAME      = 'SEMY'
MASTER_PASSWORD_HASH = hashlib.sha256('M4X'.encode()).hexdigest()

SHARED_PACKAGES = [
    'httpx',
    'google-play-scraper',
    'pycryptodome',
    'protobuf',
    'protobuf-decoder',
]

# ============================================
# SHARED LIBS
# ============================================
def ensure_shared_libs():
    marker = os.path.join(SHARED_LIBS, '.installed')
    if os.path.exists(marker):
        print(f"[libs] ✅ Already installed in {SHARED_LIBS}/")
        return
    print(f"[libs] 📦 Installing {len(SHARED_PACKAGES)} packages to {SHARED_LIBS}/ ...")
    cmd = [sys.executable, '-m', 'pip', 'install',
           '--target', os.path.abspath(SHARED_LIBS),
           '--upgrade', '--disable-pip-version-check'] + SHARED_PACKAGES
    try:
        subprocess.run(cmd, check=True)
        with open(marker, 'w') as f:
            f.write(str(datetime.now()))
        print("[libs] ✅ Shared libraries installed!")
    except Exception as e:
        print(f"[libs] ⚠️ Install failed: {e}")

# ============================================
# TEMPLATE DEFAULTS
# ============================================
def ensure_template_defaults():
    main_py = os.path.join(TEMPLATES_BOT, 'main.py')
    if not os.path.exists(main_py):
        with open(main_py, 'w', encoding='utf-8') as f:
            f.write('''import time
print("Bot started on JUBAYER HOSTING")
i=0
while True:
    i+=1
    print(f"[{time.strftime('%I:%M:%S %p')}] Heartbeat #{i}")
    time.sleep(5)
''')
    req = os.path.join(TEMPLATES_BOT, 'requirements.txt')
    if not os.path.exists(req):
        with open(req, 'w', encoding='utf-8') as f:
            f.write('\n'.join(SHARED_PACKAGES) + '\n')
    acc = os.path.join(TEMPLATES_BOT, 'accounts.json')
    if not os.path.exists(acc):
        with open(acc, 'w', encoding='utf-8') as f:
            f.write('[\n  { "uid": "", "password": "" }\n]\n')

# ============================================
# JSON STORAGE
# ============================================
def load_config():
    if not os.path.exists(CONFIG_FILE):
        d = {'username': 'admin',
             'password_hash': hashlib.sha256('admin123'.encode()).hexdigest()}
        save_config(d); return d
    with open(CONFIG_FILE) as f: return json.load(f)

def save_config(d):
    with open(CONFIG_FILE, 'w') as f: json.dump(d, f, indent=4)

def load_servers():
    if not os.path.exists(SERVERS_FILE): return {'servers': []}
    with open(SERVERS_FILE) as f: return json.load(f)

def save_servers(d):
    with open(SERVERS_FILE, 'w') as f: json.dump(d, f, indent=4)

def get_server(sid):
    for s in load_servers()['servers']:
        if s['id'] == sid: return s
    return None

def update_server(sid, patch):
    d = load_servers()
    for s in d['servers']:
        if s['id'] == sid: s.update(patch); break
    save_servers(d)

def verify_user_login(u, p):
    c = load_config()
    return u == c.get('username') and \
           hashlib.sha256(p.encode()).hexdigest() == c.get('password_hash')

def verify_master_login(u, p):
    return u == MASTER_USERNAME and \
           hashlib.sha256(p.encode()).hexdigest() == MASTER_PASSWORD_HASH

def login_required(f):
    @wraps(f)
    def deco(*a, **k):
        if 'logged_in' not in session: return redirect(url_for('login'))
        return f(*a, **k)
    return deco

def safe_join(base, sub):
    p = os.path.abspath(os.path.join(base, sub))
    if not p.startswith(os.path.abspath(base)): return None
    return p

def server_folder(sid):
    s = get_server(sid)
    if not s: return None
    return os.path.join(SERVERS_DIR, s['folder'])

# ============================================
# LOG PARSER
# ============================================
def parse_stats_from_log(folder):
    st = {'nickname': '—', 'level': 0, 'exp_total': 0, 'exp_gained': 0, 'uid': '—'}
    lf = os.path.join(folder, 'output.log')
    if not os.path.exists(lf): return st
    nick_re = re.compile(r'\[PROFILE\]\s+(.+?)\s+\|\s+Lvl\s+(\d+)')
    exp_re  = re.compile(r'EXP\s+\+(\d+)\s*\|\s*Total\s+\+?(\d+)\s*\|\s*Lvl\s+(\d+)')
    uid_re  = re.compile(r'UID[=:\s]+(\d{6,})')
    try:
        with open(lf, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                m = nick_re.search(line)
                if m:
                    st['nickname'] = m.group(1).strip()
                    st['level'] = max(st['level'], int(m.group(2)))
                m = exp_re.search(line)
                if m:
                    st['exp_gained'] = int(m.group(1))
                    st['exp_total']  = int(m.group(2))
                    st['level']      = int(m.group(3))
                m = uid_re.search(line)
                if m: st['uid'] = m.group(1)
    except Exception: pass
    return st

# ============================================
# CREATE SERVER
# ============================================
def create_server_dir(sid):
    folder = os.path.join(SERVERS_DIR, sid)
    os.makedirs(folder, exist_ok=True)
    if os.path.exists(TEMPLATES_BOT):
        for item in os.listdir(TEMPLATES_BOT):
            if item.startswith('.'): continue
            src = os.path.join(TEMPLATES_BOT, item)
            dst = os.path.join(folder, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
    acc = os.path.join(folder, 'accounts.json')
    if not os.path.exists(acc):
        open(acc, 'w').write('[\n  { "uid": "", "password": "" }\n]\n')
    return folder

# ============================================
# RUN BOT
# ============================================
def kill_pid(pid):
    try:
        if sys.platform == 'win32':
            subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True)
        else:
            os.kill(pid, 15)
    except Exception: pass

def run_bot_server(server_id):
    s = get_server(server_id)
    if not s: return None, "Server not found"

    folder    = os.path.join(SERVERS_DIR, s['folder'])
    main_file = s.get('main_file', 'main.py')
    req_file  = s.get('requirements_file', 'requirements.txt')
    main_path = os.path.join(folder, main_file)
    req_path  = os.path.join(folder, req_file)
    log_file  = os.path.join(folder, 'output.log')

    if not os.path.exists(main_path):
        return None, f"{main_file} not found"

    open(log_file, 'w').close()
    py = sys.executable
    ts = lambda: datetime.now().strftime('%I:%M:%S %p')

    def log(m):
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(m + '\n'); f.flush()

    log(f"[{ts()}] Checking rate limit...")
    log(f"[{ts()}] Rate limit: {s.get('cpu_limit', 90)}%")
    log("")

    # pip install → shared_libs
    if os.path.exists(req_path):
        with open(req_path) as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith('#')]
        if lines:
            log(f"[{ts()}] Run: pip install -r {req_file}")
            log("")
            try:
                proc = subprocess.Popen(
                    [py, '-m', 'pip', 'install', '-r', os.path.abspath(req_path),
                     '--target', os.path.abspath(SHARED_LIBS),
                     '--upgrade', '--disable-pip-version-check'],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1
                )
                for line in iter(proc.stdout.readline, ''):
                    if line.strip(): log(f"[{ts()}] {line.rstrip()}")
                proc.wait()
                log("")
                log(f"[{ts()}] Requirements installation complete!")
            except Exception as e:
                log(f"[{ts()}] pip error: {e}")

    log("")
    log(f"[{ts()}] Run: python {main_file}")
    log(f"[{ts()}] Python {sys.version.split()[0]}")
    log("")

    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUNBUFFERED'] = '1'
    env['TERM'] = 'xterm'
    existing = env.get('PYTHONPATH', '')
    env['PYTHONPATH'] = os.path.abspath(SHARED_LIBS) + (os.pathsep + existing if existing else '')

    try:
        proc = subprocess.Popen(
            [py, os.path.abspath(main_path)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=folder, text=True, encoding='utf-8',
            errors='replace', bufsize=1, env=env
        )
        log(f"[{ts()}] Server started (PID: {proc.pid})")

        def stream():
            try:
                with open(log_file, 'a', encoding='utf-8') as f:
                    while True:
                        line = proc.stdout.readline()
                        if not line and proc.poll() is not None: break
                        if line:
                            f.write(f"[{datetime.now().strftime('%I:%M:%S %p')}] {line.rstrip()}\n")
                            f.flush()
            except Exception: pass
        threading.Thread(target=stream, daemon=True).start()

        def monitor():
            proc.wait()
            time.sleep(2)
            cur = get_server(server_id) or {}
            if cur.get('stopped_by_user') or cur.get('rate_limit_exceeded'): return
            new_pid, err = run_bot_server(server_id)
            if new_pid:
                update_server(server_id, {
                    'status': 'running', 'pid': new_pid,
                    'started_at': str(datetime.now())
                })
        threading.Thread(target=monitor, daemon=True).start()

        return proc.pid, None
    except Exception as e:
        log(f"[{ts()}] Error: {e}")
        return None, str(e)

# ============================================
# BASE CSS (dark theme)
# ============================================
BASE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0a0e14;color:#e6edf3;font-family:'Segoe UI',system-ui,-apple-system,sans-serif;
     margin:0;padding:20px;font-size:14px;line-height:1.5;min-height:100vh}
a{color:#58a6ff;text-decoration:none}
a:hover{text-decoration:underline}
h1{color:#58a6ff;margin:0 0 18px;font-size:24px;font-weight:700;letter-spacing:-.5px}
h3{color:#58a6ff;margin:0 0 10px;font-size:16px}
.btn{background:linear-gradient(135deg,#238636,#2ea043);color:#fff;padding:9px 18px;
     border:none;border-radius:8px;font-weight:600;cursor:pointer;font-size:13px;
     display:inline-flex;align-items:center;gap:6px;transition:.15s;font-family:inherit}
.btn:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(46,160,67,.3)}
.btn:active{transform:translateY(0)}
.btn.red{background:linear-gradient(135deg,#da3633,#f85149)}
.btn.red:hover{box-shadow:0 4px 12px rgba(248,81,73,.3)}
.btn.gray{background:#21262d;color:#e6edf3}
.btn.gray:hover{background:#30363d;box-shadow:none}
.btn.blue{background:linear-gradient(135deg,#1f6feb,#388bfd)}
.btn.blue:hover{box-shadow:0 4px 12px rgba(56,139,253,.3)}
.btn.small{padding:5px 10px;font-size:11px}
input,textarea,select{width:100%;padding:10px 12px;background:#0d1117;border:1px solid #30363d;
     color:#e6edf3;border-radius:8px;margin:6px 0;font-family:inherit;font-size:13px;
     transition:.15s}
input:focus,textarea:focus,select:focus{outline:none;border-color:#58a6ff;box-shadow:0 0 0 3px rgba(88,166,255,.15)}
textarea{font-family:'Consolas','Monaco',monospace;resize:vertical;min-height:80px}
.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;
        flex-wrap:wrap;gap:12px;padding-bottom:16px;border-bottom:1px solid #21262d}
.topbar h1{margin:0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
.card{background:linear-gradient(180deg,#161b22,#0d1117);border:1px solid #30363d;
      border-radius:14px;padding:18px;transition:.2s;position:relative;overflow:hidden}
.card:hover{border-color:#58a6ff;transform:translateY(-2px);box-shadow:0 8px 24px rgba(0,0,0,.3)}
.card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;
              background:linear-gradient(90deg,#58a6ff,#3fb950);opacity:0;transition:.2s}
.card:hover::before{opacity:1}
.stat{display:flex;justify-content:space-between;padding:5px 0;font-size:13px;border-bottom:1px solid #21262d}
.stat:last-child{border-bottom:none}
.stat span:first-child{color:#8b949e;font-weight:500}
.stat span:last-child{font-weight:600}
.badge{padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;
       letter-spacing:.3px;text-transform:uppercase}
.badge.run{background:rgba(63,185,80,.15);color:#3fb950;border:1px solid rgba(63,185,80,.3)}
.badge.stop{background:rgba(248,81,73,.15);color:#f85149;border:1px solid rgba(248,81,73,.3)}
.row{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;align-items:center}
pre{background:#010409;color:#c9d1d9;padding:16px;border-radius:10px;
    max-height:540px;overflow:auto;font-size:12.5px;line-height:1.6;
    border:1px solid #21262d;white-space:pre-wrap;word-break:break-word;
    font-family:'Consolas','Monaco',monospace;margin:0}
pre::-webkit-scrollbar{width:10px;height:10px}
pre::-webkit-scrollbar-track{background:#010409}
pre::-webkit-scrollbar-thumb{background:#30363d;border-radius:5px}
pre::-webkit-scrollbar-thumb:hover{background:#58a6ff}
.modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.8);
       backdrop-filter:blur(4px);align-items:center;justify-content:center;
       z-index:100;padding:16px;animation:fade .2s}
.modal.on{display:flex}
@keyframes fade{from{opacity:0}to{opacity:1}}
.modal-box{background:linear-gradient(180deg,#161b22,#0d1117);padding:26px;
           border-radius:14px;width:480px;max-width:96%;max-height:90vh;
           overflow:auto;border:1px solid #30363d;box-shadow:0 20px 60px rgba(0,0,0,.6);
           animation:slide .25s ease-out}
@keyframes slide{from{transform:translateY(20px);opacity:0}to{transform:translateY(0);opacity:1}}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:16px 0}
.metric{background:linear-gradient(180deg,#161b22,#0d1117);border:1px solid #30363d;
        border-radius:12px;padding:14px;transition:.2s;position:relative;overflow:hidden}
.metric::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;
                background:linear-gradient(180deg,#58a6ff,#3fb950);opacity:.5}
.metric:hover{border-color:#58a6ff;transform:translateY(-2px)}
.metric .lbl{color:#8b949e;font-size:11px;text-transform:uppercase;
             letter-spacing:.6px;font-weight:600}
.metric .val{font-size:19px;font-weight:700;margin-top:6px;color:#e6edf3}
.err{color:#f85149;margin:10px 0;padding:10px 14px;background:rgba(248,81,73,.1);
     border:1px solid rgba(248,81,73,.3);border-radius:8px;font-size:13px}
.ok{color:#3fb950;margin:10px 0;padding:10px 14px;background:rgba(63,185,80,.1);
    border:1px solid rgba(63,185,80,.3);border-radius:8px;font-size:13px}
.tabs{display:flex;gap:4px;border-bottom:1px solid #21262d;margin-bottom:18px;
      flex-wrap:wrap;padding-bottom:2px}
.tab{padding:10px 18px;cursor:pointer;border-bottom:2px solid transparent;
     color:#8b949e;font-weight:600;font-size:13px;transition:.15s;border-radius:6px 6px 0 0}
.tab:hover{color:#e6edf3;background:rgba(88,166,255,.05)}
.tab.active{color:#58a6ff;border-bottom-color:#58a6ff;background:rgba(88,166,255,.05)}
.file-row{display:grid;grid-template-columns:1fr auto auto;align-items:center;
          padding:10px 14px;border-bottom:1px solid #21262d;font-size:13px;gap:12px;
          transition:.15s}
.file-row:last-child{border-bottom:none}
.file-row:hover{background:rgba(88,166,255,.05)}
.acc-row{display:grid;grid-template-columns:1fr 2fr auto 30px;gap:10px;
         margin:8px 0;align-items:center}
.acc-row input{margin:0}
.acc-row .num{color:#8b949e;font-size:12px;text-align:center;font-weight:600}
.drop{border:2px dashed #30363d;border-radius:12px;padding:30px;text-align:center;
      color:#8b949e;cursor:pointer;transition:.2s;background:#0d1117}
.drop:hover,.drop.over{border-color:#58a6ff;background:rgba(88,166,255,.05);color:#58a6ff}
.login-box{max-width:420px;margin:80px auto;
           background:linear-gradient(180deg,#161b22,#0d1117);
           padding:36px;border-radius:16px;border:1px solid #30363d;
           box-shadow:0 20px 60px rgba(0,0,0,.5);animation:slide .3s ease-out}
.login-box h1{text-align:center;font-size:26px;margin-bottom:24px;
              background:linear-gradient(90deg,#58a6ff,#3fb950);
              -webkit-background-clip:text;-webkit-text-fill-color:transparent;
              background-clip:text}
.muted{color:#8b949e;font-size:12px}
"""

# ============================================
# LOGIN
# ============================================
LOGIN_HTML = """
<!DOCTYPE html><html><head><title>Login — JUBAYER HOSTING</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>""" + BASE_CSS + """</style></head><body>
<div class="login-box">
<h1>🚀 JUBAYER HOSTING</h1>
{% if error %}<div class="err">{{ error }}</div>{% endif %}
<form method="POST">
  <input name="username" placeholder="👤 Username" required autofocus>
  <input name="password" type="password" placeholder="🔒 Password" required>
  <button class="btn" style="width:100%;margin-top:12px;padding:13px;font-size:14px;justify-content:center">
    Login
  </button>
</form>
</div></body></html>
"""

# ============================================
# DASHBOARD
# ============================================
DASH_HTML = """
<!DOCTYPE html><html><head><title>Dashboard — JUBAYER HOSTING</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>""" + BASE_CSS + """</style></head><body>
<div class="topbar">
  <h1>🚀 JUBAYER HOSTING</h1>
  <div class="row" style="margin:0">
    <span class="muted">👤 {{ username }}</span>
    <a class="btn gray" href="{{ url_for('profile') }}">⚙ Profile</a>
    <a class="btn red" href="{{ url_for('logout') }}">Logout</a>
  </div>
</div>

<div class="row">
  <button class="btn" onclick="document.getElementById('cm').classList.add('on')">
    ➕ Create Server ({{ servers|length }}/{{ max_servers }})
  </button>
  <a class="btn blue" href="{{ url_for('templates_page') }}">🧩 Manage Templates</a>
</div>

<div class="grid" style="margin-top:20px">
  {% for s in servers %}
  <div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
      <h3 style="margin:0;font-size:17px">{{ s.name }}</h3>
      <span class="badge {{ 'run' if s.status=='running' else 'stop' }}">{{ s.status }}</span>
    </div>
    <div class="stat"><span>Nickname</span><span>{{ s.nickname }}</span></div>
    <div class="stat"><span>Level</span><span>Lvl {{ s.level }}</span></div>
    <div class="stat"><span>Exp Total</span><span style="color:#3fb950">+{{ s.exp_total }}</span></div>
    <div class="stat"><span>Server ID</span><span class="muted" style="font-size:11px">{{ s.id }}</span></div>
    <div class="row" style="margin-top:14px">
      <a class="btn" href="{{ url_for('server_page', sid=s.id) }}">📂 Open</a>
      <button class="btn gray" onclick="delSrv('{{ s.id }}','{{ s.name }}')">🗑 Delete</button>
    </div>
  </div>
  {% endfor %}
  {% if not servers %}
  <div class="card" style="grid-column:1/-1;text-align:center;padding:50px">
    <div style="font-size:48px;margin-bottom:10px">📦</div>
    <h3 style="color:#8b949e;font-weight:400">Koi server nahi hai</h3>
    <p class="muted">Upar "Create Server" button dabao</p>
  </div>
  {% endif %}
</div>

<div class="modal" id="cm"><div class="modal-box">
  <h3>➕ Create New Server</h3>
  <p class="muted" style="margin-bottom:12px">Server name choose karo (jaise: Papa Bot)</p>
  <input id="sname" placeholder="Server name" autofocus>
  <div class="row" style="margin-top:16px">
    <button class="btn" onclick="createSrv()">✓ Create</button>
    <button class="btn gray" onclick="document.getElementById('cm').classList.remove('on')">Cancel</button>
  </div>
</div></div>

<script>
async function createSrv(){
  const name = document.getElementById('sname').value.trim() || 'Server';
  const r = await fetch('/api/servers/create', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({name})});
  const j = await r.json();
  if (j.success) location.reload(); else alert(j.error||'Failed');
}
async function delSrv(id,name){
  if(!confirm('Delete "'+name+'" ?')) return;
  const r = await fetch('/api/servers/delete', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({id})});
  const j = await r.json();
  if (j.success) location.reload(); else alert(j.error);
}
</script></body></html>
"""

# ============================================
# SERVER PAGE
# ============================================
SERVER_HTML = """
<!DOCTYPE html><html><head><title>{{ server.name }} — JUBAYER HOSTING</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>""" + BASE_CSS + """</style></head><body>
<a href="{{ url_for('dashboard') }}">← Back to Dashboard</a>
<h1 style="margin-top:12px">{{ server.name }} <span id="badge" class="badge stop">…</span></h1>

<div class="row">
  <button class="btn" onclick="runSrv()">▶ Run</button>
  <button class="btn red" onclick="stopSrv()">■ Stop</button>
  <button class="btn gray" onclick="clearLogs()">🧹 Clear Logs</button>
  <button class="btn blue" onclick="downloadServer()">⬇ Download .zip</button>
</div>

<div class="metrics">
  <div class="metric"><div class="lbl">CPU</div><div class="val" id="cpu">0%</div></div>
  <div class="metric"><div class="lbl">RAM</div><div class="val" id="ram">0 MB</div></div>
  <div class="metric"><div class="lbl">Net In</div><div class="val" id="nin">0 KB</div></div>
  <div class="metric"><div class="lbl">Net Out</div><div class="val" id="nout">0 KB</div></div>
  <div class="metric"><div class="lbl">Uptime</div><div class="val" id="uptime">—</div></div>
  <div class="metric"><div class="lbl">Nickname</div><div class="val" id="nick">—</div></div>
  <div class="metric"><div class="lbl">Level</div><div class="val" id="lvl">Lvl 0</div></div>
  <div class="metric"><div class="lbl">Exp Total</div><div class="val" id="exp" style="color:#3fb950">+0</div></div>
  <div class="metric"><div class="lbl">Last Gain</div><div class="val" id="expg" style="color:#3fb950">+0</div></div>
</div>

<div class="tabs">
  <div class="tab active" data-t="logs" onclick="tab('logs')">📜 Logs</div>
  <div class="tab" data-t="files" onclick="tab('files')">📁 Files</div>
  <div class="tab" data-t="accounts" onclick="tab('accounts')">👤 Accounts</div>
  <div class="tab" data-t="startup" onclick="tab('startup')">⚙ Startup</div>
</div>

<div id="tab-logs"><pre id="logs">Loading…</pre></div>

<div id="tab-files" style="display:none">
  <div class="drop" id="drop" onclick="document.getElementById('finput').click()">
    📤 Click ya files drag karo — current folder me upload hoga
    <input type="file" id="finput" multiple style="display:none" onchange="doUpload(this.files)">
  </div>
  <div class="row" style="margin-top:14px">
    <button class="btn" onclick="newFile()">➕ New File</button>
    <button class="btn" onclick="newFolder()">📁 New Folder</button>
    <button class="btn gray" onclick="document.getElementById('zipin').click()">📦 Upload .zip & extract</button>
    <input type="file" id="zipin" accept=".zip" style="display:none" onchange="uploadZip(this.files[0])">
  </div>
  <div id="pathInfo" class="muted" style="margin:10px 0"></div>
  <div class="card" style="padding:0" id="fileList"></div>
</div>

<div id="tab-accounts" style="display:none">
  <p class="muted" style="margin-bottom:14px">Yaha se <code>accounts.json</code> me UID + Password add/edit/delete karo.</p>
  <div id="accList"></div>
  <div class="row" style="margin-top:14px">
    <button class="btn" onclick="addAcc()">➕ Add Account</button>
    <button class="btn blue" onclick="saveAcc()">💾 Save accounts.json</button>
  </div>
  <div id="accMsg"></div>
</div>

<div id="tab-startup" style="display:none">
  <label class="muted">Main File</label>
  <input id="mainFile" placeholder="main.py">
  <label class="muted">Requirements File</label>
  <input id="reqFile" placeholder="requirements.txt">
  <button class="btn" style="margin-top:12px" onclick="saveStartup()">💾 Save</button>
  <div id="startMsg"></div>
</div>

<script>
const SID = "{{ server.id }}";
let currentFolder = '';

function tab(name){
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active', t.dataset.t===name));
  ['logs','files','accounts','startup'].forEach(n=>{
    document.getElementById('tab-'+n).style.display = (n===name?'block':'none');
  });
  if (name==='files') loadFiles();
  if (name==='accounts') loadAccounts();
  if (name==='startup') loadStartup();
}

async function stats(){
  try{
    const j = await (await fetch(`/api/server/${SID}/stats`)).json();
    cpu.textContent=j.cpu; ram.textContent=j.ram;
    nin.textContent=j.net_in; nout.textContent=j.net_out;
    uptime.textContent=j.uptime; nick.textContent=j.nickname;
    lvl.textContent='Lvl '+j.level; exp.textContent='+'+j.exp_total;
    expg.textContent='+'+j.exp_gained;
    const b=document.getElementById('badge');
    b.textContent=j.status;
    b.className='badge '+(j.status==='running'?'run':'stop');
  }catch(e){}
}
async function logs(){
  try{
    const j = await (await fetch(`/api/server/${SID}/logs`)).json();
    const el=document.getElementById('logs');
    const bottom=el.scrollTop+el.clientHeight>=el.scrollHeight-40;
    el.textContent=j.logs||'(empty)';
    if(bottom) el.scrollTop=el.scrollHeight;
  }catch(e){}
}
async function runSrv(){ await fetch(`/api/server/${SID}/run`,{method:'POST'}); stats(); }
async function stopSrv(){ await fetch(`/api/server/${SID}/stop`,{method:'POST'}); stats(); }
async function clearLogs(){
  if(!confirm('Clear logs?')) return;
  await fetch(`/api/server/${SID}/clear_logs`,{method:'POST'});
  logs();
}
function downloadServer(){ window.location = `/api/server/${SID}/download`; }

async function loadFiles(){
  const j = await (await fetch(`/api/server/${SID}/files?folder=${encodeURIComponent(currentFolder)}`)).json();
  document.getElementById('pathInfo').textContent = '📁 Path: /'+(currentFolder||'');
  let html = '';
  if (currentFolder){
    const up = currentFolder.split('/').slice(0,-1).join('/');
    html += `<div class="file-row"><span>📁 <a href="#" onclick="cd('${up}')">..</a></span><span></span><span></span></div>`;
  }
  (j.files||[]).forEach(f=>{
    const full = currentFolder ? currentFolder+'/'+f.name : f.name;
    const icon = f.is_dir ? '📁' : (f.name.endsWith('.py')?'🐍':(f.name.endsWith('.json')?'📋':(f.name.endsWith('.zip')?'📦':'📄')));
    if (f.is_dir){
      html += `<div class="file-row">
        <span>${icon} <a href="#" onclick="cd('${full}')">${f.name}</a></span>
        <span class="muted" style="font-size:11px">${f.modified}</span>
        <span>
          <button class="btn gray small" onclick="renFile('${full}')">Rename</button>
          <button class="btn red small" onclick="delFile('${full}')">Del</button>
        </span>
      </div>`;
    } else {
      html += `<div class="file-row">
        <span>${icon} <a href="#" onclick="editFile('${full}')">${f.name}</a></span>
        <span class="muted" style="font-size:11px">${(f.size/1024).toFixed(1)} KB · ${f.modified}</span>
        <span>
          ${f.name.endsWith('.zip')?`<button class="btn blue small" onclick="unzip('${full}')">Unzip</button>`:''}
          <button class="btn gray small" onclick="renFile('${full}')">Rename</button>
          <button class="btn red small" onclick="delFile('${full}')">Del</button>
        </span>
      </div>`;
    }
  });
  if (!html) html = '<div class="file-row"><span class="muted">(empty folder)</span><span></span><span></span></div>';
  document.getElementById('fileList').innerHTML = html;
}
function cd(f){ currentFolder = f; loadFiles(); }

const drop = document.getElementById('drop');
['dragover','dragenter'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.add('over')}));
['dragleave','drop'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove('over')}));
drop.addEventListener('drop', e=>{ if(e.dataTransfer.files.length) doUpload(e.dataTransfer.files); });

async function doUpload(files){
  if(!files || !files.length) return;
  const fd = new FormData();
  for (const f of files) fd.append('files', f);
  fd.append('folder', currentFolder);
  const r = await fetch(`/api/server/${SID}/upload`, {method:'POST', body: fd});
  const j = await r.json();
  if (j.success) { alert('Uploaded: '+(j.uploaded||[]).join(', ')); loadFiles(); }
  else alert(j.error||'Failed');
}
async function uploadZip(file){
  if(!file) return;
  const fd = new FormData();
  fd.append('file', file);
  fd.append('folder', currentFolder);
  const r = await fetch(`/api/server/${SID}/upload_zip`, {method:'POST', body: fd});
  const j = await r.json();
  if (j.success) { alert('Extracted!'); loadFiles(); }
  else alert(j.error||'Failed');
}
async function unzip(name){
  const r = await fetch(`/api/server/${SID}/unzip`, {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({filename:name})});
  const j = await r.json();
  if (j.success) loadFiles(); else alert(j.error||'Failed');
}
async function delFile(name){
  if(!confirm('Delete '+name+'?')) return;
  const r = await fetch(`/api/server/${SID}/file`, {method:'DELETE',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({filename:name})});
  const j = await r.json();
  if (j.success) loadFiles(); else alert(j.error||'Failed');
}
async function renFile(oldName){
  const newName = prompt('New name:', oldName);
  if(!newName || newName===oldName) return;
  const r = await fetch(`/api/server/${SID}/rename`, {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({old_name:oldName, new_name:newName})});
  const j = await r.json();
  if (j.success) loadFiles(); else alert(j.error||'Failed');
}
async function newFile(){
  const name = prompt('File name (e.g. extra.py):');
  if(!name) return;
  const full = currentFolder ? currentFolder+'/'+name : name;
  const r = await fetch(`/api/server/${SID}/file`, {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({filename:full, content:''})});
  const j = await r.json();
  if (j.success) { loadFiles(); editFile(full); } else alert(j.error);
}
async function newFolder(){
  const name = prompt('Folder name:');
  if(!name) return;
  const full = currentFolder ? currentFolder+'/'+name : name;
  const r = await fetch(`/api/server/${SID}/mkdir`, {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({folder:full})});
  const j = await r.json();
  if (j.success) loadFiles(); else alert(j.error);
}
async function editFile(name){
  const j = await (await fetch(`/api/server/${SID}/file?filename=${encodeURIComponent(name)}`)).json();
  if (j.error) return alert(j.error);
  const modal = document.createElement('div');
  modal.className='modal on';
  modal.innerHTML = `<div class="modal-box" style="width:760px">
    <h3>📝 ${name}</h3>
    <textarea id="ed" style="height:440px">${(j.content||'').replace(/</g,'&lt;')}</textarea>
    <div class="row" style="margin-top:14px">
      <button class="btn" id="sv">💾 Save</button>
      <button class="btn gray" id="cl">Close</button>
    </div>
  </div>`;
  document.body.appendChild(modal);
  modal.querySelector('#sv').onclick = async ()=>{
    const content = modal.querySelector('#ed').value;
    const r = await fetch(`/api/server/${SID}/file`, {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({filename:name, content})});
    const jj = await r.json();
    if (jj.success) { alert('Saved!'); modal.remove(); loadFiles(); }
    else alert(jj.error||'Failed');
  };
  modal.querySelector('#cl').onclick = ()=>modal.remove();
}

let accData = [];
async function loadAccounts(){
  const j = await (await fetch(`/api/server/${SID}/accounts`)).json();
  accData = j.accounts || [];
  renderAcc();
}
function renderAcc(){
  const box = document.getElementById('accList');
  if (!accData.length){
    box.innerHTML = '<div class="card" style="text-align:center;padding:30px;color:#8b949e">No accounts yet</div>';
    return;
  }
  box.innerHTML = accData.map((a,i)=>`
    <div class="acc-row">
      <input value="${a.uid||''}" oninput="accData[${i}].uid=this.value" placeholder="UID">
      <input value="${a.password||''}" oninput="accData[${i}].password=this.value" placeholder="Password / Token">
      <button class="btn red small" onclick="delAcc(${i})">🗑</button>
      <span class="num">#${i+1}</span>
    </div>`).join('');
}
function addAcc(){ accData.push({uid:'', password:''}); renderAcc(); }
function delAcc(i){ accData.splice(i,1); renderAcc(); }
async function saveAcc(){
  const r = await fetch(`/api/server/${SID}/accounts`, {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({accounts: accData})});
  const j = await r.json();
  document.getElementById('accMsg').innerHTML =
    j.success ? '<div class="ok">✅ Saved accounts.json</div>' : '<div class="err">❌ '+j.error+'</div>';
}

async function loadStartup(){
  const j = await (await fetch(`/api/server/${SID}/startup`)).json();
  document.getElementById('mainFile').value = j.main_file || 'main.py';
  document.getElementById('reqFile').value  = j.requirements_file || 'requirements.txt';
}
async function saveStartup(){
  const r = await fetch(`/api/server/${SID}/startup`, {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      main_file: document.getElementById('mainFile').value,
      requirements_file: document.getElementById('reqFile').value
    })});
  const j = await r.json();
  document.getElementById('startMsg').innerHTML =
    j.success ? '<div class="ok">✅ Saved</div>' : '<div class="err">❌ '+j.error+'</div>';
}

setInterval(stats, 2000);
setInterval(logs, 2000);
stats(); logs();
</script></body></html>
"""

# ============================================
# TEMPLATES PAGE
# ============================================
TEMPLATES_HTML = """
<!DOCTYPE html><html><head><title>Templates — JUBAYER HOSTING</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>""" + BASE_CSS + """</style></head><body>
<a href="{{ url_for('dashboard') }}">← Back to Dashboard</a>
<h1 style="margin-top:12px">🧩 Template Files Manager</h1>

<p class="muted" style="margin-bottom:16px">
  Ye files <code>templates_bot/</code> folder me hain. Naya server banate waqt ye sab auto-copy hongi.
</p>

<div class="drop" id="drop" onclick="document.getElementById('finput').click()">
  📤 Click ya files drag karo — templates_bot/ me upload hoga
  <input type="file" id="finput" multiple style="display:none" onchange="doUpload(this.files)">
</div>

<div class="row" style="margin-top:14px">
  <button class="btn" onclick="newFile()">➕ New File</button>
  <button class="btn" onclick="newFolder()">📁 New Folder</button>
  <button class="btn gray" onclick="document.getElementById('zipin').click()">📦 Upload .zip & extract</button>
  <input type="file" id="zipin" accept=".zip" style="display:none" onchange="uploadZip(this.files[0])">
</div>

<div id="pathInfo" class="muted" style="margin:10px 0"></div>
<div class="card" style="padding:0" id="fileList">Loading…</div>

<script>
let currentFolder = '';

async function loadFiles(){
  const j = await (await fetch(`/api/templates/files?folder=${encodeURIComponent(currentFolder)}`)).json();
  document.getElementById('pathInfo').textContent = '📁 templates_bot/ '+(currentFolder||'');
  let html = '';
  if (currentFolder){
    const up = currentFolder.split('/').slice(0,-1).join('/');
    html += `<div class="file-row"><span>📁 <a href="#" onclick="cd('${up}')">..</a></span><span></span><span></span></div>`;
  }
  (j.files||[]).forEach(f=>{
    const full = currentFolder ? currentFolder+'/'+f.name : f.name;
    const icon = f.is_dir ? '📁' : (f.name.endsWith('.py')?'🐍':(f.name.endsWith('.json')?'📋':(f.name.endsWith('.zip')?'📦':'📄')));
    if (f.is_dir){
      html += `<div class="file-row">
        <span>${icon} <a href="#" onclick="cd('${full}')">${f.name}</a></span>
        <span class="muted" style="font-size:11px">${f.modified}</span>
        <span>
          <button class="btn gray small" onclick="renFile('${full}')">Rename</button>
          <button class="btn red small" onclick="delFile('${full}')">Del</button>
        </span>
      </div>`;
    } else {
      html += `<div class="file-row">
        <span>${icon} <a href="#" onclick="editFile('${full}')">${f.name}</a></span>
        <span class="muted" style="font-size:11px">${(f.size/1024).toFixed(1)} KB · ${f.modified}</span>
        <span>
          ${f.name.endsWith('.zip')?`<button class="btn blue small" onclick="unzip('${full}')">Unzip</button>`:''}
          <button class="btn gray small" onclick="renFile('${full}')">Rename</button>
          <button class="btn red small" onclick="delFile('${full}')">Del</button>
        </span>
      </div>`;
    }
  });
  if (!html) html = '<div class="file-row"><span class="muted">(empty folder)</span><span></span><span></span></div>';
  document.getElementById('fileList').innerHTML = html;
}
function cd(f){ currentFolder = f; loadFiles(); }

const drop = document.getElementById('drop');
['dragover','dragenter'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.add('over')}));
['dragleave','drop'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove('over')}));
drop.addEventListener('drop', e=>{ if(e.dataTransfer.files.length) doUpload(e.dataTransfer.files); });

async function doUpload(files){
  if(!files || !files.length) return;
  const fd = new FormData();
  for (const f of files) fd.append('files', f);
  fd.append('folder', currentFolder);
  const r = await fetch('/api/templates/upload', {method:'POST', body: fd});
  const j = await r.json();
  if (j.success) { alert('Uploaded: '+(j.uploaded||[]).join(', ')); loadFiles(); }
  else alert(j.error||'Failed');
}
async function uploadZip(file){
  if(!file) return;
  const fd = new FormData();
  fd.append('file', file);
  fd.append('folder', currentFolder);
  const r = await fetch('/api/templates/upload_zip', {method:'POST', body: fd});
  const j = await r.json();
  if (j.success) { alert('Extracted!'); loadFiles(); }
  else alert(j.error||'Failed');
}
async function unzip(name){
  const r = await fetch('/api/templates/unzip', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({filename:name})});
  const j = await r.json();
  if (j.success) loadFiles(); else alert(j.error||'Failed');
}
async function delFile(name){
  if(!confirm('Delete '+name+'?')) return;
  const r = await fetch('/api/templates/file', {method:'DELETE',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({filename:name})});
  const j = await r.json();
  if (j.success) loadFiles(); else alert(j.error||'Failed');
}
async function renFile(oldName){
  const newName = prompt('New name:', oldName);
  if(!newName || newName===oldName) return;
  const r = await fetch('/api/templates/rename', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({old_name:oldName, new_name:newName})});
  const j = await r.json();
  if (j.success) loadFiles(); else alert(j.error||'Failed');
}
async function newFile(){
  const name = prompt('File name (e.g. extra.py):');
  if(!name) return;
  const full = currentFolder ? currentFolder+'/'+name : name;
  const r = await fetch('/api/templates/file', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({filename:full, content:''})});
  const j = await r.json();
  if (j.success) { loadFiles(); editFile(full); } else alert(j.error);
}
async function newFolder(){
  const name = prompt('Folder name:');
  if(!name) return;
  const full = currentFolder ? currentFolder+'/'+name : name;
  const r = await fetch('/api/templates/mkdir', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({folder:full})});
  const j = await r.json();
  if (j.success) loadFiles(); else alert(j.error);
}
async function editFile(name){
  const j = await (await fetch(`/api/templates/file?filename=${encodeURIComponent(name)}`)).json();
  if (j.error) return alert(j.error);
  const modal = document.createElement('div');
  modal.className='modal on';
  modal.innerHTML = `<div class="modal-box" style="width:760px">
    <h3>📝 ${name}</h3>
    <textarea id="ed" style="height:440px">${(j.content||'').replace(/</g,'&lt;')}</textarea>
    <div class="row" style="margin-top:14px">
      <button class="btn" id="sv">💾 Save</button>
      <button class="btn gray" id="cl">Close</button>
    </div>
  </div>`;
  document.body.appendChild(modal);
  modal.querySelector('#sv').onclick = async ()=>{
    const content = modal.querySelector('#ed').value;
    const r = await fetch('/api/templates/file', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({filename:name, content})});
    const jj = await r.json();
    if (jj.success) { alert('Saved!'); modal.remove(); loadFiles(); }
    else alert(jj.error||'Failed');
  };
  modal.querySelector('#cl').onclick = ()=>modal.remove();
}

loadFiles();
</script></body></html>
"""

# ============================================
# PROFILE
# ============================================
PROFILE_HTML = """
<!DOCTYPE html><html><head><title>Profile — JUBAYER HOSTING</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>""" + BASE_CSS + """</style></head><body>
<a href="{{ url_for('dashboard') }}">← Back</a>
<h1 style="margin-top:12px">👤 Profile</h1>
{% if error %}<div class="err">{{ error }}</div>{% endif %}
{% if success %}<div class="ok">{{ success }}</div>{% endif %}
<form method="POST" style="max-width:420px">
  <label class="muted">Username</label>
  <input name="new_username" value="{{ current_username }}">
  <label class="muted">Current Password *</label>
  <input name="current_password" type="password" required>
  <label class="muted">New Password (blank = no change)</label>
  <input name="new_password" type="password">
  <button class="btn" style="width:100%;margin-top:14px;justify-content:center">💾 Save Changes</button>
</form>
</body></html>
"""

# ============================================
# PAGE ROUTES
# ============================================
@app.route('/')
def index():
    return redirect(url_for('dashboard') if 'logged_in' in session else url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username','').strip()
        p = request.form.get('password','').strip()
        if verify_master_login(u,p):
            session.update(logged_in=True, user_type='master', username=u)
            return redirect(url_for('dashboard'))
        if verify_user_login(u,p):
            session.update(logged_in=True, user_type='user', username=u)
            return redirect(url_for('dashboard'))
        return render_template_string(LOGIN_HTML, error="Invalid credentials!")
    return render_template_string(LOGIN_HTML, error=None)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    out = []
    for s in load_servers()['servers']:
        folder = os.path.join(SERVERS_DIR, s['folder'])
        st = parse_stats_from_log(folder)
        s2 = dict(s)
        s2['nickname']  = st['nickname']
        s2['level']     = st['level']
        s2['exp_total'] = st['exp_total']
        out.append(s2)
    return render_template_string(DASH_HTML,
        username=session.get('username'), user_type=session.get('user_type'),
        servers=out, max_servers=MAX_SERVERS)

@app.route('/server/<sid>')
@login_required
def server_page(sid):
    s = get_server(sid)
    if not s: return redirect(url_for('dashboard'))
    return render_template_string(SERVER_HTML, server=s)

@app.route('/templates')
@login_required
def templates_page():
    return render_template_string(TEMPLATES_HTML)

@app.route('/profile', methods=['GET','POST'])
@login_required
def profile():
    if request.method == 'POST':
        cur   = request.form.get('current_password','')
        new_p = request.form.get('new_password','')
        new_u = request.form.get('new_username','').strip()
        cfg = load_config()
        if hashlib.sha256(cur.encode()).hexdigest() != cfg.get('password_hash'):
            return render_template_string(PROFILE_HTML, error="Wrong current password",
                success=None, current_username=cfg.get('username'))
        if new_u and new_u != cfg.get('username'):
            cfg['username'] = new_u; session['username'] = new_u
        if new_p:
            cfg['password_hash'] = hashlib.sha256(new_p.encode()).hexdigest()
        save_config(cfg)
        return render_template_string(PROFILE_HTML, error=None,
            success="Updated!", current_username=cfg.get('username'))
    cfg = load_config()
    return render_template_string(PROFILE_HTML, error=None, success=None,
        current_username=cfg.get('username'))

# ============================================
# API — SERVERS
# ============================================
@app.route('/api/servers/create', methods=['POST'])
@login_required
def api_create_server():
    d = load_servers()
    if len(d['servers']) >= MAX_SERVERS:
        return jsonify({'error': f'Max {MAX_SERVERS} servers allowed!'}), 400
    name = (request.json.get('name') or 'Server').strip()[:30]
    sid = f"server_{uuid.uuid4().hex[:6]}"
    create_server_dir(sid)
    d['servers'].append({
        'id': sid, 'name': name, 'folder': sid,
        'status': 'stopped', 'pid': None, 'started_at': None,
        'main_file': 'main.py', 'requirements_file': 'requirements.txt',
        'cpu_limit': 90, 'stopped_by_user': False,
        'rate_limit_exceeded': False,
        'created_at': str(datetime.now())
    })
    save_servers(d)
    return jsonify({'success': True, 'id': sid})

@app.route('/api/servers/delete', methods=['POST'])
@login_required
def api_delete_server():
    sid = request.json.get('id')
    s = get_server(sid)
    if not s: return jsonify({'error': 'Not found'}), 404
    if s.get('pid'): kill_pid(s['pid'])
    shutil.rmtree(os.path.join(SERVERS_DIR, s['folder']), ignore_errors=True)
    d = load_servers()
    d['servers'] = [x for x in d['servers'] if x['id'] != sid]
    save_servers(d)
    return jsonify({'success': True})

# ============================================
# API — RUN / STOP / LOGS / STATS
# ============================================
@app.route('/api/server/<sid>/run', methods=['POST'])
@login_required
def api_run(sid):
    s = get_server(sid)
    if not s: return jsonify({'error': 'Not found'}), 404
    if s.get('status') == 'running': return jsonify({'error': 'Already running'})
    update_server(sid, {'stopped_by_user': False, 'rate_limit_exceeded': False})
    pid, err = run_bot_server(sid)
    if pid:
        update_server(sid, {'status':'running','pid':pid,
                            'started_at': str(datetime.now())})
        return jsonify({'success': True})
    return jsonify({'error': err}), 500

@app.route('/api/server/<sid>/stop', methods=['POST'])
@login_required
def api_stop(sid):
    s = get_server(sid)
    if not s: return jsonify({'error': 'Not found'}), 404
    if s.get('pid'): kill_pid(s['pid'])
    update_server(sid, {'status':'stopped','pid':None,'stopped_by_user':True})
    try:
        lf = os.path.join(SERVERS_DIR, s['folder'], 'output.log')
        with open(lf, 'a', encoding='utf-8') as f:
            f.write(f"\n[{datetime.now().strftime('%I:%M:%S %p')}] Server stopped by user\n")
    except Exception: pass
    return jsonify({'success': True})

@app.route('/api/server/<sid>/logs')
@login_required
def api_logs(sid):
    s = get_server(sid)
    if not s: return jsonify({'logs':''})
    lf = os.path.join(SERVERS_DIR, s['folder'], 'output.log')
    if os.path.exists(lf):
        with open(lf, 'r', encoding='utf-8', errors='ignore') as f:
            return jsonify({'logs': f.read()})
    return jsonify({'logs': ''})

@app.route('/api/server/<sid>/clear_logs', methods=['POST'])
@login_required
def api_clear_logs(sid):
    s = get_server(sid)
    if not s: return jsonify({'error':'Not found'}), 404
    try:
        open(os.path.join(SERVERS_DIR, s['folder'], 'output.log'), 'w').close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/server/<sid>/stats')
@login_required
def api_stats(sid):
    s = get_server(sid)
    if not s: return jsonify({'error':'Not found'}), 404
    folder = os.path.join(SERVERS_DIR, s['folder'])
    parsed = parse_stats_from_log(folder)
    cpu, ram, nin, nout, uptime = "0%", "0 MB", "0 KB", "0 KB", "—"

    if s.get('status')=='running' and s.get('pid'):
        try:
            p = psutil.Process(s['pid'])
            cpu = f"{p.cpu_percent(interval=0.3):.1f}%"
            mem = p.memory_info().rss / 1024 / 1024
            ram = f"{mem:.1f} MB" if mem < 1024 else f"{mem/1024:.2f} GB"
            io = p.io_counters()
            nin  = fmt_bytes(io.read_bytes)
            nout = fmt_bytes(io.write_bytes)
        except Exception: pass

    if s.get('status')=='running' and s.get('started_at'):
        try:
            st = datetime.strptime(s['started_at'], '%Y-%m-%d %H:%M:%S.%f')
            d = datetime.now() - st
            uptime = f"{d.days}d {d.seconds//3600}h {(d.seconds%3600)//60}m"
        except Exception: pass

    return jsonify({
        'status': s.get('status'),
        'cpu': cpu, 'ram': ram, 'net_in': nin, 'net_out': nout, 'uptime': uptime,
        'nickname': parsed['nickname'], 'level': parsed['level'],
        'exp_total': parsed['exp_total'], 'exp_gained': parsed['exp_gained'],
        'uid': parsed['uid'],
    })

def fmt_bytes(b):
    for u in ['B','KB','MB','GB','TB']:
        if b < 1024: return f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.2f} PB"

# ============================================
# API — SERVER FILES
# ============================================
@app.route('/api/server/<sid>/files')
@login_required
def api_files(sid):
    base = server_folder(sid)
    if not base: return jsonify({'files': []})
    folder = request.args.get('folder','')
    target = safe_join(base, folder)
    if not target or not os.path.exists(target):
        return jsonify({'files': []})
    out = []
    for it in sorted(os.listdir(target)):
        if it.startswith('.'): continue
        p = os.path.join(target, it)
        out.append({
            'name': it,
            'is_dir': os.path.isdir(p),
            'size': os.path.getsize(p) if os.path.isfile(p) else 0,
            'modified': datetime.fromtimestamp(os.path.getmtime(p)).strftime('%Y-%m-%d %H:%M')
        })
    return jsonify({'files': out})

@app.route('/api/server/<sid>/file', methods=['GET'])
@login_required
def api_get_file(sid):
    base = server_folder(sid)
    if not base: return jsonify({'error':'Not found'}), 404
    fp = safe_join(base, request.args.get('filename',''))
    if not fp or not os.path.isfile(fp):
        return jsonify({'error':'Not found'}), 404
    try:
        with open(fp, 'r', encoding='utf-8', errors='replace') as f:
            return jsonify({'content': f.read()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/server/<sid>/file', methods=['POST'])
@login_required
def api_save_file(sid):
    base = server_folder(sid)
    if not base: return jsonify({'error':'Not found'}), 404
    data = request.get_json() or {}
    fp = safe_join(base, data.get('filename',''))
    if not fp: return jsonify({'error':'Access denied'}), 403
    os.makedirs(os.path.dirname(fp) or base, exist_ok=True)
    with open(fp, 'w', encoding='utf-8') as f:
        f.write(data.get('content',''))
    return jsonify({'success': True})

@app.route('/api/server/<sid>/file', methods=['DELETE'])
@login_required
def api_del_file(sid):
    base = server_folder(sid)
    if not base: return jsonify({'error':'Not found'}), 404
    data = request.get_json() or {}
    fp = safe_join(base, data.get('filename',''))
    if not fp: return jsonify({'error':'Access denied'}), 403
    try:
        if os.path.isdir(fp): shutil.rmtree(fp)
        elif os.path.isfile(fp): os.remove(fp)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/server/<sid>/rename', methods=['POST'])
@login_required
def api_rename(sid):
    base = server_folder(sid)
    if not base: return jsonify({'error':'Not found'}), 404
    d = request.get_json() or {}
    old = safe_join(base, d.get('old_name',''))
    new = safe_join(base, d.get('new_name',''))
    if not old or not new: return jsonify({'error':'Access denied'}), 403
    try:
        os.rename(old, new)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/server/<sid>/mkdir', methods=['POST'])
@login_required
def api_mkdir(sid):
    base = server_folder(sid)
    if not base: return jsonify({'error':'Not found'}), 404
    d = request.get_json() or {}
    fp = safe_join(base, d.get('folder',''))
    if not fp: return jsonify({'error':'Access denied'}), 403
    try:
        os.makedirs(fp, exist_ok=True)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/server/<sid>/upload', methods=['POST'])
@login_required
def api_upload(sid):
    base = server_folder(sid)
    if not base: return jsonify({'error':'Not found'}), 404
    folder = request.form.get('folder','')
    target = safe_join(base, folder)
    if not target: return jsonify({'error':'Access denied'}), 403
    os.makedirs(target, exist_ok=True)
    files = request.files.getlist('files')
    up = []
    for f in files:
        if not f.filename: continue
        safe_name = os.path.basename(f.filename)
        f.save(os.path.join(target, safe_name))
        up.append(safe_name)
    return jsonify({'success': True, 'uploaded': up})

@app.route('/api/server/<sid>/upload_zip', methods=['POST'])
@login_required
def api_upload_zip(sid):
    base = server_folder(sid)
    if not base: return jsonify({'error':'Not found'}), 404
    folder = request.form.get('folder','')
    target = safe_join(base, folder)
    if not target: return jsonify({'error':'Access denied'}), 403
    os.makedirs(target, exist_ok=True)
    f = request.files.get('file')
    if not f: return jsonify({'error':'No file'}), 400
    tmp = os.path.join(target, f.filename)
    f.save(tmp)
    try:
        with zipfile.ZipFile(tmp, 'r') as zf:
            zf.extractall(target)
        os.remove(tmp)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/server/<sid>/unzip', methods=['POST'])
@login_required
def api_unzip(sid):
    base = server_folder(sid)
    if not base: return jsonify({'error':'Not found'}), 404
    d = request.get_json() or {}
    zp = safe_join(base, d.get('filename',''))
    if not zp or not os.path.isfile(zp) or not zp.endswith('.zip'):
        return jsonify({'error':'Invalid zip'}), 400
    try:
        with zipfile.ZipFile(zp, 'r') as zf:
            zf.extractall(os.path.dirname(zp))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/server/<sid>/download')
@login_required
def api_download(sid):
    base = server_folder(sid)
    if not base or not os.path.exists(base):
        return "Not found", 404
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(base):
            for file in files:
                if file == 'output.log': continue
                full = os.path.join(root, file)
                rel  = os.path.relpath(full, base)
                zf.write(full, rel)
    mem.seek(0)
    return send_file(mem, mimetype='application/zip',
                     as_attachment=True, download_name=f"{sid}.zip")

# ============================================
# API — ACCOUNTS
# ============================================
@app.route('/api/server/<sid>/accounts', methods=['GET'])
@login_required
def api_get_accounts(sid):
    base = server_folder(sid)
    if not base: return jsonify({'accounts': []})
    fp = os.path.join(base, 'accounts.json')
    if not os.path.exists(fp): return jsonify({'accounts': []})
    try:
        with open(fp, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, list): data = []
        return jsonify({'accounts': data})
    except Exception:
        return jsonify({'accounts': []})

@app.route('/api/server/<sid>/accounts', methods=['POST'])
@login_required
def api_save_accounts(sid):
    base = server_folder(sid)
    if not base: return jsonify({'error':'Not found'}), 404
    data = request.get_json() or {}
    accounts = data.get('accounts', [])
    if not isinstance(accounts, list):
        return jsonify({'error':'Invalid format'}), 400
    clean = [{'uid': str(a.get('uid','')).strip(),
              'password': str(a.get('password','')).strip()} for a in accounts]
    fp = os.path.join(base, 'accounts.json')
    try:
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump(clean, f, indent=2, ensure_ascii=False)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================
# API — STARTUP
# ============================================
@app.route('/api/server/<sid>/startup', methods=['GET'])
@login_required
def api_get_startup(sid):
    s = get_server(sid)
    if not s: return jsonify({'error':'Not found'}), 404
    return jsonify({
        'main_file': s.get('main_file','main.py'),
        'requirements_file': s.get('requirements_file','requirements.txt'),
    })

@app.route('/api/server/<sid>/startup', methods=['POST'])
@login_required
def api_set_startup(sid):
    d = request.get_json() or {}
    update_server(sid, {
        'main_file': (d.get('main_file') or 'main.py').strip(),
        'requirements_file': (d.get('requirements_file') or 'requirements.txt').strip(),
    })
    return jsonify({'success': True})

# ============================================
# API — TEMPLATES
# ============================================
def _tpl_base(): return os.path.abspath(TEMPLATES_BOT)

@app.route('/api/templates/files')
@login_required
def api_tpl_files():
    base = _tpl_base()
    folder = request.args.get('folder','')
    target = safe_join(base, folder)
    if not target or not os.path.exists(target):
        return jsonify({'files': []})
    out = []
    for it in sorted(os.listdir(target)):
        if it.startswith('.'): continue
        p = os.path.join(target, it)
        out.append({
            'name': it,
            'is_dir': os.path.isdir(p),
            'size': os.path.getsize(p) if os.path.isfile(p) else 0,
            'modified': datetime.fromtimestamp(os.path.getmtime(p)).strftime('%Y-%m-%d %H:%M')
        })
    return jsonify({'files': out})

@app.route('/api/templates/file', methods=['GET'])
@login_required
def api_tpl_get_file():
    fp = safe_join(_tpl_base(), request.args.get('filename',''))
    if not fp or not os.path.isfile(fp):
        return jsonify({'error':'Not found'}), 404
    try:
        with open(fp, 'r', encoding='utf-8', errors='replace') as f:
            return jsonify({'content': f.read()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/templates/file', methods=['POST'])
@login_required
def api_tpl_save_file():
    data = request.get_json() or {}
    fp = safe_join(_tpl_base(), data.get('filename',''))
    if not fp: return jsonify({'error':'Access denied'}), 403
    os.makedirs(os.path.dirname(fp) or _tpl_base(), exist_ok=True)
    with open(fp, 'w', encoding='utf-8') as f:
        f.write(data.get('content',''))
    return jsonify({'success': True})

@app.route('/api/templates/file', methods=['DELETE'])
@login_required
def api_tpl_del_file():
    data = request.get_json() or {}
    fp = safe_join(_tpl_base(), data.get('filename',''))
    if not fp: return jsonify({'error':'Access denied'}), 403
    try:
        if os.path.isdir(fp): shutil.rmtree(fp)
        elif os.path.isfile(fp): os.remove(fp)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/templates/rename', methods=['POST'])
@login_required
def api_tpl_rename():
    d = request.get_json() or {}
    old = safe_join(_tpl_base(), d.get('old_name',''))
    new = safe_join(_tpl_base(), d.get('new_name',''))
    if not old or not new: return jsonify({'error':'Access denied'}), 403
    try:
        os.rename(old, new)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/templates/mkdir', methods=['POST'])
@login_required
def api_tpl_mkdir():
    d = request.get_json() or {}
    fp = safe_join(_tpl_base(), d.get('folder',''))
    if not fp: return jsonify({'error':'Access denied'}), 403
    try:
        os.makedirs(fp, exist_ok=True)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/templates/upload', methods=['POST'])
@login_required
def api_tpl_upload():
    folder = request.form.get('folder','')
    target = safe_join(_tpl_base(), folder)
    if not target: return jsonify({'error':'Access denied'}), 403
    os.makedirs(target, exist_ok=True)
    files = request.files.getlist('files')
    up = []
    for f in files:
        if not f.filename: continue
        safe_name = os.path.basename(f.filename)
        f.save(os.path.join(target, safe_name))
        up.append(safe_name)
    return jsonify({'success': True, 'uploaded': up})

@app.route('/api/templates/upload_zip', methods=['POST'])
@login_required
def api_tpl_upload_zip():
    folder = request.form.get('folder','')
    target = safe_join(_tpl_base(), folder)
    if not target: return jsonify({'error':'Access denied'}), 403
    os.makedirs(target, exist_ok=True)
    f = request.files.get('file')
    if not f: return jsonify({'error':'No file'}), 400
    tmp = os.path.join(target, f.filename)
    f.save(tmp)
    try:
        with zipfile.ZipFile(tmp, 'r') as zf:
            zf.extractall(target)
        os.remove(tmp)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/templates/unzip', methods=['POST'])
@login_required
def api_tpl_unzip():
    d = request.get_json() or {}
    zp = safe_join(_tpl_base(), d.get('filename',''))
    if not zp or not os.path.isfile(zp) or not zp.endswith('.zip'):
        return jsonify({'error':'Invalid zip'}), 400
    try:
        with zipfile.ZipFile(zp, 'r') as zf:
            zf.extractall(os.path.dirname(zp))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================
# START
# ============================================
if __name__ == '__main__':
    ensure_template_defaults()
    ensure_shared_libs()
    print("\n" + "="*50)
    print("🚀 JUBAYER HOSTING — MULTI SERVER")
    print("="*50)
    print("📍 http://localhost:5000")
    print("🔐 MASTER: SEMY / M4X")
    print("👤 USER  : admin / admin123")
    print(f"📦 Max Servers : {MAX_SERVERS}")
    print(f"📚 Shared Libs : {SHARED_LIBS}/")
    print(f"🧩 Templates   : {TEMPLATES_BOT}/")
    print("="*50 + "\n")
    app.run(debug=False, host='0.0.0.0', port=5000)
