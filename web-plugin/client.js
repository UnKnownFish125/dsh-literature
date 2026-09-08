__ModuleLoader__.load({
  id: 'dsh-literature',
  factory: (require) => {
const React = require('react')
const UI = require('@deepseek-ai/dsh-client-ui-primitives')
const h = React.createElement
const name = 'dsh-literature'
const API = '/lit-api/v1/literature'
const DEFAULT_WORKSPACE = 'deepseek-harness'
const LIBRARIES = ['bias', 'core', 'eco', 'project', 'runtime']
const LIB_LABEL = { bias: 'bias 约束', core: 'core 核心', eco: 'eco 生态', project: 'project 项目', runtime: 'runtime 运行' }
const LIB_COLOR = {
  bias: 'var(--dsw-alias-state-warn-primary)',
  core: 'var(--dsw-alias-brand-primary)',
  eco: 'var(--dsw-alias-state-success-primary)',
  project: 'var(--dsw-alias-state-business-primary)',
  runtime: 'var(--dsw-alias-state-error-primary)',
  unknown: 'var(--dsw-alias-label-secondary)',
}
const READ_STATUS = { unread: '未读', reading: '在读', intensive: '精读', read: '已读' }
const DOC_TYPE = { paper: '论文', book: '书籍', report: '报告', web: '网页' }
const STANCE = { supporting: '支持', contradicting: '反驳', contextual: '中性' }
const ICONS = {
  back: UI.IconChevronLeftOutline14, refresh: UI.IconRefreshOutline16, search: UI.IconSearchOutline16,
  close: UI.IconCloseOutline16, add: UI.IconPlusOutline16, open: UI.IconRightUpOutline16,
  upload: UI.IconDownloadOutline16, zoomIn: UI.IconPlusOutline16, reset: UI.IconRefreshOutline16, save: UI.IconCheckOutline16,
}

function qs(params) {
  const query = new URLSearchParams()
  Object.keys(params || {}).forEach(function (key) {
    const value = params[key]
    if (value !== undefined && value !== null && value !== '') query.set(key, String(value))
  })
  return query.size ? '?' + query.toString() : ''
}

async function api(path, opts) {
  const o = opts || {}
  const method = o.method || 'GET'
  const headers = {}
  let body
  if (o.body !== undefined && o.body !== null) {
    if (o.raw) body = o.body
    else { headers['Content-Type'] = 'application/json'; body = JSON.stringify(o.body) }
  }
  let res
  try {
    res = await fetch(API + path, { method, headers, body })
  } catch (e) {
    throw new Error('网络错误: ' + String((e && e.message) || e))
  }
  let data = null
  try { data = await res.json() } catch (e) { data = null }
  if (!res.ok) {
    const msg = (data && (data.error || data.detail)) || ('HTTP ' + res.status + (res.statusText ? ' ' + res.statusText : ''))
    throw new Error(String(msg))
  }
  return data
}

// Shared DSH tokens; only native option popups need dark fallbacks.
const LIT_CSS = `
/* DSH DESIGN TOKENS: deepmemory box / row / mini / btn / input / select. */
.dsh-lit-panel, .dsh-lit-pcard { color:var(--dsw-alias-label-primary); font-size:13px; line-height:1.55; letter-spacing:0; min-width:0; }
.dsh-lit-panel *, .dsh-lit-pcard * { box-sizing:border-box; letter-spacing:0; }
.dsh-lit-panel { width:100%; max-width:1120px; padding:16px 20px; display:flex; flex-direction:column; gap:12px; container-type:inline-size; }
.dsh-lit-topbar, .dsh-lit-actions, .dsh-lit-meta, .dsh-lit-section-head { display:flex; align-items:center; gap:8px; flex-wrap:wrap; min-width:0; }
.dsh-lit-topbar { justify-content:space-between; min-height:28px; }
.dsh-lit-brand { margin:0; font-size:14px; font-weight:600; overflow-wrap:anywhere; }
.dsh-lit-ws { color:var(--dsw-alias-label-secondary); font-size:11px; max-width:100%; overflow-wrap:anywhere; font-family:ui-monospace, SFMono-Regular, Menlo, monospace; }
.dsh-lit-tabs { display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:4px; padding:0 0 10px; border-bottom:1px solid var(--dsw-alias-border-l1); }
.dsh-lit-tab { appearance:none; border:1px solid var(--dsw-alias-border-l1); border-radius:6px; padding:5px 8px; min-height:32px; background:var(--dsw-alias-bg-layer-1); color:var(--dsw-alias-label-secondary); font:inherit; cursor:pointer; }
.dsh-lit-tab:hover, .dsh-lit-btn:hover { background:var(--dsw-alias-bg-layer-2); }
.dsh-lit-tab[aria-selected="true"] { background:var(--dsw-alias-bg-layer-2); border-color:var(--dsw-alias-border-l2); color:var(--dsw-alias-label-primary); font-weight:600; }
.dsh-lit-view, .dsh-lit-stack { display:flex; flex-direction:column; gap:12px; min-width:0; }
.dsh-lit-view[hidden] { display:none; }
.dsh-lit-title { margin:0; font-size:12px; font-weight:500; color:var(--dsw-alias-label-secondary); }
.dsh-lit-heading { margin:0; font-size:15px; font-weight:600; overflow-wrap:anywhere; }
.dsh-lit-section { padding-top:12px; border-top:1px solid var(--dsw-alias-border-l1); min-width:0; }
.dsh-lit-section-head { margin-bottom:8px; }
.dsh-lit-box { border:1px solid var(--dsw-alias-border-l1); border-radius:8px; padding:10px; min-width:0; }
.dsh-lit-row { display:flex; gap:8px; align-items:flex-start; padding:7px 0; border-top:1px solid var(--dsw-alias-border-l1); min-width:0; }
.dsh-lit-row:first-child { border-top:0; }
.dsh-lit-list { min-width:0; border-top:1px solid var(--dsw-alias-border-l1); }
.dsh-lit-rowbtn { appearance:none; display:flex; gap:10px; align-items:flex-start; width:100%; text-align:left; padding:10px 0; border:0; border-bottom:1px solid var(--dsw-alias-border-l1); border-radius:0; background:var(--dsw-alias-bg-layer-1); color:var(--dsw-alias-label-primary); font:inherit; cursor:pointer; }
.dsh-lit-rowbtn:hover { background:var(--dsw-alias-bg-layer-2); }
.dsh-lit-rowbtn .dsh-lit-content { display:flex; flex-direction:column; gap:4px; }
.dsh-lit-content { flex:1; min-width:0; overflow-wrap:anywhere; }
.dsh-lit-row-icon { flex:none; width:22px; padding-top:1px; text-align:center; color:var(--dsw-alias-label-secondary); }
.dsh-lit-badge, .dsh-lit-mini { display:inline-flex; align-items:center; gap:4px; max-width:100%; font-size:11px; font-weight:400; line-height:1.55; padding:1px 5px; border:1px solid var(--dsw-alias-border-l1); border-radius:6px; background:var(--dsw-alias-bg-layer-1); color:var(--dsw-alias-label-secondary); overflow-wrap:anywhere; }
.dsh-lit-badge { color:var(--dsw-alias-label-primary); }
.dsh-lit-archived { border-style:dashed; color:var(--dsw-alias-state-warn-primary); }
.dsh-lit-stance-supporting { color:var(--dsw-alias-state-success-primary); }
.dsh-lit-stance-contradicting { color:var(--dsw-alias-state-error-primary); }
.dsh-lit-stance-contextual { color:var(--dsw-alias-label-secondary); }
.dsh-lit-meta { gap:6px; color:var(--dsw-alias-label-secondary); font-size:12px; overflow-wrap:anywhere; }
.dsh-lit-muted, .dsh-lit-count { color:var(--dsw-alias-label-secondary); font-size:11px; overflow-wrap:anywhere; }
.dsh-lit-count { margin-left:auto; }
.dsh-lit-input, .dsh-lit-select { min-width:0; max-width:100%; background:var(--dsw-alias-bg-layer-1); border:1px solid var(--dsw-alias-border-l2); border-radius:6px; padding:6px 8px; color:var(--dsw-alias-label-primary); font:inherit; line-height:1.55; }
.dsh-lit-input { flex:1; width:100%; }
.dsh-lit-select { padding:5px 6px; }
.dsh-lit-input::placeholder { color:var(--dsw-alias-label-secondary); opacity:1; }
.dsh-lit-select option { background:var(--dsw-alias-bg-overlay, #1e1e1e); color:var(--dsw-alias-label-primary, #e8e8e8); }
.dsh-lit-check { display:inline-flex; gap:6px; align-items:center; color:var(--dsw-alias-label-secondary); cursor:pointer; white-space:nowrap; }
.dsh-lit-check input { accent-color:var(--dsw-alias-brand-primary); margin:0; width:14px; height:14px; }
.dsh-lit-btn { appearance:none; display:inline-flex; align-items:center; justify-content:center; gap:6px; border:1px solid var(--dsw-alias-border-l2); background:var(--dsw-alias-bg-layer-1); color:var(--dsw-alias-label-primary); border-radius:6px; min-height:30px; max-width:100%; padding:4px 12px; cursor:pointer; font:inherit; line-height:1.55; }
.dsh-lit-btn-primary { border-color:var(--dsw-alias-brand-primary); color:var(--dsw-alias-brand-primary); }
.dsh-lit-btn-danger { color:var(--dsw-alias-state-error-primary); }
.dsh-lit-btn-icon { width:32px; height:32px; flex:none; padding:0; }
.dsh-lit-symbol { display:inline-flex; width:16px; height:18px; align-items:center; justify-content:center; flex:none; font-size:16px; line-height:1; }
.dsh-lit-symbol-upload { transform:rotate(180deg); }
.dsh-lit-btn:disabled { opacity:.45; cursor:default; }
.dsh-lit-panel :focus-visible, .dsh-lit-pcard :focus-visible { outline:2px solid var(--dsw-alias-brand-primary); outline-offset:2px; }
.dsh-lit-link { color:var(--dsw-alias-brand-primary); text-decoration:none; overflow-wrap:anywhere; }
.dsh-lit-link:hover { text-decoration:underline; }
.dsh-lit-search { display:flex; align-items:center; gap:6px; flex:1 1 220px; min-width:0; }
.dsh-lit-form { display:flex; gap:8px; flex-wrap:wrap; align-items:flex-start; }
.dsh-lit-field { display:flex; flex-direction:column; gap:4px; flex:1 1 180px; min-width:0; max-width:100%; color:var(--dsw-alias-label-secondary); font-size:12px; }
.dsh-lit-field-wide { flex-basis:100%; }
.dsh-lit-field textarea { min-height:80px; resize:vertical; }
.dsh-lit-kv { display:grid; grid-template-columns:minmax(80px, .25fr) minmax(0, 1fr); gap:6px 14px; margin:0; }
.dsh-lit-kv dt { color:var(--dsw-alias-label-secondary); overflow-wrap:anywhere; }
.dsh-lit-kv dd { margin:0; min-width:0; overflow-wrap:anywhere; }
.dsh-lit-text { margin:0; white-space:pre-wrap; overflow-wrap:anywhere; }
.dsh-lit-pre { margin:8px 0 0; padding:8px; background:var(--dsw-alias-bg-layer-1); border:1px solid var(--dsw-alias-border-l1); border-radius:6px; color:var(--dsw-alias-label-primary); font:inherit; font-size:12px; line-height:1.55; white-space:pre-wrap; overflow-wrap:anywhere; max-height:360px; overflow:auto; }
.dsh-lit-details > summary { cursor:pointer; color:var(--dsw-alias-label-secondary); }
.dsh-lit-evidence { display:flex; flex-direction:column; gap:6px; padding:10px 0; border-top:1px solid var(--dsw-alias-border-l1); min-width:0; }
.dsh-lit-evidence:first-child { border-top:0; }
.dsh-lit-evidence blockquote { margin:0; padding-left:10px; border-left:2px solid var(--dsw-alias-border-l2); color:var(--dsw-alias-label-secondary); }
.dsh-lit-relation { display:grid; grid-template-columns:minmax(0, 1fr) auto minmax(0, 1fr); gap:8px; align-items:start; width:100%; }
.dsh-lit-empty { padding:20px 0; color:var(--dsw-alias-label-secondary); }
.dsh-lit-notice { display:flex; align-items:center; gap:8px; flex-wrap:wrap; padding:6px 0; min-width:0; color:var(--dsw-alias-label-secondary); overflow-wrap:anywhere; }
.dsh-lit-notice-error { color:var(--dsw-alias-state-error-primary); }
.dsh-lit-notice-ok { color:var(--dsw-alias-state-success-primary); }
.dsh-lit-stat-grid { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:10px; }
.dsh-lit-stat { display:flex; flex-direction:column; gap:8px; background:var(--dsw-alias-bg-layer-1); }
.dsh-lit-stat-big { font-size:24px; font-weight:600; line-height:1.3; overflow-wrap:anywhere; }
.dsh-lit-stat-lines { display:flex; flex-direction:column; gap:4px; color:var(--dsw-alias-label-secondary); font-size:12px; overflow-wrap:anywhere; }
.dsh-lit-graph-view { position:relative; min-width:0; }
.dsh-lit-graph-content { display:flex; flex-direction:column; gap:12px; min-width:0; }
.dsh-lit-graph-content[hidden] { display:none; }
.dsh-lit-graph-stage { min-width:0; position:relative; }
.dsh-lit-graph-svg { width:100%; height:clamp(480px, 86vh, 920px); display:block; overflow:hidden; overscroll-behavior:contain; background:var(--dsw-alias-bg-layer-1); border:1px solid var(--dsw-alias-border-l1); border-radius:8px; touch-action:none; cursor:grab; }
.dsh-lit-graph-svg:active { cursor:grabbing; }
.dsh-lit-graph-node { cursor:pointer; transition:opacity .14s; }
.dsh-lit-graph-node:active { cursor:grabbing; }
.dsh-lit-graph-label { fill:var(--dsw-alias-label-primary); paint-order:stroke; stroke:var(--dsw-alias-bg-layer-1); stroke-linejoin:round; pointer-events:none; }
.dsh-lit-graph-edge { stroke:var(--dsw-alias-border-l2); }
.dsh-lit-graph-island { fill-opacity:.07; stroke-opacity:.24; stroke-width:1; pointer-events:none; }
.dsh-lit-graph-legend { display:flex; align-items:center; gap:6px 16px; flex-wrap:wrap; max-height:104px; overflow:auto; font-size:11px; color:var(--dsw-alias-label-secondary); }
.dsh-lit-graph-key { display:inline-flex; align-items:center; gap:5px; max-width:100%; }
.dsh-lit-graph-key-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:230px; }
.dsh-lit-graph-dot { width:8px; height:8px; border-radius:50%; display:inline-block; flex:none; }
.dsh-lit-graph-overlay { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; padding:20px; pointer-events:none; color:var(--dsw-alias-label-secondary); text-align:center; }
.dsh-lit-graph-zoom { width:48px; text-align:center; font-variant-numeric:tabular-nums; flex:none; }
.dsh-lit-graph-fullscreen, .dsh-lit-graph-view:fullscreen { position:fixed; inset:0; width:100vw; height:100vh; max-width:none; margin:0; padding:0; z-index:10000; background:var(--dsw-alias-bg-layer-1); color:var(--dsw-alias-label-primary); overflow:hidden; }
.dsh-lit-graph-fullscreen .dsh-lit-graph-svg { width:100vw; height:100vh; border:0; border-radius:0; }
.dsh-lit-graph-fullscreen .dsh-lit-graph-controls { position:absolute; top:0; left:0; right:0; z-index:2; padding:10px 12px; background:var(--dsw-alias-bg-layer-1); border-bottom:1px solid var(--dsw-alias-border-l1); }
.dsh-lit-graph-fullscreen .dsh-lit-graph-legend { position:absolute; bottom:0; left:0; right:0; z-index:2; padding:10px 12px; background:var(--dsw-alias-bg-layer-1); border-top:1px solid var(--dsw-alias-border-l1); }
.dsh-lit-graph-fullscreen .dsh-lit-graph-detail { height:100vh; padding:20px; overflow:auto; }
.dsh-lit-graph-fullscreen .dsh-lit-graph-detail > .dsh-lit-stack { max-width:1080px; margin:0 auto; }
.dsh-lit-graph-fullscreen .dsh-lit-graph-error { position:absolute; top:100px; left:12px; right:12px; z-index:2; background:var(--dsw-alias-bg-layer-1); }
.dsh-lit-panel:has(.dsh-lit-graph-fullscreen) { container-type:normal; }
.dsh-lit-pcard { border:1px solid var(--dsw-alias-border-l2); background:var(--dsw-alias-bg-layer-1); border-radius:8px; list-style:none; }
.dsh-lit-pcard[open] { background:var(--dsw-alias-bg-layer-2); }
.dsh-lit-pcard > summary { cursor:pointer; padding:14px 16px; font-weight:600; }
.dsh-lit-pcard-body { border-top:1px solid var(--dsw-alias-border-l2); margin:0 16px; padding:12px 0; }
.dsh-lit-cfg-group { border:0; margin:0 0 12px; padding:0; min-width:0; }
.dsh-lit-cfg-group legend { color:var(--dsw-alias-label-secondary); font-size:12px; margin-bottom:4px; }
.dsh-lit-cfg-item { display:flex; flex-direction:column; gap:4px; padding:8px 0; border-top:1px solid var(--dsw-alias-border-l1); min-width:0; }
.dsh-lit-cfg-item:first-of-type { border-top:0; }
.dsh-lit-cfg-label { font-weight:500; overflow-wrap:anywhere; }
.dsh-lit-cfg-footer { display:flex; align-items:center; justify-content:flex-end; gap:8px; border-top:1px solid var(--dsw-alias-border-l2); padding-top:10px; }
.dsh-lit-cfg-footer .dsh-lit-notice { flex:1; }
@container (max-width:420px) { .dsh-lit-stat-grid { grid-template-columns:minmax(0, 1fr); } .dsh-lit-relation { grid-template-columns:minmax(0, 1fr); } }
@media (max-width:480px) { .dsh-lit-panel { padding:12px; } .dsh-lit-tab { padding:5px 2px; } }

`

function fmtTime(ts) {
  if (ts === undefined || ts === null || ts === '') return '—'
  const date = new Date(Number.isFinite(Number(ts)) ? Number(ts) * 1000 : ts)
  return Number.isNaN(date.getTime()) ? String(ts) : date.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

function short(value, length) {
  const text = String(value == null ? '' : value)
  return text.length > length ? text.slice(0, length) + '…' : text
}

function isArchived(item) { return !!item && (item.archived === 1 || item.archived === true || String(item.archived) === 'true') }
function libraryColor(library) { return LIB_COLOR[library] || LIB_COLOR.unknown }
function message(error) { return String(error && error.message || error) }
function list(value) { return Array.isArray(value) ? value : [] }
function pathFor(kind, id, workspaceId) { return '/' + kind + '/' + encodeURIComponent(String(id)) + qs({ workspace_id: workspaceId }) }

// ── shell 级会话/工作区接线：conversation.view 的 props 从不含工作区信息
//（宿主从未提供 props.useWorkspaces），改为在 apply(ctx) 直连 shell 的
//    sessions/workspaces 服务，订阅快照解析「当前会话 → 所在工作区」
//（与 dsh-livetaskboard 同款模式；工作区 ID 即宿主 workspaceId，与
//    literature server list_workspaces 读 workspace.json 补 title 的口径一致）。
const shellServices = { sessions: null, workspaces: null }

function useShellSnapshot(service, empty) {
  const [snap, setSnap] = React.useState(function () {
    return service && service.list ? service.list.getSnapshot() : empty
  })
  React.useEffect(function () {
    if (!service || !service.list) return
    const update = function () { setSnap(service.list.getSnapshot()) }
    const off = service.list.subscribe(update)
    update()
    return function () { off() }
  }, [service])
  return snap
}

function resolveWorkspaceId(props, sessionsSnap, workspacesSnap, serverWs) {
  const sid = props && props.sessionId ? String(props.sessionId)
    : sessionsSnap && sessionsSnap.current ? String(sessionsSnap.current) : ''
  if (!sid) return DEFAULT_WORKSPACE
  // 优先：后端 /workspaces（含 session_ids，读宿主 workspace.json）——不依赖前端 shell 服务
  const byServer = list(serverWs).find(function (w) {
    return list(w && w.session_ids).map(String).indexOf(sid) >= 0
  })
  if (byServer && byServer.workspace_id) return String(byServer.workspace_id)
  // 回退：前端 shell 快照（若宿主提供了 sessions/workspaces 服务）
  const byShell = list(workspacesSnap && workspacesSnap.items).find(function (workspace) {
    return list(workspace.sessionIds).map(String).indexOf(sid) >= 0
  })
  return byShell && (byShell.workspaceId || byShell.id) ? String(byShell.workspaceId || byShell.id) : DEFAULT_WORKSPACE
}

function Button(props) {
  const attrs = Object.assign({ type: 'button' }, props)
  delete attrs.icon
  delete attrs.children
  attrs.className = 'dsh-lit-btn' + (props.className ? ' ' + props.className : '')
  if (!props.children) {
    attrs.className += ' dsh-lit-btn-icon'
    attrs['aria-label'] = props['aria-label'] || props.title
  }
  return h('button', attrs,
    props.icon ? h('span', { className: 'dsh-lit-symbol' + (props.icon === 'upload' ? ' dsh-lit-symbol-upload' : ''), 'aria-hidden': true },
      ICONS[props.icon] ? h(ICONS[props.icon], {}) : '−') : null,
    props.children || null)
}

function Notice(props) {
  if (!props.text) return null
  return h('div', { className: 'dsh-lit-notice' + (props.error ? ' dsh-lit-notice-error' : props.success ? ' dsh-lit-notice-ok' : ''), role: props.error ? 'alert' : 'status' },
    h('span', { className: 'dsh-lit-content' }, props.text),
    props.retry ? h(Button, { icon: 'refresh', title: '重试', onClick: props.retry }, '重试') : null)
}

function Empty(props) { return h('div', { className: 'dsh-lit-empty', role: 'status' }, props.children || '暂无数据') }

function libraryChip(library) {
  return h('span', { className: 'dsh-lit-mini' },
    h('i', { className: 'dsh-lit-graph-dot', style: { background: libraryColor(library) }, 'aria-hidden': true }),
    LIB_LABEL[library] || library || '未分类')
}

function archivedChip() { return h('span', { className: 'dsh-lit-mini dsh-lit-archived' }, '已归档') }

function LibrarySelect(props) {
  return h('select', {
    className: 'dsh-lit-select', value: props.value, 'aria-label': '知识库', title: '知识库',
    onChange: function (event) { props.onChange(event.target.value) },
  }, h('option', { value: '' }, '全部知识库'),
  LIBRARIES.map(function (library) { return h('option', { key: library, value: library }, LIB_LABEL[library]) }))
}

function ArchiveCheck(props) {
  return h('label', { className: 'dsh-lit-check' },
    h('input', { type: 'checkbox', checked: props.value, onChange: function (event) { props.onChange(event.target.checked) } }), '含归档')
}

function KV(props) {
  return h('dl', { className: 'dsh-lit-kv' }, props.rows.map(function (row) {
    return h(React.Fragment, { key: row[0] },
      h('dt', null, row[0]), h('dd', null, row[1] == null || row[1] === '' ? '—' : row[1]))
  }))
}

function Section(props) {
  return h('section', { className: 'dsh-lit-section' },
    h('div', { className: 'dsh-lit-section-head' },
      h('h3', { className: 'dsh-lit-title' }, props.title),
      props.count != null ? h('span', { className: 'dsh-lit-mini' }, props.count) : null,
      props.actions || null),
    props.children)
}

// Each effect owns its response, so a slow request cannot replace a newer filter or workspace.
function useResource(loader, dependencies) {
  const [revision, setRevision] = React.useState(0)
  const [state, setState] = React.useState({ data: null, loading: true, error: '' })
  React.useEffect(function () {
    let alive = true
    setState({ data: null, loading: true, error: '' })
    Promise.resolve().then(loader).then(function (data) {
      if (alive) setState({ data: data, loading: false, error: '' })
    }).catch(function (error) {
      if (alive) setState({ data: null, loading: false, error: message(error) })
    })
    return function () { alive = false }
  }, dependencies.concat(revision))
  const reload = React.useCallback(function () { setRevision(function (value) { return value + 1 }) }, [])
  return Object.assign({}, state, { reload: reload })
}

function EvidenceRow(props) {
  const ev = props.ev
  const stance = STANCE[ev.stance] ? ev.stance : 'contextual'
  return h('article', { className: 'dsh-lit-evidence' },
    h('div', { className: 'dsh-lit-actions' },
      h('span', { className: 'dsh-lit-mini dsh-lit-stance-' + stance }, STANCE[ev.stance] || ev.stance || STANCE.contextual),
      h('strong', { className: 'dsh-lit-content' }, ev.claim || '未命名主张'),
      props.onDelete ? h(Button, { icon: 'close', title: '删除证据', className: 'dsh-lit-btn-danger', disabled: props.busy, onClick: function () { props.onDelete(ev) } }) : null),
    ev.evidence_text ? h('blockquote', { className: 'dsh-lit-text' }, ev.evidence_text) : null,
    h('div', { className: 'dsh-lit-meta' },
      ev.chapter_anchor ? h('span', null, '章节 ' + ev.chapter_anchor) : null,
      ev.page != null && ev.page !== '' ? h('span', null, '页码 ' + ev.page) : null,
      ev.confidence != null ? h('span', null, '置信度 ' + Math.round(Number(ev.confidence) * 100) + '%') : null,
      h('span', { className: 'dsh-lit-muted' }, '#' + ev.id),
      ev.updated_at ? h('span', { className: 'dsh-lit-muted' }, fmtTime(ev.updated_at)) : null),
    ev.note ? h('p', { className: 'dsh-lit-text dsh-lit-meta' }, ev.note) : null,
    props.onOpenDocument && ev.doc_id ? h('div', null,
      h(Button, { icon: 'open', onClick: function () { props.onOpenDocument(ev.doc_id) } }, '文档 #' + ev.doc_id)) : null)
}

function DocDetail(props) {
  const { docId, workspaceId } = props
  const docPath = pathFor('documents', docId, workspaceId)
  const resource = useResource(function () {
    return api(docPath).then(function (res) {
      if (!res || !res.document) throw new Error('文档不存在')
      return res.document
    })
  }, [docId, workspaceId])
  const [busy, setBusy] = React.useState('')
  const lock = React.useRef(false)
  const [notice, setNotice] = React.useState(null)
  const [claim, setClaim] = React.useState('')
  const [stance, setStance] = React.useState('supporting')
  const [text, setText] = React.useState('')
  const fileRef = React.useRef(null)
  const doc = resource.data

  async function run(action, task, success) {
    if (lock.current) return
    lock.current = true
    setBusy(action); setNotice(null)
    try {
      await task()
      if (success) setNotice({ text: success, success: true })
    } catch (error) { setNotice({ text: message(error), error: true }) }
    finally { lock.current = false; setBusy('') }
  }

  function addEvidence(event) {
    event.preventDefault()
    if (!claim.trim()) return
    run('evidence', async function () {
      await api('/evidence', { method: 'POST', body: {
        claim: claim.trim(), stance: stance, evidence_text: text.trim(), doc_id: Number(docId), workspace_id: workspaceId,
      } })
      setClaim(''); setText(''); resource.reload()
    }, '证据已添加')
  }

  function removeEvidence(ev) {
    if (!window.confirm('删除该证据？\n' + short(ev.claim, 90))) return
    run('delete-evidence', async function () {
      await api(pathFor('evidence', ev.id, workspaceId), { method: 'DELETE' })
      resource.reload()
    }, '证据已删除')
  }

  function upload(event) {
    const file = event.target.files && event.target.files[0]
    if (!file) return
    run('upload', async function () {
      try {
        const form = new FormData()
        form.append('file', file); form.append('workspace_id', workspaceId)
        const res = await api('/attachments', { method: 'POST', body: form, raw: true })
        if (!res || !res.attachment_path) throw new Error('上传响应缺少附件路径')
        await api(docPath, { method: 'PATCH', body: { attachment_path: res.attachment_path, attachment_sha256: res.attachment_sha256 } })
        resource.reload()
      } finally { if (fileRef.current) fileRef.current.value = '' }
    }, '附件已上传并关联')
  }

  function openAttachment() {
    run('open', async function () {
      const res = await api('/documents/' + encodeURIComponent(String(docId)) + '/attachment-url')
      const url = res && (res.url || res.attachment_url)
      if (!url) throw new Error('服务端未返回附件链接')
      const target = new URL(url, window.location.href)
      if (target.protocol !== 'https:' && target.protocol !== 'http:') throw new Error('附件链接无效')
      const opened = window.open(url, '_blank')
      if (opened) opened.opener = null
      else setNotice({ text: '浏览器已阻止打开附件', error: true, attachmentUrl: url })
    })
  }

  function archive() {
    const next = doc.lifecycle_status === 'archived' ? 'active' : 'archived'
    run('archive', async function () {
      await api(docPath, { method: 'PATCH', body: { lifecycle_status: next } })
      resource.reload()
    }, next === 'archived' ? '文档已归档' : '文档已恢复')
  }

  function deleteDocument() {
    if (!window.confirm('删除该文档？')) return
    run('delete', async function () {
      await api(docPath, { method: 'DELETE' })
      props.onBack()
    })
  }

  const navigation = h('div', { className: 'dsh-lit-actions' },
    h(Button, { icon: 'back', title: props.backLabel || '返回文档列表', onClick: props.onBack }),
    h('span', { className: 'dsh-lit-title' }, '文档 #' + docId),
    h('span', { className: 'dsh-lit-count' }, resource.loading ? '加载中…' : ''),
    h(Button, { icon: 'refresh', title: '刷新文档', onClick: resource.reload, disabled: resource.loading || !!busy }))

  return h('div', { className: 'dsh-lit-stack', 'aria-busy': resource.loading },
    navigation,
    h(Notice, Object.assign({}, notice)),
    notice && notice.attachmentUrl ? h('a', { className: 'dsh-lit-link', href: notice.attachmentUrl, target: '_blank', rel: 'noopener noreferrer' }, '打开附件') : null,
    h(Notice, { text: resource.error, error: true, retry: resource.reload }),
    doc ? h(React.Fragment, null,
      h('div', { className: 'dsh-lit-stack' },
        h('h2', { className: 'dsh-lit-heading' }, doc.title || '无题录'),
        h('div', { className: 'dsh-lit-meta' },
          doc.lifecycle_status === 'archived' ? archivedChip() : null,
          list(doc.tags).map(function (tag, index) { return h('span', { key: index, className: 'dsh-lit-mini' }, String(tag)) }))),
      h(Section, { title: '元数据', actions: h('div', { className: 'dsh-lit-actions dsh-lit-count' },
        h(Button, { onClick: archive, disabled: !!busy }, doc.lifecycle_status === 'archived' ? '恢复' : '归档'),
        h(Button, { className: 'dsh-lit-btn-danger', onClick: deleteDocument, disabled: !!busy }, '删除')) },
        h(KV, { rows: [
          ['类型', DOC_TYPE[doc.type] || doc.type], ['作者', list(doc.authors).join('、')], ['年份', doc.year],
          ['期刊 / 出处', doc.journal],
          ['DOI', doc.doi ? h('a', { className: 'dsh-lit-link', href: 'https://doi.org/' + encodeURIComponent(doc.doi), target: '_blank', rel: 'noopener noreferrer' }, doc.doi) : null],
          ['ISBN', doc.isbn],
          ['URL', doc.url ? h('a', { className: 'dsh-lit-link', href: doc.url, target: '_blank', rel: 'noopener noreferrer' }, doc.url) : null],
          ['阅读状态', h('select', { className: 'dsh-lit-select', 'aria-label': '阅读状态', value: doc.read_status || 'unread', disabled: !!busy,
            onChange: function (event) {
              const value = event.target.value
              run('read', async function () { await api(docPath, { method: 'PATCH', body: { read_status: value } }); resource.reload() }, '阅读状态已更新')
            } }, Object.keys(READ_STATUS).map(function (key) { return h('option', { key: key, value: key }, READ_STATUS[key]) }))],
          ['生命周期', doc.lifecycle_status === 'archived' ? '已归档' : '活动'],
          ['工作区', doc.workspace_id], ['创建时间', fmtTime(doc.created_at)], ['更新时间', fmtTime(doc.updated_at)],
        ] })),
      h(Section, { title: '附件', actions: h('div', { className: 'dsh-lit-actions dsh-lit-count' },
        h('input', { ref: fileRef, type: 'file', hidden: true, 'aria-label': '选择附件', disabled: !!busy, onChange: upload }),
        h(Button, { icon: 'upload', disabled: !!busy, onClick: function () { fileRef.current.click() } }, busy === 'upload' ? '上传中…' : '上传附件'),
        doc.attachment_path ? h(Button, { icon: 'open', disabled: !!busy, onClick: openAttachment }, busy === 'open' ? '打开中…' : '打开') : null) },
        doc.attachment_path ? h(KV, { rows: [['路径', doc.attachment_path], ['SHA256', doc.attachment_sha256]] }) : h(Empty, null, '暂无附件')),
      h(Section, { title: '关联证据', count: list(doc.evidence).length },
        list(doc.evidence).length ? list(doc.evidence).map(function (ev) {
          return h(EvidenceRow, { key: ev.id, ev: ev, busy: !!busy, onDelete: removeEvidence })
        }) : h(Empty, null, '暂无关联证据')),
      h(Section, { title: '新增证据' },
        h('form', { className: 'dsh-lit-form', onSubmit: addEvidence },
          h('label', { className: 'dsh-lit-field' }, '主张',
            h('input', { className: 'dsh-lit-input', required: true, value: claim, onChange: function (event) { setClaim(event.target.value) } })),
          h('label', { className: 'dsh-lit-field' }, '立场',
            h('select', { className: 'dsh-lit-select', value: stance, onChange: function (event) { setStance(event.target.value) } },
              Object.keys(STANCE).map(function (key) { return h('option', { key: key, value: key }, STANCE[key]) }))),
          h('label', { className: 'dsh-lit-field dsh-lit-field-wide' }, '原文摘录',
            h('textarea', { className: 'dsh-lit-input', value: text, onChange: function (event) { setText(event.target.value) } })),
          h(Button, { type: 'submit', icon: 'add', className: 'dsh-lit-btn-primary', disabled: !!busy || !claim.trim() }, busy === 'evidence' ? '添加中…' : '添加证据'))),
      h('details', { className: 'dsh-lit-section dsh-lit-details' },
        h('summary', null, '摘要 / 全文' + (doc.full_text ? ' · ' + String(doc.full_text).length + ' 字符' : '')),
        doc.full_text ? h('pre', { className: 'dsh-lit-pre' }, String(doc.full_text)) : h(Empty, null, '暂无全文'))
    ) : null)
}

function DocumentsView(props) {
  const workspaceId = props.workspaceId
  const [input, setInput] = React.useState('')
  const [query, setQuery] = React.useState('')
  const [includeArchived, setIncludeArchived] = React.useState(false)
  const [openId, setOpenId] = React.useState(null)
  const resource = useResource(function () {
    return api('/documents' + qs({ workspace_id: workspaceId, q: query, include_archived: includeArchived }))
      .then(function (res) { return list(res && res.documents) })
  }, [workspaceId, query, includeArchived])
  if (openId != null) return h(DocDetail, { key: openId, docId: openId, workspaceId: workspaceId,
    onBack: function () { setOpenId(null); resource.reload() } })
  const docs = resource.data || []
  return h('div', { className: 'dsh-lit-stack', 'aria-busy': resource.loading },
    h('div', { className: 'dsh-lit-actions' },
      h('form', { className: 'dsh-lit-search', role: 'search', onSubmit: function (event) { event.preventDefault(); if (query === input.trim()) resource.reload(); else setQuery(input.trim()) } },
        h('input', { className: 'dsh-lit-input', type: 'search', 'aria-label': '检索文档', placeholder: '标题、作者、期刊、标签', value: input, onChange: function (event) { setInput(event.target.value) } }),
        h(Button, { type: 'submit', icon: 'search', title: '检索文档' })),
      h(ArchiveCheck, { value: includeArchived, onChange: setIncludeArchived }),
      h(Button, { icon: 'refresh', title: '刷新文档列表', disabled: resource.loading, onClick: resource.reload }),
      h('span', { className: 'dsh-lit-count', role: 'status' }, resource.loading ? '加载中…' : docs.length + ' 篇')),
    h(Notice, { text: resource.error, error: true, retry: resource.reload }),
    h('div', { className: 'dsh-lit-list' },
      docs.map(function (doc) {
        return h('button', { key: doc.id, type: 'button', className: 'dsh-lit-rowbtn', onClick: function () { setOpenId(doc.id) } },
          h('span', { className: 'dsh-lit-row-icon', 'aria-hidden': true }, '📄'),
          h('span', { className: 'dsh-lit-content' },
            h('span', { className: 'dsh-lit-actions' },
              h('strong', { className: 'dsh-lit-content' }, doc.title || '无题录'),
              h('span', { className: 'dsh-lit-badge' }, READ_STATUS[doc.read_status] || doc.read_status || READ_STATUS.unread),
              doc.lifecycle_status === 'archived' ? archivedChip() : null),
            h('span', { className: 'dsh-lit-meta' },
              h('span', null, list(doc.authors).join('、') || '佚名'),
              doc.year ? h('span', null, String(doc.year)) : null,
              doc.journal ? h('span', null, doc.journal) : null),
            h('span', { className: 'dsh-lit-meta' },
              doc.type ? h('span', { className: 'dsh-lit-mini' }, DOC_TYPE[doc.type] || doc.type) : null,
              list(doc.tags).map(function (tag, index) { return h('span', { key: index, className: 'dsh-lit-mini' }, String(tag)) }))))
      }),
      !docs.length && !resource.error ? h(Empty, null, resource.loading ? '加载文档…' : query ? '没有匹配的文档' : '暂无文档') : null))
}

const GRAPH_THEME_COLORS = [
  '#3685db', '#d95f76', '#299b83', '#b38a25', '#9274ce', '#289eb8',
  '#d77a40', '#729b38', '#ce6caf', '#647fcb', '#ab775c', '#5f9998',
]

// Undirected, deduplicated relations drive themes; library never affects membership.
function buildGraphThemes(nodes, edges) {
  const adjacency = new Map(nodes.map(function (node) { return [String(node.id), new Set()] }))
  edges.forEach(function (edge) {
    const a = String(edge.source), b = String(edge.target)
    if (a === b || !adjacency.has(a) || !adjacency.has(b)) return
    adjacency.get(a).add(b); adjacency.get(b).add(a)
  })
  const ids = Array.from(adjacency.keys()).sort(function (a, b) {
    return adjacency.get(b).size - adjacency.get(a).size || a.localeCompare(b)
  })
  const labels = new Map(ids.map(function (id) { return [id, id] }))
  // Retaining the current label on ties prevents oscillation; sorted neighbors make refreshes stable.
  for (let pass = 0; pass < 40; pass += 1) {
    let changed = false
    const order = pass % 2 ? ids.slice().reverse() : ids
    order.forEach(function (id) {
      const votes = new Map()
      Array.from(adjacency.get(id)).sort().forEach(function (neighbor) {
        const label = labels.get(neighbor)
        votes.set(label, (votes.get(label) || 0) + 1)
      })
      let best = labels.get(id), score = votes.get(best) || 0
      votes.forEach(function (count, label) { if (count > score) { best = label; score = count } })
      if (best !== labels.get(id)) { labels.set(id, best); changed = true }
    })
    if (!changed) break
  }
  // Split any disconnected remnants of a propagated label, including isolated nodes.
  const visited = new Set(), groups = []
  ids.forEach(function (id) {
    if (visited.has(id)) return
    const members = [id]
    visited.add(id)
    for (let i = 0; i < members.length; i += 1) {
      adjacency.get(members[i]).forEach(function (neighbor) {
        if (!visited.has(neighbor) && labels.get(neighbor) === labels.get(id)) {
          visited.add(neighbor); members.push(neighbor)
        }
      })
    }
    groups.push(members.sort())
  })
  groups.sort(function (a, b) { return b.length - a.length || a[0].localeCompare(b[0]) })
  const nodeMap = new Map(nodes.map(function (node) { return [String(node.id), node] }))
  const byNode = new Map()
  const themes = groups.map(function (members, index) {
    const concepts = new Map()
    members.forEach(function (id) {
      const concept = String(nodeMap.get(id).concept || '').trim()
      if (concept) concepts.set(concept, (concepts.get(concept) || 0) + 1)
    })
    const ranked = members.slice().sort(function (a, b) {
      const ca = String(nodeMap.get(a).concept || '').trim(), cb = String(nodeMap.get(b).concept || '').trim()
      return (concepts.get(cb) || 0) - (concepts.get(ca) || 0) || adjacency.get(b).size - adjacency.get(a).size || a.localeCompare(b)
    })
    const theme = { id: members[0], members: members, representative: ranked[0],
      name: String(nodeMap.get(ranked[0]).concept || '主题 ' + (index + 1)), color: GRAPH_THEME_COLORS[index % GRAPH_THEME_COLORS.length] }
    members.forEach(function (id) { byNode.set(id, theme) })
    return theme
  })
  return { themes: themes, byNode: byNode, adjacency: adjacency }
}

function buildGraphLayout(nodes, edges, width, height, seed, communities, inset) {
  const positions = Object.create(null), islands = []
  if (!nodes.length) return { positions: positions, islands: islands }
  const top = inset ? inset.top : 36, bottom = inset ? inset.bottom : 36
  const usableHeight = Math.max(100, height - top - bottom)
  const aspect = Math.max(0.2, (width - 72) / usableHeight)
  const localEdges = new Map(communities.themes.map(function (theme) { return [theme.id, []] }))
  edges.forEach(function (edge) {
    const a = communities.byNode.get(String(edge.source)), b = communities.byNode.get(String(edge.target))
    if (a && a === b && String(edge.source) !== String(edge.target)) localEdges.get(a.id).push(edge)
  })
  communities.themes.forEach(function (theme) {
    const radius = 42 + Math.sqrt(theme.members.length) * 48
    const island = { theme: theme, x: 0, y: 0, r: radius }
    // Pack nonoverlapping islands near the center, respecting the viewport aspect ratio.
    if (islands.length) {
      let best = null, score = Infinity
      islands.forEach(function (anchor) {
        for (let step = 0; step < 48; step += 1) {
          const angle = step * Math.PI / 24
          const x = anchor.x + Math.cos(angle) * (anchor.r + radius + 24)
          const y = anchor.y + Math.sin(angle) * (anchor.r + radius + 24)
          const cost = x * x / aspect + y * y * aspect
          if (cost >= score || islands.some(function (other) { return Math.hypot(x - other.x, y - other.y) < radius + other.r + 23 })) continue
          best = { x: x, y: y }; score = cost
        }
      })
      island.x = best ? best.x : Math.max.apply(null, islands.map(function (other) { return other.x + other.r })) + radius + 24
      island.y = best ? best.y : 0
    }
    islands.push(island)
    const points = theme.members.map(function (id, index) {
      const angle = (index + seed * 0.618) * 2.399963229728653
      const spread = theme.members.length === 1 ? 0 : (radius - 44) * Math.sqrt((index + 0.5) / theme.members.length)
      const point = { id: id, x: Math.cos(angle) * spread, y: Math.sin(angle) * spread,
        vx: 0, vy: 0, r: 9 + Math.min(10, Math.sqrt(communities.adjacency.get(id).size) * 1.8) }
      positions[id] = point
      return point
    })
    const iterations = points.length > 240 ? 160 : 280
    function constrain(point) {
      const distance = Math.hypot(point.x, point.y), limit = radius - point.r - 22
      if (distance > limit) { point.x *= limit / distance; point.y *= limit / distance }
    }
    for (let tick = 0; tick < iterations; tick += 1) {
      for (let i = 0; i < points.length; i += 1) {
        const a = points[i]
        for (let j = i + 1; j < points.length; j += 1) {
          const b = points[j]
          const dx = b.x - a.x || 0.01, dy = b.y - a.y || 0.01
          const distance = Math.hypot(dx, dy), min = a.r + b.r + 48
          const repulsion = Math.min(8, 12000 / (distance * distance)) + Math.max(0, min - distance) * 0.16
          const fx = dx / distance * repulsion, fy = dy / distance * repulsion
          a.vx -= fx; a.vy -= fy; b.vx += fx; b.vy += fy
        }
      }
      localEdges.get(theme.id).forEach(function (edge) {
        const a = positions[String(edge.source)], b = positions[String(edge.target)]
        const dx = b.x - a.x, dy = b.y - a.y, distance = Math.hypot(dx, dy) || 1
        const pull = (distance - 170) * 0.009
        a.vx += dx / distance * pull; a.vy += dy / distance * pull
        b.vx -= dx / distance * pull; b.vy -= dy / distance * pull
      })
      points.forEach(function (point) {
        point.vx = (point.vx - point.x * 0.002) * 0.65
        point.vy = (point.vy - point.y * 0.002) * 0.65
        point.x += point.vx * (1 - tick / iterations * 0.7)
        point.y += point.vy * (1 - tick / iterations * 0.7)
        constrain(point)
      })
    }
    for (let pass = 0; pass < 32; pass += 1) {
      points.forEach(function (a, i) {
        for (let j = i + 1; j < points.length; j += 1) {
          const b = points[j], dx = b.x - a.x || 0.01, dy = b.y - a.y || 0.01
          const distance = Math.hypot(dx, dy), shift = Math.max(0, a.r + b.r + 44 - distance) / 2
          a.x -= dx / distance * shift; a.y -= dy / distance * shift
          b.x += dx / distance * shift; b.y += dy / distance * shift
        }
      })
      points.forEach(constrain)
    }
    points.forEach(function (point) { point.x += island.x; point.y += island.y })
  })
  const minX = Math.min.apply(null, islands.map(function (island) { return island.x - island.r }))
  const maxX = Math.max.apply(null, islands.map(function (island) { return island.x + island.r }))
  const minY = Math.min.apply(null, islands.map(function (island) { return island.y - island.r }))
  const maxY = Math.max.apply(null, islands.map(function (island) { return island.y + island.r }))
  const scale = Math.min((width - 72) / (maxX - minX), usableHeight / (maxY - minY))
  function fit(point) {
    point.x = width / 2 + (point.x - (minX + maxX) / 2) * scale
    point.y = top + usableHeight / 2 + (point.y - (minY + maxY) / 2) * scale
    point.r *= scale
  }
  Object.keys(positions).forEach(function (id) { fit(positions[id]) })
  islands.forEach(fit)
  return { positions: positions, islands: islands }
}

function KnowledgeDetail(props) {
  const { kid, workspaceId } = props
  const [docId, setDocId] = React.useState(null)
  const resource = useResource(async function () {
    const res = await api(pathFor('knowledge', kid, workspaceId))
    if (!res || !res.knowledge) throw new Error('知识条目不存在')
    const item = res.knowledge
    const evidence = await Promise.all(list(item.sources).map(async function (id) {
      try {
        const result = await api(pathFor('evidence', id, workspaceId))
        if (!result || !result.evidence) throw new Error('证据不存在')
        return { id: id, evidence: result.evidence }
      } catch (error) { return { id: id, error: message(error) } }
    }))
    return { item: item, evidence: evidence }
  }, [kid, workspaceId])
  if (docId != null) return h(DocDetail, { key: docId, docId: docId, workspaceId: workspaceId, backLabel: '返回知识详情', onBack: function () { setDocId(null); resource.reload() } })
  const data = resource.data
  const item = data && data.item
  return h('div', { className: 'dsh-lit-stack', 'aria-busy': resource.loading },
    h('div', { className: 'dsh-lit-actions' },
      h(Button, { icon: 'back', title: props.backLabel || '返回知识列表', onClick: props.onBack }),
      h('span', { className: 'dsh-lit-title' }, '知识 #' + kid),
      h('span', { className: 'dsh-lit-count' }, resource.loading ? '加载中…' : ''),
      h(Button, { icon: 'refresh', title: '刷新知识详情', onClick: resource.reload, disabled: resource.loading })),
    h(Notice, { text: resource.error, error: true, retry: resource.reload }),
    item ? h(React.Fragment, null,
      h('h2', { className: 'dsh-lit-heading' }, item.concept || '无概念名'),
      h(Section, { title: '条目信息' }, h(KV, { rows: [
        ['知识库', libraryChip(item.library)], ['状态', isArchived(item) ? archivedChip() : '活动'],
        ['source_memory_id', item.source_memory_id], ['条目 ID', String(item.id)], ['工作区', item.workspace_id],
        ['创建时间', fmtTime(item.created_at)], ['更新时间', fmtTime(item.updated_at)],
      ] })),
      h(Section, { title: '摘要' }, item.summary ? h('p', { className: 'dsh-lit-text' }, item.summary) : h(Empty, null, '暂无摘要')),
      h(Section, { title: '笔记' }, item.notes ? h('p', { className: 'dsh-lit-text' }, item.notes) : h(Empty, null, '暂无笔记')),
      h(Section, { title: '关联关系', count: list(item.relations).length },
        list(item.relations).length ? list(item.relations).map(function (relation, index) {
          return h('div', { key: index, className: 'dsh-lit-row' },
            h('div', { className: 'dsh-lit-relation' },
              h('span', { className: 'dsh-lit-content' }, String(relation.source == null ? relation.source_id : relation.source)),
              h('span', { className: 'dsh-lit-mini' }, String(relation.relation || '关联') + ' →'),
              h('span', { className: 'dsh-lit-content' }, String(relation.target == null ? relation.target_id : relation.target))))
        }) : h(Empty, null, '暂无关联关系')),
      h(Section, { title: '关联证据', count: data.evidence.length },
        data.evidence.length ? data.evidence.map(function (result) {
          return result.evidence ? h(EvidenceRow, { key: result.id, ev: result.evidence, onOpenDocument: setDocId })
            : h(Notice, { key: result.id, text: '证据 #' + result.id + '：' + result.error, error: true, retry: resource.reload })
        }) : h(Empty, null, '暂无关联证据'))
    ) : null)
}

function KnowledgeView(props) {
  const workspaceId = props.workspaceId
  const [library, setLibrary] = React.useState('')
  const [includeArchived, setIncludeArchived] = React.useState(false)
  const [openId, setOpenId] = React.useState(null)
  const resource = useResource(async function () {
    const results = await Promise.all((includeArchived ? [false, true] : [false]).map(function (archived) {
      return api('/knowledge-browse' + qs({ workspace_id: workspaceId, library: library, archived: archived, k: 1000 }))
    }))
    const byId = new Map()
    results.forEach(function (result) { list(result && result.items).forEach(function (item) { byId.set(String(item.id), item) }) })
    return Array.from(byId.values()).sort(function (a, b) { return Number(b.id) - Number(a.id) })
  }, [workspaceId, library, includeArchived])
  if (openId != null) return h(KnowledgeDetail, { key: openId, kid: openId, workspaceId: workspaceId, onBack: function () { setOpenId(null) } })
  const items = resource.data || []
  return h('div', { className: 'dsh-lit-stack', 'aria-busy': resource.loading },
    h('div', { className: 'dsh-lit-actions' },
      h(LibrarySelect, { value: library, onChange: setLibrary }),
      h(ArchiveCheck, { value: includeArchived, onChange: setIncludeArchived }),
      h(Button, { icon: 'refresh', title: '刷新知识列表', onClick: resource.reload, disabled: resource.loading }),
      h('span', { className: 'dsh-lit-count', role: 'status' }, resource.loading ? '加载中…' : items.length + ' 条')),
    h(Notice, { text: resource.error, error: true, retry: resource.reload }),
    h('div', { className: 'dsh-lit-list' },
      items.map(function (item) {
        return h('button', { key: item.id, type: 'button', className: 'dsh-lit-rowbtn', onClick: function () { setOpenId(item.id) } },
          h('span', { className: 'dsh-lit-row-icon', 'aria-hidden': true }, '◇'),
          h('span', { className: 'dsh-lit-content' },
            h('span', { className: 'dsh-lit-actions' },
              h('strong', { className: 'dsh-lit-content' }, item.concept || '无概念名'),
              libraryChip(item.library), isArchived(item) ? archivedChip() : null),
            item.summary ? h('span', { className: 'dsh-lit-text' }, item.summary) : null,
            h('span', { className: 'dsh-lit-meta' },
              h('span', { className: 'dsh-lit-muted' }, '#' + item.id),
              item.source_memory_id != null ? h('span', { className: 'dsh-lit-muted' }, 'memory #' + item.source_memory_id) : null,
              item.updated_at ? h('span', { className: 'dsh-lit-muted' }, fmtTime(item.updated_at)) : null)))
      }),
      !items.length && !resource.error ? h(Empty, null, resource.loading ? '加载知识…' : '暂无匹配的知识条目') : null))
}

function GraphView(props) {
  const [library, setLibrary] = React.useState('')
  const [detailId, setDetailId] = React.useState(null)
  const [fullscreen, setFullscreen] = React.useState(false)
  const [size, setSize] = React.useState({ width: 1080, height: 800 })
  const [hover, setHover] = React.useState(null)
  const [selNode, setSelNode] = React.useState(null)
  const [tf, setTf] = React.useState({ k: 0.27, x: 0, y: 0 })
  const [overrides, setOverrides] = React.useState({})
  const [seed, setSeed] = React.useState(0)
  const rootRef = React.useRef(null)
  const fullscreenButton = React.useRef(null)
  const lastNode = React.useRef(null)
  const svgRef = React.useRef(null)
  const gesture = React.useRef(null)
  const resource = useResource(async function () {
    const res = await api('/graph' + qs({ workspace_id: props.workspaceId, library: library }))
    const graph = res && (res.graph || res) || {}
    const unique = new Map()
    list(graph.nodes).forEach(function (node) { if (node && node.id != null) unique.set(String(node.id), node) })
    return { nodes: Array.from(unique.values()), edges: list(graph.edges).filter(function (edge) {
      return edge && unique.has(String(edge.source)) && unique.has(String(edge.target))
    }) }
  }, [props.workspaceId, library])
  const nodes = resource.data ? resource.data.nodes : []
  const edges = resource.data ? resource.data.edges : []
  // 无限画布：世界坐标系（WORLD_W×WORLD_H，节点铺开不压缩），SVG viewBox 即世界，
  // <g transform> 缩放平移让视窗显示任意区域（k/x/y 由用户滚轮/拖拽控制）。
  const WORLD_W = 4000, WORLD_H = 3000
  const W = WORLD_W, H = WORLD_H
  const communities = React.useMemo(function () { return buildGraphThemes(nodes, edges) }, [resource.data])
  const layout = React.useMemo(function () {
    return buildGraphLayout(nodes, edges, WORLD_W, WORLD_H, seed, communities,
      fullscreen ? { top: 140, bottom: 120 } : null)
  }, [communities, seed, fullscreen])
  function fitContent() {
    // 自动 fit 到节点包围盒并居中放大（视窗有限、画布无限）。tf 平移在 viewBox
    // 用户坐标系里，而 CSS 视口经 xMidYMid meet letterbox 映射：可见区中心恒为
    // (W/2, H/2)，可见区用户尺寸 = 视口像素 ÷ 映射比例，并截断到 viewBox 范围。
    const positions = layout.positions || {}
    const ids = Object.keys(positions)
    if (!ids.length) { setTf({ k: 0.27, x: W / 2, y: H / 2 }); return }
    const svg = svgRef.current
    const rect = svg ? svg.getBoundingClientRect() : null
    const vpW = (rect && rect.width) || size.width || 1080
    const vpH = (rect && rect.height) || size.height || 800
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    ids.forEach(function (id) {
      const p = positions[id]; if (!p) return
      const r = (p.r || 9) + 12
      if (p.x - r < minX) minX = p.x - r
      if (p.y - r < minY) minY = p.y - r
      if (p.x + r > maxX) maxX = p.x + r
      if (p.y + r > maxY) maxY = p.y + r
    })
    const bboxW = Math.max(1, maxX - minX), bboxH = Math.max(1, maxY - minY)
    const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2
    const pxPerUnit = Math.min(vpW / W, vpH / H) || 0.27
    const visibleW = Math.min(W, vpW / pxPerUnit), visibleH = Math.min(H, vpH / pxPerUnit)
    const k = Math.max(0.12, Math.min(8, Math.min(visibleW / bboxW, visibleH / bboxH) * 0.88))
    const x = W / 2 - cx * k
    const y = H / 2 - cy * k
    setTf({ k: k, x: x, y: y })
  }
  React.useEffect(function () {
    setDetailId(null); setHover(null); setOverrides({}); gesture.current = null
  }, [resource.data])
  React.useEffect(function () {
    const svg = svgRef.current
    if (!svg) return
    function measure() {
      const rect = svg.getBoundingClientRect()
      if (!rect.width || !rect.height) return
      const width = Math.round(rect.width), height = Math.round(rect.height)
      setSize(function (previous) { return previous.width === width && previous.height === height ? previous : { width: width, height: height } })
    }
    measure()
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(measure) : null
    if (observer) observer.observe(svg)
    window.addEventListener('resize', measure)
    return function () { if (observer) observer.disconnect(); window.removeEventListener('resize', measure) }
  }, [])
  React.useEffect(function () {
    setOverrides({}); gesture.current = null
    fitContent()
  }, [W, H, fullscreen, layout])
  React.useEffect(function () {
    const root = rootRef.current
    function changed() { setFullscreen(document.fullscreenElement === root) }
    document.addEventListener('fullscreenchange', changed)
    return function () {
      document.removeEventListener('fullscreenchange', changed)
      if (document.fullscreenElement === root && document.exitFullscreen) document.exitFullscreen().catch(function () {})
    }
  }, [])
  React.useEffect(function () {
    if (!fullscreen) return
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    function escape(event) {
      if (event.key !== 'Escape') return
      event.preventDefault(); event.stopPropagation()
      exitFullscreen()
    }
    document.addEventListener('keydown', escape, true)
    return function () { document.body.style.overflow = overflow; document.removeEventListener('keydown', escape, true) }
  }, [fullscreen])

  function exitFullscreen() {
    if (document.fullscreenElement === rootRef.current && document.exitFullscreen) {
      document.exitFullscreen().catch(function () {})
    } else setFullscreen(false)
    if (fullscreenButton.current) fullscreenButton.current.focus()
  }

  async function toggleFullscreen() {
    if (fullscreen) { exitFullscreen(); return }
    const root = rootRef.current
    if (root && root.requestFullscreen) {
      try { await root.requestFullscreen(); return } catch (error) { /* Embedded hosts may disable the native fullscreen API. */ }
    }
    setFullscreen(true)
  }

  function openDetail(node) {
    lastNode.current = String(node.id)
    setHover(null); setDetailId(node.id)
  }

  function backToGraph() {
    setDetailId(null)
    window.requestAnimationFrame(function () {
      const svg = svgRef.current
      if (!svg) return
      const node = Array.from(svg.querySelectorAll('[data-node-id]')).find(function (element) { return element.dataset.nodeId === lastNode.current })
      if (node) node.focus({ preventScroll: true })
    })
  }

  // getScreenCTM includes SVG letterboxing, unlike independent width/height ratios.
  function pointInSvg(event) {
    const svg = svgRef.current
    const matrix = svg && svg.getScreenCTM()
    if (!matrix) return null
    const point = svg.createSVGPoint()
    point.x = event.clientX; point.y = event.clientY
    return point.matrixTransform(matrix.inverse())
  }

  React.useEffect(function () {
    const svg = svgRef.current
    if (!svg || detailId != null) return
    function wheel(event) {
      event.preventDefault()
      event.stopPropagation()
      const point = pointInSvg(event)
      if (!point) return
      const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? H : 1)
      setTf(function (previous) {
        const k = Math.max(0.35, Math.min(6, previous.k * Math.exp(-delta * 0.0015)))
        return { k: k, x: point.x - (point.x - previous.x) * k / previous.k, y: point.y - (point.y - previous.y) * k / previous.k }
      })
    }
    svg.addEventListener('wheel', wheel, { passive: false })
    return function () { svg.removeEventListener('wheel', wheel) }
  }, [detailId, H])

  function pos(id) { return overrides[String(id)] || layout.positions[String(id)] }

  function start(event, node) {
    if (event.button !== 0 || gesture.current) return
    const point = pointInSvg(event)
    if (!point) return
    event.preventDefault(); event.stopPropagation()
    const position = node ? pos(node.id) : null
    gesture.current = {
      pointerId: event.pointerId, node: node || null, start: point, clientX: event.clientX, clientY: event.clientY,
      x: position ? position.x : tf.x, y: position ? position.y : tf.y, k: tf.k, moved: false,
    }
    svgRef.current.setPointerCapture(event.pointerId)
  }

  function move(event) {
    const drag = gesture.current
    if (!drag || drag.pointerId !== event.pointerId) return
    const point = pointInSvg(event)
    if (!point) return
    if (Math.hypot(event.clientX - drag.clientX, event.clientY - drag.clientY) > 3) drag.moved = true
    if (!drag.moved) return
    const dx = point.x - drag.start.x, dy = point.y - drag.start.y
    if (drag.node) {
      setOverrides(function (previous) {
        return Object.assign({}, previous, { [String(drag.node.id)]: {
          id: String(drag.node.id), r: layout.positions[String(drag.node.id)].r, x: drag.x + dx / drag.k, y: drag.y + dy / drag.k,
        } })
      })
    } else setTf({ k: drag.k, x: drag.x + dx, y: drag.y + dy })
  }

  function finish(event, cancelled) {
    const drag = gesture.current
    if (!drag || drag.pointerId !== event.pointerId) return
    gesture.current = null
    const svg = svgRef.current
    if (svg && svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId)
    if (!cancelled && !drag.moved && drag.node) openDetail(drag.node)
  }

  function zoom(factor) {
    setTf(function (previous) {
      const k = Math.max(0.12, Math.min(8, previous.k * factor))
      return { k: k, x: W / 2 - (W / 2 - previous.x) * k / previous.k, y: H / 2 - (H / 2 - previous.y) * k / previous.k }
    })
  }

  function reset() { setOverrides({}); setSeed(function (value) { return value + 1 }) }
  const neighbors = new Set(hover == null ? [] : [hover])
  const degree = {}
  edges.forEach(function (edge) {
    const source = String(edge.source), target = String(edge.target)
    degree[source] = (degree[source] || 0) + 1; degree[target] = (degree[target] || 0) + 1
    if (source === hover) neighbors.add(target)
    if (target === hover) neighbors.add(source)
  })
  const counts = {}
  nodes.forEach(function (node) { const library = LIBRARIES.indexOf(node.library) >= 0 ? node.library : 'unknown'; counts[library] = (counts[library] || 0) + 1 })

  if (detailId != null) return h(KnowledgeDetail, { key: detailId, kid: detailId, workspaceId: props.workspaceId, backLabel: '返回图谱', onBack: function () { setDetailId(null) } })

  return h('div', { className: 'dsh-lit-stack', 'aria-busy': resource.loading },
    h('div', { className: 'dsh-lit-actions' },
      h(LibrarySelect, { value: library, onChange: setLibrary }),
      h(Button, { icon: 'refresh', title: '刷新图谱', onClick: resource.reload, disabled: resource.loading }),
      h(Button, { icon: 'reset', title: '重排并重置视图', onClick: reset, disabled: !nodes.length }),
      h(Button, { icon: 'zoomOut', title: '缩小', onClick: function () { zoom(1 / 1.25) }, disabled: tf.k <= 0.12 }),
      h('span', { className: 'dsh-lit-mini', style: { minWidth: 44, justifyContent: 'center' } }, Math.round(tf.k * 100) + '%'),
      h(Button, { icon: 'zoomIn', title: '放大', onClick: function () { zoom(1.25) }, disabled: tf.k >= 8 }),
      h('span', { className: 'dsh-lit-count' }, nodes.length + ' 节点 · ' + edges.length + ' 关系')),
    h(Notice, { text: resource.error, error: true, retry: resource.reload }),
    h('div', { className: 'dsh-lit-graph-legend', 'aria-label': '知识库图例' },
      LIBRARIES.concat('unknown').filter(function (library) { return library !== 'unknown' || counts.unknown }).map(function (library) {
        return h('span', { key: library, className: 'dsh-lit-graph-key' },
          h('i', { className: 'dsh-lit-graph-dot', style: { background: libraryColor(library) }, 'aria-hidden': true }),
          (LIB_LABEL[library] || '未分类') + ' ' + (counts[library] || 0))
      })),
    h('div', { className: 'dsh-lit-graphbox' + (selNode ? ' dsh-lit-graphbox-selected' : '') },
      h('div', { className: 'dsh-lit-graph-stage' },
        h('svg', {
          ref: svgRef, className: 'dsh-lit-graph-svg', viewBox: '0 0 ' + W + ' ' + H, role: 'group', 'aria-label': '知识概念关系图',
          onPointerDown: function (event) { start(event, null) }, onPointerMove: move,
          onPointerUp: function (event) { finish(event, false) }, onPointerCancel: function (event) { finish(event, true) },
          onLostPointerCapture: function () { gesture.current = null },
        }, h('g', { transform: 'translate(' + tf.x + ',' + tf.y + ') scale(' + tf.k + ')' },
          edges.map(function (edge, index) {
            const a = pos(edge.source), b = pos(edge.target)
            if (!a || !b) return null
            const hot = hover == null || String(edge.source) === hover || String(edge.target) === hover
            return h('line', { key: 'e' + index, className: 'dsh-lit-graph-edge', x1: a.x, y1: a.y, x2: b.x, y2: b.y,
              opacity: hot ? 1 : 0.15, strokeWidth: hover != null && hot ? 2.5 : 1.4 },
              h('title', null, (edge.source_concept || edge.source) + ' → ' + (edge.relation || '关联') + ' → ' + (edge.target_concept || edge.target)))
          }),
          nodes.map(function (node) {
            const point = pos(node.id)
            if (!point) return null
            const selected = selNode && String(selNode.id) === String(node.id)
            const hot = hover === String(node.id) || selected
            return h('g', {
              key: 'n' + node.id, className: 'dsh-lit-graph-node', 'data-node-id': String(node.id),
              tabIndex: 0, role: 'button', 'aria-label': node.concept || String(node.id), 'aria-pressed': !!selected,
              opacity: hover != null && !neighbors.has(String(node.id)) ? 0.25 : 1,
              onPointerDown: function (event) { start(event, node) },
              onClick: function () { setSelNode(node) },
              onPointerEnter: function () { setHover(String(node.id)) }, onPointerLeave: function () { setHover(null) },
              onFocus: function () { setHover(String(node.id)) }, onBlur: function () { setHover(null) },
              onKeyDown: function (event) {
                if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelNode(node) }
              },
            },
              h('title', null, (node.concept || node.id) + ' · ' + (LIB_LABEL[node.library] || '未分类') + ' · ' + (degree[String(node.id)] || 0) + ' 关系'),
              h('circle', { cx: point.x, cy: point.y, r: point.r, fill: libraryColor(node.library),
                stroke: hot ? 'var(--dsw-alias-label-primary)' : 'var(--dsw-alias-bg-layer-1)', strokeWidth: hot ? 2.5 : 1 }),
              h('text', { x: point.x, y: point.y + point.r + 14, className: 'dsh-lit-graph-label', textAnchor: 'middle' }, short(node.concept || node.id, 22)))
          }))),
        resource.loading || !nodes.length ? h('div', { className: 'dsh-lit-graph-overlay', role: 'status' },
          resource.loading ? '加载图谱…' : resource.error ? '图谱加载失败' : '暂无匹配的图谱节点') : null),
      selNode ? h('aside', { className: 'dsh-lit-side', 'aria-label': '节点详情' },
        h('div', { className: 'dsh-lit-actions' },
          h('span', { className: 'dsh-lit-title dsh-lit-content' }, '知识 #' + selNode.id),
          h(Button, { icon: 'close', title: '关闭节点详情', onClick: function () { setSelNode(null) } })),
        h('h2', { className: 'dsh-lit-heading' }, selNode.concept || '无概念名'),
        h('div', null, libraryChip(selNode.library)),
        selNode.summary ? h('p', { className: 'dsh-lit-text' }, selNode.summary) : null,
        h(KV, { rows: [['关联关系', degree[String(selNode.id)] || 0]] }),
        h(Button, { icon: 'open', className: 'dsh-lit-btn-primary', onClick: function () { setDetailId(selNode.id) } }, '知识详情')) : null))
}

function StatusView(props) {
  const resource = useResource(async function () {
    const ws = props.workspaceId
    const sources = {
      kb: '/kb/browse', count: '/knowledge-count' + qs({ workspace_id: ws }),
      active: '/knowledge-browse' + qs({ workspace_id: ws, archived: false, k: 1000 }),
      archived: '/knowledge-browse' + qs({ workspace_id: ws, archived: true, k: 1000 }),
      graph: '/graph' + qs({ workspace_id: ws }), config: '/config',
    }
    const result = {}
    await Promise.all(Object.keys(sources).map(async function (key) {
      try { result[key] = { value: await api(sources[key]) } }
      catch (error) { result[key] = { error: message(error) } }
    }))
    return result
  }, [props.workspaceId])
  const data = resource.data
  function card(title, value, lines, error) {
    return h('article', { className: 'dsh-lit-box dsh-lit-stat', key: title },
      h('h3', { className: 'dsh-lit-title' }, title),
      h('div', { className: 'dsh-lit-stat-big' }, resource.loading ? '…' : error ? '—' : value),
      h('div', { className: 'dsh-lit-stat-lines' }, lines.map(function (line, index) { return h('div', { key: index }, line) })),
      h(Notice, { text: error, error: true, retry: resource.reload }))
  }
  const cards = []
  const kb = data && data.kb.value && data.kb.value.libraries || {}
  const kbIds = Object.keys(kb)
  const kbTotal = kbIds.reduce(function (sum, key) { return sum + Number(kb[key].total || 0) }, 0)
  const kbArchived = kbIds.reduce(function (sum, key) { return sum + Number(kb[key].archived || 0) }, 0)
  cards.push(card('deepmemory 记忆库', kbTotal + ' 条', data ? [
    '知识库 ' + kbIds.length + ' 个 · 归档 ' + kbArchived + ' 条',
    kbIds.map(function (key) { return key + ' ' + Number(kb[key].total || 0) }).join(' · ') || '暂无库数据',
  ] : [], data && data.kb.error))
  const active = list(data && data.active.value && data.active.value.items)
  const archived = list(data && data.archived.value && data.archived.value.items)
  const perLibrary = {}
  active.forEach(function (item) { perLibrary[item.library] = (perLibrary[item.library] || 0) + 1 })
  const count = data && data.count.value && data.count.value.count
  cards.push(card('本库知识', count == null ? '—' : count + ' 条', data ? [
    data.active.error ? '分库计数不可用' : (active.length >= 1000 ? '已载入：' : '') + LIBRARIES.map(function (library) { return library + ' ' + (perLibrary[library] || 0) }).join(' · '),
    data.archived.error ? '归档计数不可用' : '另归档 ' + (archived.length >= 1000 ? '至少 ' : '') + archived.length + ' 条',
  ] : [], data && [data.count.error, data.active.error, data.archived.error].filter(Boolean).join('；')))
  const graph = data && data.graph.value && data.graph.value.graph || {}
  cards.push(card('图谱规模', list(graph.nodes).length + ' 节点', data ? [
    list(graph.edges).length + ' 条关系',
    LIBRARIES.map(function (library) { return library + ' ' + list(graph.nodes).filter(function (node) { return node.library === library }).length }).join(' · '),
  ] : [], data && data.graph.error))
  const config = data && data.config.value && data.config.value.config || {}
  const keys = Object.keys(config)
  cards.push(card('配置摘要', keys.length + ' 项', data ? keys.length ? keys.slice(0, 7).map(function (key) {
    const value = typeof config[key] === 'string' ? config[key] : JSON.stringify(config[key])
    return h('span', { title: key + ': ' + value }, key + ': ' + short(value, 80))
  }).concat(keys.length > 7 ? ['其余 ' + (keys.length - 7) + ' 项'] : []) : ['暂无自定义配置'] : [], data && data.config.error))
  return h('div', { className: 'dsh-lit-stack', 'aria-busy': resource.loading },
    h('div', { className: 'dsh-lit-actions' },
      h('h2', { className: 'dsh-lit-title dsh-lit-content' }, '状况'),
      h(Button, { icon: 'refresh', title: '刷新状况', onClick: resource.reload, disabled: resource.loading })),
    h(Notice, { text: resource.error, error: true, retry: resource.reload }),
    h('div', { className: 'dsh-lit-stat-grid' }, cards))
}

const TABS = [
  { id: 'docs', label: '📄 文档', component: DocumentsView },
  { id: 'knowledge', label: '🧠 知识', component: KnowledgeView },
  { id: 'graph', label: '🕸 图谱', component: GraphView },
  { id: 'status', label: '📊 状况', component: StatusView },
]

function PanelBody(props) {
  const [view, setView] = React.useState('docs')
  const [visited, setVisited] = React.useState({ docs: true })
  const [workspace, setWorkspace] = React.useState(props.workspaceId || DEFAULT_WORKSPACE)
  const [wsOptions, setWsOptions] = React.useState([])
  const tabRefs = React.useRef([])
  const panelId = React.useId()
  React.useEffect(function () {
    api('/workspaces').then(function (data) {
      setWsOptions((data && data.workspaces) || [])
    }).catch(function () { /* 拉取失败仅影响下拉枚举，不影响主面板 */ })
  }, [])
  function select(id) {
    setView(id)
    setVisited(function (previous) { return Object.assign({}, previous, { [id]: true }) })
  }
  function switchWorkspace(value) {
    const next = value || DEFAULT_WORKSPACE
    setWorkspace(next)
    setVisited(function (previous) {
      const fresh = Object.assign({}, previous)
      Object.keys(fresh).forEach(function (k) { fresh[k] = false })
      fresh.docs = true
      return fresh
    })
    setView('docs')
  }
  function tabKey(event, index) {
    let next = index
    if (event.key === 'ArrowRight') next = (index + 1) % TABS.length
    else if (event.key === 'ArrowLeft') next = (index + TABS.length - 1) % TABS.length
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = TABS.length - 1
    else return
    event.preventDefault()
    select(TABS[next].id)
    tabRefs.current[next].focus()
  }
  const shellItems = list(props.shellWorkspaces)
  function wsLabel(id) {
    const server = wsOptions.find(function (w) { return String(w.workspace_id) === String(id) })
    const shell = shellItems.find(function (w) { return String(w.workspaceId || w.id || '') === String(id) })
    const title = String((shell && (shell.title || shell.name)) || (server && server.title) || id || '')
    return server ? title + ' (' + Number(server.knowledge || 0) + ')' : title
  }
  return h('div', { className: 'dsh-lit-panel', 'data-dsh-style': 'deepmemory-tokens-v2' },
    h('header', { className: 'dsh-lit-topbar' },
      h('h1', { className: 'dsh-lit-brand' }, '📚 literature 文献知识库'),
      h('select', {
        className: 'dsh-lit-select', 'aria-label': '选择工作区',
        value: workspace, onChange: function (event) { switchWorkspace(event.target.value) },
      }, [
        h('option', { key: 'cur', value: workspace }, wsLabel(workspace)),
        wsOptions.filter(function (w) { return w.workspace_id !== workspace }).map(function (w) {
          return h('option', { key: w.workspace_id, value: w.workspace_id }, wsLabel(w.workspace_id))
        }),
      ]),
      h('span', { className: 'dsh-lit-ws', title: '当前会话工作区' }, '会话: ' + props.workspaceId)),
    h('div', { className: 'dsh-lit-tabs', role: 'tablist', 'aria-label': '文献知识库视图' },
      TABS.map(function (tab, index) {
        return h('button', {
          key: tab.id, type: 'button', className: 'dsh-lit-tab', role: 'tab',
          id: panelId + '-tab-' + tab.id, 'aria-controls': panelId + '-view-' + tab.id,
          'aria-selected': view === tab.id, tabIndex: view === tab.id ? 0 : -1,
          ref: function (element) { tabRefs.current[index] = element },
          onKeyDown: function (event) { tabKey(event, index) }, onClick: function () { select(tab.id) },
        }, tab.label)
      })),
    TABS.map(function (tab) {
      return h('div', {
        key: tab.id, id: panelId + '-view-' + tab.id, className: 'dsh-lit-view', role: 'tabpanel',
        'aria-labelledby': panelId + '-tab-' + tab.id, hidden: view !== tab.id,
      }, visited[tab.id] ? h(tab.component, { workspaceId: workspace }) : null)
    }))
}

function LiteraturePanel(props) {
  const sessions = useShellSnapshot(shellServices.sessions, { current: undefined })
  const workspaces = useShellSnapshot(shellServices.workspaces, { items: [] })
  // 后端工作区表（含 session_ids）：作为「当前会话 → 工作区」的权威解析源
  const [serverWs, setServerWs] = React.useState(null)
  React.useEffect(function () {
    api('/workspaces').then(function (d) {
      setServerWs((d && d.workspaces) || [])
    }).catch(function () { setServerWs([]) })
  }, [])
  const workspaceId = resolveWorkspaceId(props, sessions, workspaces, serverWs)
  return h(PanelBody, { key: workspaceId, workspaceId: workspaceId, shellWorkspaces: workspaces.items || [] })
}

function ConfigView() {
  const [values, setValues] = React.useState({})
  const [busy, setBusy] = React.useState(false)
  const [notice, setNotice] = React.useState(null)
  const resource = useResource(async function () {
    const results = await Promise.all([api('/config-schema'), api('/config')])
    if (!results[0] || !results[0].schema) throw new Error('配置结构不可用')
    return { schema: results[0].schema, values: results[1] && results[1].config || {} }
  }, [])
  const schema = resource.data && resource.data.schema
  const formId = React.useId()
  React.useEffect(function () { if (resource.data) setValues(resource.data.values) }, [resource.data])
  function setValue(key, value) { setValues(function (previous) { return Object.assign({}, previous, { [key]: value }) }) }
  function valueFor(key, spec) { return values[key] === undefined ? spec.default : values[key] }
  function numeric(spec) { return ['number', 'integer', 'int', 'float'].indexOf(spec.type) >= 0 }
  function field(key, spec) {
    const value = valueFor(key, spec)
    const base = { id: formId + key, disabled: busy || !!spec.readonly }
    if (spec.type === 'boolean' || spec.type === 'bool') return h('input', Object.assign({}, base, {
      type: 'checkbox', checked: value === true || value === 1 || value === 'true',
      onChange: function (event) { setValue(key, event.target.checked) },
    }))
    if (Array.isArray(spec.options)) return h('select', Object.assign({}, base, {
      className: 'dsh-lit-select', value: value == null ? '' : String(value),
      onChange: function (event) { setValue(key, numeric(spec) ? Number(event.target.value) : event.target.value) },
    }), spec.options.map(function (option) { return h('option', { key: String(option), value: String(option) }, String(option)) }))
    if (['text', 'array', 'list'].indexOf(spec.type) >= 0) return h('textarea', Object.assign({}, base, {
      className: 'dsh-lit-input', rows: 3,
      value: Array.isArray(value) ? value.join('\n') : value == null ? '' : String(value),
      onChange: function (event) { setValue(key, spec.type === 'text' ? event.target.value : event.target.value.split(/[,，\n]/).map(function (item) { return item.trim() }).filter(Boolean)) },
    }))
    return h('input', Object.assign({}, base, {
      className: 'dsh-lit-input', type: numeric(spec) ? 'number' : 'text',
      step: spec.type === 'number' || spec.type === 'float' ? 'any' : undefined,
      min: spec.min, max: spec.max, required: numeric(spec), readOnly: !!spec.readonly,
      value: value == null ? '' : String(value),
      onChange: function (event) { setValue(key, event.target.value) },
    }))
  }
  async function save(event) {
    event.preventDefault()
    if (busy || !schema) return
    setBusy(true); setNotice(null)
    try {
      const payload = {}
      Object.keys(schema).forEach(function (group) {
        Object.keys(schema[group].items || {}).forEach(function (name) {
          const key = group + '.' + name, spec = schema[group].items[name]
          if (spec.readonly) return
          const value = valueFor(key, spec)
          if (numeric(spec)) {
            if (value === '' || !Number.isFinite(Number(value))) throw new Error((spec.description || key) + '需要有效数值')
            payload[key] = Number(value)
          } else if (spec.type === 'bool' || spec.type === 'boolean') payload[key] = value === true || value === 1 || value === 'true'
          else if (value !== undefined) payload[key] = value
        })
      })
      await api('/config', { method: 'POST', body: payload })
      setNotice({ text: '配置已保存', success: true })
    } catch (error) { setNotice({ text: '保存失败：' + message(error), error: true }) }
    finally { setBusy(false) }
  }
  return h('details', { className: 'dsh-lit-pcard' },
    h('summary', null, 'literature 文献库配置'),
    h('div', { className: 'dsh-lit-pcard-body' },
      h(Notice, { text: resource.error, error: true, retry: resource.reload }),
      resource.loading ? h(Empty, null, '加载配置…') : null,
      schema ? h('form', { onSubmit: save },
        Object.keys(schema).map(function (group) {
          const spec = schema[group]
          return h('fieldset', { key: group, className: 'dsh-lit-cfg-group' },
            h('legend', null, spec.description || group),
            Object.keys(spec.items || {}).map(function (name) {
              const key = group + '.' + name, item = spec.items[name]
              return h('div', { key: key, className: 'dsh-lit-cfg-item' },
                h('label', { className: 'dsh-lit-cfg-label', htmlFor: formId + key }, (item.description || name) + (item.readonly ? '（只读）' : '')),
                field(key, item))
            }))
        }),
        h('div', { className: 'dsh-lit-cfg-footer' },
          h(Notice, Object.assign({}, notice)),
          h(Button, { type: 'submit', icon: 'save', className: 'dsh-lit-btn-primary', disabled: busy }, busy ? '保存中…' : '保存配置'))) : null))
}

function apply(ctx) {
  const slots = ctx.get('slots')
  if (!slots) return
  const sessionService = ctx.get('sessions')
  const workspaceService = ctx.get('workspaces')
  if (sessionService) shellServices.sessions = sessionService
  if (workspaceService) shellServices.workspaces = workspaceService
  let style = document.head.querySelector('style[data-plugin="dsh-literature"]')
  if (!style) {
    style = document.createElement('style')
    style.dataset.plugin = 'dsh-literature'
    document.head.appendChild(style)
  }
  style.textContent = LIT_CSS

  // conversation.view must use the two-argument inject contract.
  slots.inject('conversation.view', function () {
    return slots.register(
      { name: 'conversation.view', id: 'literature', order: 60, label: '📚 literature' },
      function (props) { return h(LiteraturePanel, props) },
    )
  })
  slots.inject('settings.plugin.item', function* () {
    yield slots.register(
      { name: 'settings.plugin.item', id: 'literature', key: 'literature', order: 60, label: 'literature 文献库' },
      function () { return h(ConfigView, {}) },
    )
  })
}

return { name, apply }
  }
})
