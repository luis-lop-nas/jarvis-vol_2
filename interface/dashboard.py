"""Dashboard web de JARVIS — panel de control en http://localhost:8765.

HTML+JS vanilla (sin dependencias frontend externas). Muestra sesiones activas,
audit log, estado del sistema y permite cancelar sesiones.
Protegido por el mismo rate limiting que el resto de la API.
"""

from __future__ import annotations

_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JARVIS — Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'SF Mono', 'Menlo', monospace;
    background: #0d0d0d;
    color: #e0e0e0;
    padding: 24px;
    font-size: 13px;
  }
  h1 { color: #5ac8fa; font-size: 18px; margin-bottom: 20px; letter-spacing: 0.05em; }
  h2 { color: #888; font-size: 12px; text-transform: uppercase;
       letter-spacing: 0.1em; margin: 24px 0 10px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
          gap: 12px; margin-bottom: 8px; }
  .card {
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 8px;
    padding: 12px 16px;
  }
  .card .label { color: #666; font-size: 11px; margin-bottom: 4px; }
  .card .value { font-size: 20px; font-weight: bold; }
  .ok  { color: #30d158; }
  .err { color: #ff453a; }
  .warn { color: #ffd60a; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; color: #555; font-size: 11px; text-transform: uppercase;
       padding: 6px 10px; border-bottom: 1px solid #222; }
  td { padding: 7px 10px; border-bottom: 1px solid #1a1a1a; }
  tr:hover td { background: #161616; }
  .badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
  }
  .badge-thinking { background: #1c3a5e; color: #5ac8fa; }
  .badge-acting   { background: #3a2800; color: #ffd60a; }
  .badge-waiting  { background: #3a1a00; color: #ff9f0a; }
  .badge-done     { background: #1a3a1a; color: #30d158; }
  .badge-error    { background: #3a1a1a; color: #ff453a; }
  .badge-idle     { background: #1e1e1e; color: #888; }
  .btn-cancel {
    background: #3a1a1a;
    color: #ff453a;
    border: 1px solid #ff453a33;
    border-radius: 4px;
    padding: 3px 10px;
    cursor: pointer;
    font-size: 11px;
    font-family: inherit;
  }
  .btn-cancel:hover { background: #5a2020; }
  .mono { font-family: inherit; color: #aaa; }
  .dim  { color: #555; }
  pre { background: #111; border: 1px solid #222; border-radius: 6px;
        padding: 10px; overflow-x: auto; font-size: 11px; color: #aaa;
        max-height: 300px; overflow-y: auto; }
  #refresh-indicator { float: right; color: #444; font-size: 11px; }
  #error-banner { display: none; background: #3a1a1a; color: #ff453a;
                  border: 1px solid #ff453a33; border-radius: 6px;
                  padding: 8px 14px; margin-bottom: 16px; }
</style>
</head>
<body>

<h1>JARVIS <span id="refresh-indicator">actualizando…</span></h1>
<div id="error-banner"></div>

<h2>Estado del sistema</h2>
<div class="grid" id="status-grid">
  <div class="card"><div class="label">API</div><div class="value dim">…</div></div>
</div>

<h2>Sesiones activas</h2>
<table id="sessions-table">
  <thead><tr><th>session_id</th><th>Tarea</th><th>Estado</th><th>Guardado</th><th></th></tr></thead>
  <tbody id="sessions-body"><tr><td colspan="5" class="dim">Cargando…</td></tr></tbody>
</table>

<h2>Audit log (últimas 50 entradas)</h2>
<pre id="audit-log">Cargando…</pre>

<script>
const BASE = '';

function badge(type) {
  const map = {
    thinking: ['thinking', 'Pensando'],
    acting:   ['acting',   'Actuando'],
    waiting:  ['waiting',  'Esperando'],
    done:     ['done',     'Completado'],
    error:    ['error',    'Error'],
  };
  const [cls, label] = map[type] || ['idle', type || 'Idle'];
  return `<span class="badge badge-${cls}">${label}</span>`;
}

function timeAgo(iso) {
  if (!iso) return '—';
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 60) return `hace ${diff}s`;
  if (diff < 3600) return `hace ${Math.floor(diff/60)}m`;
  return `hace ${Math.floor(diff/3600)}h`;
}

async function fetchJSON(url) {
  const r = await fetch(BASE + url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}

async function cancelSession(sid) {
  if (!confirm(`¿Cancelar sesión ${sid}?`)) return;
  try {
    await fetch(BASE + `/cancel/${sid}`, {method: 'POST'});
    refresh();
  } catch (e) {
    alert('Error al cancelar: ' + e.message);
  }
}

async function loadStatus() {
  try {
    const s = await fetchJSON('/status');
    const grid = document.getElementById('status-grid');
    const items = [
      ['API', s.api_running, s.api_running ? 'OK' : 'DOWN'],
      ['ChromaDB', s.chroma_connected, s.chroma_connected ? 'OK' : 'DOWN'],
      ['Ollama', s.ollama_running, s.ollama_running ? 'OK' : 'DOWN'],
      ['1Password', s.onepassword_available, s.onepassword_available ? 'OK' : 'N/A'],
      ['RAM libre', true, s.ram_available_gb + ' GB'],
      ['Modelos', true, s.available_models?.length || 0],
    ];
    grid.innerHTML = items.map(([label, ok, val]) =>
      `<div class="card">
        <div class="label">${label}</div>
        <div class="value ${ok ? 'ok' : 'err'}">${val}</div>
      </div>`
    ).join('');
    if (s.mcp_health && Object.keys(s.mcp_health).length) {
      grid.innerHTML += Object.entries(s.mcp_health).map(([name, ok]) =>
        `<div class="card">
          <div class="label">MCP · ${name}</div>
          <div class="value ${ok ? 'ok' : 'err'}">${ok ? 'OK' : 'DOWN'}</div>
        </div>`
      ).join('');
    }
  } catch (e) {
    document.getElementById('status-grid').innerHTML =
      `<div class="card"><div class="label">Estado</div><div class="value err">Error</div></div>`;
  }
}

async function loadSessions() {
  try {
    const sessions = await fetchJSON('/sessions');
    const tbody = document.getElementById('sessions-body');
    if (!sessions || sessions.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="dim">Sin sesiones persistidas.</td></tr>';
      return;
    }
    tbody.innerHTML = sessions.map(s =>
      `<tr>
        <td class="mono">${s.session_id}</td>
        <td>${s.current_task || '<span class="dim">—</span>'}</td>
        <td>${badge(s.tarea_completada ? 'done' : s.waiting_for_user ? 'waiting' : '')}</td>
        <td class="dim">${timeAgo(s.saved_at)}</td>
        <td><button class="btn-cancel" onclick="cancelSession('${s.session_id}')">Cancelar</button></td>
      </tr>`
    ).join('');
  } catch (e) {
    document.getElementById('sessions-body').innerHTML =
      `<tr><td colspan="5" class="err">Error cargando sesiones: ${e.message}</td></tr>`;
  }
}

async function loadAudit() {
  try {
    const entries = await fetchJSON('/audit?limit=50');
    const pre = document.getElementById('audit-log');
    if (!entries || entries.length === 0) {
      pre.textContent = 'Sin entradas en el audit log.';
      return;
    }
    pre.textContent = entries.slice().reverse().map(e => {
      const ts = e.timestamp ? new Date(e.timestamp).toLocaleTimeString('es-ES') : '?';
      const sid = e.session_id ? e.session_id.slice(0, 8) : '?';
      const result = e.result || '';
      return `[${ts}] [${sid}…] ${e.action_type || ''} · ${e.action || ''} → ${result}`;
    }).join('\\n');
  } catch (e) {
    document.getElementById('audit-log').textContent = 'Error: ' + e.message;
  }
}

async function refresh() {
  const ind = document.getElementById('refresh-indicator');
  ind.textContent = 'actualizando…';
  try {
    await Promise.all([loadStatus(), loadSessions(), loadAudit()]);
    ind.textContent = 'actualizado ' + new Date().toLocaleTimeString('es-ES');
    document.getElementById('error-banner').style.display = 'none';
  } catch (e) {
    ind.textContent = 'error';
    const banner = document.getElementById('error-banner');
    banner.style.display = 'block';
    banner.textContent = 'Error de conexión con la API: ' + e.message;
  }
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>"""


def build_dashboard_html() -> str:
    """Devuelve el HTML completo del dashboard.

    Ejemplo::
        html = build_dashboard_html()
    """
    return _HTML
