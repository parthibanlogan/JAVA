// Streamlit component of the Java Lab student app (apps/student/app.py).
// The editor, its typing log, paste and drop blocking and the work saved in this browser are
// those of the website's Lab page: Recorder, summarise and fnv come from lab-activity.js
// (copied here unchanged by the app at start-up), so the gradebook reads both alike.
// Compiling, running and the encrypted package are done by the app on the server (real JDK 21).
import { Recorder, summarise, fnv } from './lab-activity.js';

const $ = id => document.getElementById(id);
let args = null, editor = null, recorder = null, work = null, pending = null, pendingTimer = null;
let seenResult = null, initialised = false, mode = null, handled = null;

// ---------- Streamlit component protocol (API version 1) ----------
function post(type, data = {}) { window.parent.postMessage({ isStreamlitMessage: true, type, ...data }, '*'); }
function setValue(value) { post('streamlit:setComponentValue', { value, dataType: 'json' }); }
let lastHeight = -1;
function fitHeight() {      // height of the content itself (the frame's own height must not feed back)
  const h = mode === 'editor' ? Math.ceil($('app').getBoundingClientRect().bottom + window.scrollY) + 4 : 0;
  if (h !== lastHeight) { lastHeight = h; post('streamlit:setFrameHeight', { height: h }); }
}
new ResizeObserver(fitHeight).observe($('app'));

function safeGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function safeSet(k, v) { try { localStorage.setItem(k, v); return true; } catch { return false; } }
function safeKeys() { try { return Object.keys(localStorage); } catch { return []; } }
function safeRemove(k) { try { localStorage.removeItem(k); } catch { /* storage unavailable */ } }

window.addEventListener('message', ev => {
  const d = ev.data;
  if (!d || d.type !== 'streamlit:render') return;
  args = d.args || {};
  const dark = d.theme && d.theme.base === 'dark';
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  if (editor) editor.setTheme(dark ? 'ace/theme/tomorrow_night' : 'ace/theme/chrome');
  mode = args.mode;
  if (mode === 'identity') identity(); else editorRender();
  fitHeight();
});
post('streamlit:componentReady', { apiVersion: 1 });

// ---------- identity kept in this browser ----------
function identity() {
  if (handled === args.nonce) return;
  handled = args.nonce;
  if (args.action === 'save' && args.identity) {
    safeSet('lab-identity', JSON.stringify(args.identity));
    setValue({ nonce: args.nonce, saved: true });
  } else if (args.action === 'forget') {
    const regno = args.identity && args.identity.regno;
    for (const k of safeKeys()) if (regno && k.startsWith(`lab-work:${regno}:`)) safeRemove(k);
    safeRemove('lab-identity');
    setValue({ nonce: args.nonce, forgotten: true });
  } else {
    let stored = null;
    try { stored = JSON.parse(safeGet('lab-identity')); } catch { stored = null; }
    setValue({ nonce: args.nonce, identity: stored && stored.regno ? stored : null });
  }
}

// ---------- editor ----------
let saveTimer = null;
function saveNow() {
  clearTimeout(saveTimer);
  saveTimer = null;
  work.code = editor.getValue();
  work.stdin = $('stdin').value;
  work.updated = Date.now();
  if (!safeSet(args.workKey, JSON.stringify(work))) status('This browser does not allow saving: submit before you leave.', 'warn');
}
function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => { saveNow(); stats(); }, 300);
}
window.addEventListener('pagehide', () => { if (work && editor) saveNow(); });

function fileName(code) {
  const m = code.match(/public\s+(?:final\s+|abstract\s+)*class\s+(\w+)/);
  return (m ? m[1] : 'Main') + '.java';
}
function stats() {
  const s = summarise(work.events, editor.getValue());
  const min = ms => (ms / 60000).toFixed(1);
  $('file').textContent = fileName(editor.getValue());
  $('stats').innerHTML = [
    ['Typed', s.typedChars], ['Active', `${min(s.activeMs)} min`], ['Runs', s.runs],
    ['Best check', s.bestTotal ? `${s.bestPassed}/${s.bestTotal}` : '-'],
    ['Pastes blocked', s.pasteBlocked], ['Left the page', s.awayCount],
  ].map(([k, v]) => `<span>${k}: <b>${v}</b></span>`).join('');
}
function status(text, kind = '') {
  $('status').textContent = text;
  $('status').className = 'status' + (kind ? ' ' + kind : '');
}
function buttons() {
  const busy = pending !== null;
  $('run').disabled = busy;
  $('check').disabled = busy || !args.caseCount;
  $('check').title = args.caseCount ? '' : 'This question has no sample cases.';
  $('submit').disabled = busy || !args.submitOpen;
  $('submit').title = args.submitOpen ? '' : (args.submitHint || '');
}

function editorRender() {
  if (!initialised) {
    initialised = true;
    $('app').hidden = false;
    ace.config.set('basePath', 'ace/');
    editor = ace.edit('editor', {
      mode: 'ace/mode/java', tabSize: 4, useSoftTabs: true, showPrintMargin: false,
      behavioursEnabled: false, wrapBehavioursEnabled: false, enableAutoIndent: true, fontSize: 14,
    });
    editor.setTheme(document.documentElement.dataset.theme === 'dark' ? 'ace/theme/tomorrow_night' : 'ace/theme/chrome');
    $('editor').style.height = `${args.height || 420}px`;
    editor.resize();
    try { work = JSON.parse(safeGet(args.workKey)); } catch { work = null; }
    if (!work || !Array.isArray(work.events)) work = { t0: Date.now(), events: [], code: '', stdin: args.defaultStdin || '' };
    recorder = new Recorder(editor, work, {
      onChange: save,
      onBlocked: kind => status(kind === 'paste'
        ? 'Pasting from outside the editor is not allowed. Type the code. (The attempt is recorded.)'
        : 'Dropping text into the editor is not allowed.', 'bad'),
    });
    if (work.code) recorder.load(work.code); else save();
    $('stdin').value = work.stdin || '';
    $('stdin').addEventListener('input', save);
    for (const action of ['run', 'check', 'submit']) $(action).addEventListener('click', () => request(action));
    seenResult = args.result ? args.result.nonce : null;      // results from before a reload are not re-recorded
    stats();
    editor.focus();
  }
  const r = args.result;
  if (r && r.nonce !== seenResult) {
    seenResult = r.nonce;
    if (r.event) recorder.event(...r.event);                   // ['x', outcome, ms] or ['c', passed, total]
    saveNow();
    stats();
    if (pending === r.nonce) { pending = null; clearTimeout(pendingTimer); }
    status(r.message || '', r.kind || '');
  }
  buttons();
}

function request(action) {
  if (pending !== null) return;
  const code = editor.getValue();
  if (action === 'submit') {
    if (code.trim().length < 20) { status('Type your program first.', 'warn'); return; }
    if (!confirm(args.confirmText || 'Submit this program?')) return;
    recorder.event('s', fnv(code));
  }
  saveNow();
  pending = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  status(action === 'check' ? 'Checking on the server...' : action === 'submit' ? 'Making the encrypted package...' : 'Compiling and running on the server...');
  buttons();
  clearTimeout(pendingTimer);
  pendingTimer = setTimeout(() => { pending = null; status('No answer from the server. Press the button again.', 'warn'); buttons(); }, 90000);
  setValue({
    nonce: pending, action, code, stdin: $('stdin').value, fileName: fileName(code),
    t0: new Date(work.t0).toISOString(), t0ms: work.t0, events: work.events,
    timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone, userAgent: navigator.userAgent,
  });
}
