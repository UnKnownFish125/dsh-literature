__ModuleLoader__.load({
  id: 'dsh-literature',
  factory: (require) => {
/**
 * dsh-literature 浏览器端插件 —— 文献 · 证据 · 知识三合一 UI（conversation 面板 tab）。
 *
 * conversation.view 面板含四个子视图：
 *   1. 📄 文档视窗：文献列表（标题/作者/年份/标签/阅读状态）+ 检索 + 含归档；
 *      点击文献进入详情视窗：元数据 + 附件（上传/直链）+ 关联证据列表（增删）。
 *   2. 🧠 知识视窗：知识点列表（concept/summary/library/archived），可选知识库过滤
 *      （bias/core/eco/project/runtime + 全部）、可切「含归档」；
 *      点知识点进入独立详情：concept/summary/notes/library/source_memory_id/
 *      关联证据（evidence_source 反查 claim）/ 关联 relations。
 *   3. 🕸 知识图谱视窗：SVG 力导向布局渲染知识概念网络（节点按 library 着色，
 *      上方可下拉选择知识库过滤）；拖拽/缩放/平移，点节点看条目并可跳详情。
 *   4. 📊 状况窗口：deepmemory 记忆库目录（/kb/browse）+ 本库知识量（/knowledge-count
 *      + 分库浏览）+ 图谱节点数（/graph）+ 配置摘要（/config）。
 * 全部请求经同源代理 /lit-api/v1/literature → literature server（6260 单服务）。
 */
const React = require('react')
const h = React.createElement

const name = 'dsh-literature'
const inject = ['settings']

const API = '/lit-api/v1/literature'
// 与 literature server upstream 默认 workspace 对齐；会话上下文带 workspace 时优先用它
const DEFAULT_WORKSPACE = 'deepseek-harness'

// ── 知识库（library）常量 ─────────────────────────────────────────
const LIBRARIES = ['bias', 'core', 'eco', 'project', 'runtime']
const LIB_LABEL = { bias: 'bias 约束', core: 'core 核心', eco: 'eco 生态', project: 'project 项目', runtime: 'runtime 运行' }
const LIB_COLOR = {
  bias: '#f59e0b', core: '#60a5fa', eco: '#34d399',
  project: '#a78bfa', runtime: '#fb7185', unknown: '#9ca3af',
}
const READ_STATUS = { unread: '未读', reading: '在读', intensive: '精读', read: '已读' }
const DOC_TYPE = { paper: '论文', book: '书籍', report: '报告', web: '网页' }
const STANCE = { supporting: '支持', contradicting: '反驳', contextual: '中性' }
const STANCE_CLASS = { supporting: 'dsh-lit-stance-sup', contradicting: 'dsh-lit-stance-con', contextual: 'dsh-lit-stance-ctx' }

// ── 基础工具 ───────────────────────────────────────────────────────
function qs(params) {
  const parts = []
  Object.keys(params || {}).forEach(function (key) {
    const v = params[key]
    if (v === undefined || v === null || v === '') return
    parts.push(encodeURIComponent(key) + '=' + encodeURIComponent(String(v)))
  })
  return parts.length ? '?' + parts.join('&') : ''
}

/** JSON 接口调用：非 2xx 抛 Error（附 server error 文案）。raw=true 时直接发 body（如 FormData）。 */
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

function fmtTime(ts) {
  if (ts === undefined || ts === null || ts === '') return '—'
  const d = new Date(Number(ts) * 1000)
  if (Number.isNaN(d.getTime())) return String(ts)
  return d.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function short(v, n) {
  const s = String(v === undefined || v === null ? '' : v)
  return s.length > n ? s.slice(0, n) + '…' : s
}

function clipLabel(s, n) {
  const t = String(s === undefined || s === null ? '' : s).trim()
  return t.length > n ? t.slice(0, n - 1) + '…' : t
}

function libraryColor(lib) { return LIB_COLOR[lib] || LIB_COLOR.unknown }

function isArchived(item) { return !!item && (item.archived === 1 || item.archived === true || String(item.archived) === 'true') }

/** 会话上下文 → workspace_id；取不到则回落服务端默认 workspace。 */
function resolveWorkspaceId(props) {
  const sid = props && props.sessionId ? String(props.sessionId) : ''
  const workspaces = typeof props.useWorkspaces === 'function'
    ? props.useWorkspaces(function (s) { return (s && s.items) || [] })
    : []
  const current = workspaces.find(function (w) { return ((w.sessionIds || []).indexOf(sid) >= 0) }) || null
  return current ? String(current.workspaceId) : DEFAULT_WORKSPACE
}

/** 渲染用：库名 → 彩色标签 chips。 */
function libraryChip(lib, extra) {
  const key = lib || 'unknown'
  const col = libraryColor(lib)
  return h('span', Object.assign({ key: (extra ? extra + '-' : 'lib-') + key, className: 'dsh-lit-tag' },
    { style: { color: col, borderColor: col + '66', background: col + '1f' } }),
    (lib && LIB_LABEL[lib]) ? LIB_LABEL[lib] : String(lib || 'unknown'))
}

function stanceChip(stance, key) {
  const st = STANCE[stance] ? stance : 'contextual'
  const label = STANCE[stance] ? STANCE[stance] : String(stance || STANCE.contextual)
  return h('span', { key: key || ('stance-' + st), className: 'dsh-lit-tag ' + (STANCE_CLASS[st] || STANCE_CLASS.contextual) }, label)
}

// ── 面板样式（沿用 DSH 主题 CSS 变量，缺省回退同 deepmemory）─────
const LIT_CSS = `
.dsh-lit-panel { display:flex; flex-direction:column; gap:10px; padding:14px 16px 24px; font-size:13px; line-height:1.55; color:var(--dsw-alias-label-primary, inherit); min-width:0; }
.dsh-lit-topbar { display:flex; align-items:center; gap:10px; flex-wrap:wrap; padding-bottom:10px; border-bottom:1px solid var(--dsw-alias-border-l1, rgba(128,128,128,.2)); }
.dsh-lit-brand { font-size:14px; font-weight:600; display:inline-flex; align-items:center; gap:6px; white-space:nowrap; }
.dsh-lit-ws { font-size:11px; opacity:.55; font-family:ui-monospace, SFMono-Regular, Menlo, monospace; max-width:220px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.dsh-lit-tabs { display:inline-flex; gap:2px; margin-left:auto; border:1px solid var(--dsw-alias-border-l2, rgba(128,128,128,.4)); border-radius:8px; padding:2px; flex-wrap:wrap; }
.dsh-lit-tab { appearance:none; background:transparent; border:0; color:var(--dsw-alias-label-secondary, rgba(128,128,128,.8)); font:inherit; font-size:12px; padding:4px 12px; border-radius:6px; cursor:pointer; white-space:nowrap; }
.dsh-lit-tab:hover { background:var(--dsw-alias-bg-layer-2, rgba(128,128,128,.16)); }
.dsh-lit-tab-on { background:var(--dsw-alias-bg-layer-3, rgba(128,128,128,.24)); color:var(--dsw-alias-label-primary, inherit); font-weight:600; }
.dsh-lit-toolbar { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
.dsh-lit-input { flex:1; min-width:120px; background:var(--dsw-alias-bg-layer-1, transparent); border:1px solid var(--dsw-alias-border-l2, rgba(128,128,128,.4)); border-radius:6px; padding:6px 9px; color:var(--dsw-alias-label-primary, inherit); font:inherit; }
.dsh-lit-input:focus { outline:1px solid var(--dsw-alias-brand-primary, #4c8dff); }
.dsh-lit-select { background:var(--dsw-alias-bg-layer-1, transparent); border:1px solid var(--dsw-alias-border-l2, rgba(128,128,128,.4)); border-radius:6px; padding:5px 8px; color:var(--dsw-alias-label-primary, inherit); font:inherit; }
.dsh-lit-select option { background:var(--dsw-alias-bg-overlay, #1e1e1e); color:var(--dsw-alias-label-primary, #e8e8e8); }
.dsh-lit-btn { border:1px solid var(--dsw-alias-border-l2, rgba(128,128,128,.45)); background:var(--dsw-alias-bg-layer-1, transparent); color:var(--dsw-alias-label-primary, inherit); border-radius:6px; padding:5px 12px; cursor:pointer; font:inherit; white-space:nowrap; }
.dsh-lit-btn:hover { background:var(--dsw-alias-bg-layer-2, rgba(128,128,128,.18)); }
.dsh-lit-btn-primary { border-color:var(--dsw-alias-brand-primary, #4c8dff); color:var(--dsw-alias-brand-primary, #4c8dff); }
.dsh-lit-btn-danger { border-color:#d34848; color:#f87171; }
.dsh-lit-btn-danger:hover { background:rgba(211,72,72,.14); }
.dsh-lit-btn-mini { padding:2px 8px; font-size:12px; border-radius:5px; }
.dsh-lit-btn:disabled { opacity:.45; cursor:default; }
.dsh-lit-link { color:var(--dsw-alias-brand-primary, #4c8dff); cursor:pointer; text-decoration:none; }
.dsh-lit-link:hover { text-decoration:underline; }
.dsh-lit-muted { opacity:.55; font-size:11px; }
.dsh-lit-meta { opacity:.62; font-size:12px; display:flex; gap:6px; align-items:center; flex-wrap:wrap; }
.dsh-lit-count { opacity:.55; font-size:11px; white-space:nowrap; }
.dsh-lit-card { border:1px solid var(--dsw-alias-border-l1, rgba(128,128,128,.3)); border-radius:10px; padding:10px 12px; background:var(--dsw-alias-bg-layer-1, rgba(128,128,128,.05)); }
.dsh-lit-sect-h { display:flex; align-items:center; gap:8px; font-size:11px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; opacity:.7; margin:14px 0 8px; }
.dsh-lit-list { display:flex; flex-direction:column; gap:8px; }
.dsh-lit-scroll { max-height:min(44vh, 460px); overflow:auto; display:flex; flex-direction:column; gap:8px; padding:2px 3px 4px 0; scrollbar-width:thin; }
.dsh-lit-item { display:block; width:100%; text-align:left; padding:9px 12px; border:1px solid var(--dsw-alias-border-l1, rgba(128,128,128,.3)); border-radius:9px; cursor:pointer; background:transparent; color:var(--dsw-alias-label-primary, inherit); font:inherit; transition:border-color .15s, background .15s; }
.dsh-lit-item:hover { border-color:var(--dsw-alias-label-dimmed, rgba(128,128,128,.6)); background:var(--dsw-alias-bg-layer-2, rgba(128,128,128,.12)); }
.dsh-lit-item-title { font-weight:600; font-size:13px; display:flex; gap:6px; align-items:flex-start; flex-wrap:wrap; }
.dsh-lit-item-title .dsh-lit-tt { flex:1; min-width:0; word-break:break-word; }
.dsh-lit-summary { color:var(--dsw-alias-label-secondary, rgba(128,128,128,.85)); font-size:12px; margin-top:3px; overflow:hidden; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; word-break:break-word; }
.dsh-lit-tag { display:inline-flex; font-size:11px; line-height:1.7; border-radius:999px; padding:0 9px; border:1px solid rgba(128,128,128,.3); opacity:.95; white-space:nowrap; }
.dsh-lit-arch-badge { border-style:dashed; border-color:#f59e0b88; color:#fbbf24; background:#f59e0b14; }
.dsh-lit-empty { opacity:.5; padding:14px 4px; }
.dsh-lit-err { color:#f87171; font-size:12px; padding:4px 0; }
.dsh-lit-ok { color:#4ade80; font-size:12px; padding:4px 0; }
.dsh-lit-kv { display:grid; grid-template-columns:max-content minmax(0,1fr); gap:4px 16px; }
.dsh-lit-kv > .dsh-lit-k { opacity:.6; white-space:nowrap; }
.dsh-lit-kv > .dsh-lit-v { min-width:0; word-break:break-word; }
.dsh-lit-pre { margin:6px 0 0; padding:8px 10px; background:var(--dsw-alias-bg-layer-1, rgba(128,128,128,.08)); border:1px solid var(--dsw-alias-border-l1, rgba(128,128,128,.2)); border-radius:6px; font-size:12px; line-height:1.6; white-space:pre-wrap; word-break:break-word; max-height:260px; overflow:auto; font-family:ui-monospace, SFMono-Regular, Menlo, monospace; }
.dsh-lit-ev { border:1px solid var(--dsw-alias-border-l1, rgba(128,128,128,.24)); border-radius:9px; padding:8px 10px; display:flex; flex-direction:column; gap:4px; }
.dsh-lit-ev-head { display:flex; align-items:flex-start; gap:8px; }
.dsh-lit-ev-claim { flex:1; font-weight:600; font-size:13px; word-break:break-word; }
.dsh-lit-ev-text { opacity:.8; font-size:12px; line-height:1.5; word-break:break-word; }
.dsh-lit-ev-foot { display:flex; gap:6px; align-items:center; flex-wrap:wrap; }
.dsh-lit-stance-sup { color:#34d399; border-color:#34d39966; background:#34d3991a; }
.dsh-lit-stance-con { color:#f87171; border-color:#f8717166; background:#f871711a; }
.dsh-lit-stance-ctx { color:#94a3b8; border-color:#94a3b866; background:#94a3b81a; }
.dsh-lit-field { display:flex; flex-direction:column; gap:3px; }
.dsh-lit-field label { font-size:11px; opacity:.65; }
.dsh-lit-form { display:flex; gap:8px; flex-wrap:wrap; align-items:flex-start; }
.dsh-lit-stats { display:grid; grid-template-columns:repeat(auto-fit, minmax(230px, 1fr)); gap:10px; }
.dsh-lit-stat { border:1px solid var(--dsw-alias-border-l1, rgba(128,128,128,.3)); border-radius:10px; padding:12px 14px; display:flex; flex-direction:column; gap:6px; background:var(--dsw-alias-bg-layer-1, rgba(128,128,128,.05)); }
.dsh-lit-stat .dsh-lit-stat-label { font-size:11px; opacity:.65; letter-spacing:.04em; }
.dsh-lit-stat .dsh-lit-stat-big { font-size:26px; font-weight:700; line-height:1.15; }
.dsh-lit-stat .dsh-lit-stat-sub { font-size:11px; opacity:.75; line-height:1.7; }
.dsh-lit-graphbox { display:flex; gap:12px; align-items:stretch; }
.dsh-lit-svg-wrap { flex:1; min-width:0; }
.dsh-lit-svg { width:100%; aspect-ratio:1000 / 620; height:auto; display:block; border-radius:10px; background:var(--dsw-alias-bg-layer-1, rgba(128,128,128,.06)); touch-action:none; cursor:grab; }
.dsh-lit-svg.dsh-lit-dragging { cursor:grabbing; }
.dsh-lit-gnode { cursor:pointer; transition:opacity .12s; }
.dsh-lit-gedge { stroke:var(--dsw-alias-border-l2, rgba(128,128,128,.55)); }
.dsh-lit-glabel { fill:var(--dsw-alias-label-primary, #e8e8e8); font-size:13px; paint-order:stroke; stroke:var(--dsw-alias-bg-layer-1, #0e1114); stroke-width:4px; stroke-linejoin:round; pointer-events:none; }
.dsh-lit-legend { display:flex; gap:10px; flex-wrap:wrap; font-size:11px; opacity:.8; align-items:center; margin-top:8px; }
.dsh-lit-key { display:inline-flex; align-items:center; gap:5px; white-space:nowrap; }
.dsh-lit-dot { width:9px; height:9px; border-radius:50%; display:inline-block; }
.dsh-lit-side { width:250px; flex:none; display:flex; flex-direction:column; gap:8px; }
.dsh-lit-hint { opacity:.55; font-size:11px; }
.dsh-lit-hr { border:none; border-top:1px solid var(--dsw-alias-border-l1, rgba(128,128,128,.18)); margin:10px 0 0; }
.dsh-lit-abs { position:relative; }
.dsh-lit-loading { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; gap:8px; background:var(--dsw-alias-bg-layer-1, rgba(0,0,0,.25)); border-radius:10px; font-size:12px; z-index:2; }
details.dsh-lit-details summary { cursor:pointer; opacity:.8; }
@media (max-width:760px) { .dsh-lit-side { width:100%; } .dsh-lit-graphbox { flex-direction:column; } }
`

// ── 图谱布局：圆心螺旋初始化 + 斥力/弹簧迭代 + 碰撞消除 ──────────
function buildGraphLayout(nodes, edges, width, height, seed) {
  const out = {}
  const n = nodes.length
  if (!n) return out
  const byId = {}
  const deg = {}
  edges.forEach(function (edge) {
    deg[String(edge.source)] = (deg[String(edge.source)] || 0) + 1
    deg[String(edge.target)] = (deg[String(edge.target)] || 0) + 1
  })
  const cx = width / 2
  const cy = height / 2
  const sd = seed || 0
  nodes.forEach(function (node, index) {
    const id = String(node.id)
    const golden = (index + sd * 0.618) * 2.399963229728653
    const spread = Math.min(width, height) * 0.46 * Math.sqrt((index + 1) / Math.max(1, n))
    const item = {
      id: id,
      x: cx + Math.cos(golden) * spread,
      y: cy + Math.sin(golden) * spread,
      vx: 0, vy: 0,
      r: 9 + Math.min(13, Math.sqrt(deg[id] || 0) * 2.2),
    }
    out[id] = item
    byId[id] = item
  })
  if (n === 1) { const it = out[String(nodes[0].id)]; it.x = cx; it.y = cy }
  const iterations = n > 240 ? 70 : n > 120 ? 95 : 130
  for (let tick = 0; tick < iterations; tick += 1) {
    const cooling = 1 - tick / iterations
    const ids = Object.keys(byId)
    for (let i = 0; i < ids.length; i += 1) {
      const a = byId[ids[i]]
      for (let j = i + 1; j < ids.length; j += 1) {
        const b = byId[ids[j]]
        let dx = b.x - a.x, dy = b.y - a.y
        let d2 = dx * dx + dy * dy
        if (d2 < 1) { dx = ((i + 1) * 17) % 13 - 6; dy = ((j + 1) * 19) % 13 - 6; d2 = dx * dx + dy * dy || 1 }
        const dist = Math.sqrt(d2)
        const min = a.r + b.r + 26
        const rep = Math.min(3.6, 5200 / d2) + (dist < min ? (min - dist) * 0.06 : 0)
        const fx = dx / dist * rep, fy = dy / dist * rep
        a.vx -= fx; a.vy -= fy; b.vx += fx; b.vy += fy
      }
    }
    edges.forEach(function (edge) {
      const a = byId[String(edge.source)], b = byId[String(edge.target)]
      if (!a || !b) return
      const dx = b.x - a.x, dy = b.y - a.y
      const dist = Math.sqrt(dx * dx + dy * dy) || 1
      const target = 150 + (a.r + b.r) * 0.6
      const pull = (dist - target) * 0.012
      const fx = dx / dist * pull, fy = dy / dist * pull
      a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy
    })
    ids.forEach(function (id) {
      const it = byId[id]
      it.vx += (cx - it.x) * 0.00024
      it.vy += (cy - it.y) * 0.00024
      it.vx *= 0.7; it.vy *= 0.7
      it.x += it.vx * (0.6 + cooling * 0.7)
      it.y += it.vy * (0.6 + cooling * 0.7)
      const m = it.r + 26
      it.x = Math.max(m, Math.min(width - m, it.x))
      it.y = Math.max(m, Math.min(height - m, it.y))
    })
  }
  for (let pass = 0; pass < 18; pass += 1) {
    const ids = Object.keys(byId)
    for (let i = 0; i < ids.length; i += 1) {
      const a = byId[ids[i]]
      for (let j = i + 1; j < ids.length; j += 1) {
        const b = byId[ids[j]]
        let dx = b.x - a.x, dy = b.y - a.y
        let dist = Math.sqrt(dx * dx + dy * dy)
        if (dist < 0.01) { dx = ((i + 7) * 11) % 9 - 4; dy = ((j + 3) * 13) % 9 - 4; dist = Math.sqrt(dx * dx + dy * dy) || 1 }
        const min = a.r + b.r + 22
        if (dist >= min) continue
        const shift = (min - dist) * 0.5
        const sx = dx / dist * shift, sy = dy / dist * shift
        a.x -= sx; a.y -= sy; b.x += sx; b.y += sy
      }
    }
  }
  return out
}

// ══════════════════════════════════════════════════════════════════
// 1) 文档视窗（文献列表 / 检索 / 详情）
// ══════════════════════════════════════════════════════════════════
function EvidenceRow(props) {
  const ev = props.ev
  const onDelete = props.onDelete
  const row = h('div', { className: 'dsh-lit-ev', key: props.key != null ? props.key : String(ev.id) },
    h('div', { className: 'dsh-lit-ev-head' },
      stanceChip(ev.stance, 'stance'),
      h('div', { className: 'dsh-lit-ev-claim' }, String(ev.claim || '')),
      onDelete ? h('button', {
        className: 'dsh-lit-btn dsh-lit-btn-mini dsh-lit-btn-danger', title: '删除该证据',
        onClick: function (e) { e.stopPropagation(); onDelete(ev) },
      }, '✕') : null,
    ),
    ev.evidence_text
      ? h('div', { className: 'dsh-lit-ev-text' }, String(ev.evidence_text))
      : null,
    h('div', { className: 'dsh-lit-ev-foot' },
      ev.chapter_anchor ? h('span', { className: 'dsh-lit-meta' }, '章节: ' + ev.chapter_anchor) : null,
      ev.page ? h('span', { className: 'dsh-lit-meta' }, '页码: ' + ev.page) : null,
      ev.confidence != null ? h('span', { className: 'dsh-lit-meta' }, '置信度: ' + Math.round(Number(ev.confidence) * 100) + '%') : null,
      ev.note ? h('span', { className: 'dsh-lit-meta' }, '备注: ' + short(ev.note, 60)) : null,
      h('span', { className: 'dsh-lit-muted' }, '#' + ev.id + (ev.updated_at ? ' · ' + fmtTime(ev.updated_at) : '')),
    ),
  )
  return row
}

/** 文档详情视窗：元数据 + 附件 + 关联证据。 */
function DocDetail(props) {
  const { docId, workspaceId, onBack, onDeleted } = props
  const [data, setData] = React.useState(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState('')
  const [msg, setMsg] = React.useState('')
  // 新增证据表单
  const [evClaim, setEvClaim] = React.useState('')
  const [evStance, setEvStance] = React.useState('supporting')
  const [evText, setEvText] = React.useState('')
  const [evBusy, setEvBusy] = React.useState(false)
  // 附件上传
  const [uploading, setUploading] = React.useState(false)
  const fileRef = React.useRef(null)

  async function load() {
    setLoading(true); setError('')
    try {
      const res = await api('/documents/' + encodeURIComponent(String(docId)))
      setData((res && res.document) || null)
    } catch (e) { setError(String((e && e.message) || e)) }
    finally { setLoading(false) }
  }
  React.useEffect(function () { load() }, [docId])

  async function addEvidence() {
    const claim = evClaim.trim()
    if (!claim) { setMsg('请填写主张（claim）'); return }
    setEvBusy(true); setMsg('')
    try {
      await api('/evidence', { method: 'POST', body: { claim: claim, stance: evStance, evidence_text: evText.trim(), doc_id: Number(docId), workspace_id: workspaceId } })
      setEvClaim(''); setEvText('')
      setMsg('证据已添加')
      await load()
    } catch (e) { setMsg('添加失败: ' + String((e && e.message) || e)) }
    finally { setEvBusy(false) }
  }

  async function removeEvidence(ev) {
    if (!window.confirm('删除该证据（软删，可恢复）？\n' + short(ev.claim, 90))) return
    try { await api('/evidence/' + String(ev.id), { method: 'DELETE' }); await load() }
    catch (e) { setMsg('删除失败: ' + String((e && e.message) || e)) }
  }

  async function onFile(e) {
    const file = e.target.files && e.target.files[0]
    if (!file) return
    setUploading(true); setMsg('')
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('workspace_id', workspaceId)
      const up = await api('/attachments', { method: 'POST', body: fd, raw: true })
      if (!up || !up.attachment_path) throw new Error('上传响应缺少 attachment_path')
      await api('/documents/' + String(docId), { method: 'PATCH', body: { attachment_path: up.attachment_path, attachment_sha256: up.attachment_sha256 } })
      setMsg('附件已上传并关联（' + up.attachment_path + (up.size ? ' · ' + Math.round(up.size / 1024) + ' KB' : '') + '）')
      await load()
    } catch (err) { setMsg('附件上传失败: ' + String((err && err.message) || err)) }
    finally { setUploading(false); if (fileRef.current) fileRef.current.value = '' }
  }

  async function openAttachment() {
    setMsg('')
    try {
      const res = await api('/documents/' + String(docId) + '/attachment-url')
      const url = res && (res.url || res.attachment_url)
      if (url) window.open(url, '_blank')
      else setMsg('服务端未返回附件直链')
    } catch (e) {
      setMsg('附件直链不可用（' + String((e && e.message) || e) + '）——本服务未开放附件签名直链，仅展示元数据')
    }
  }

  async function toggleArchive() {
    const next = data.lifecycle_status === 'archived' ? 'active' : 'archived'
    try {
      await api('/documents/' + String(docId), { method: 'PATCH', body: { lifecycle_status: next } })
      setMsg(next === 'archived' ? '已归档（列表含归档可见）' : '已恢复为活动')
      await load()
    } catch (e) { setMsg('操作失败: ' + String((e && e.message) || e)) }
  }

  async function changeRead(v) {
    try { await api('/documents/' + String(docId), { method: 'PATCH', body: { read_status: v } }); await load() }
    catch (e) { setMsg('更新失败: ' + String((e && e.message) || e)) }
  }

  async function delDoc() {
    if (!window.confirm('彻底软删该文献？删除后将从列表消失。')) return
    try { await api('/documents/' + String(docId), { method: 'DELETE' }); if (onDeleted) onDeleted(); }
    catch (e) { setMsg('删除失败: ' + String((e && e.message) || e)) }
  }

  if (loading && !data) return h('div', null, '加载文献详情…')
  if (error && !data) return h('div', { className: 'dsh-lit-err' }, error)
  if (!data) return null
  const doc = data

  const metaRows = []
  const metaKv = function (k, v) {
    metaRows.push(h('span', { key: k + '-k', className: 'dsh-lit-k' }, k))
    metaRows.push(h('span', { key: k + '-v', className: 'dsh-lit-v' }, v == null || v === '' ? '—' : v))
  }
  metaKv('类型', DOC_TYPE[doc.type] || String(doc.type || '—'))
  metaKv('作者', Array.isArray(doc.authors) && doc.authors.length ? doc.authors.join('、') : '—')
  metaKv('年份', doc.year != null ? String(doc.year) : '—')
  metaKv('期刊/出处', doc.journal || '—')
  metaKv('DOI', doc.doi
    ? h('a', { key: 'doi', className: 'dsh-lit-link', href: 'https://doi.org/' + encodeURIComponent(doc.doi), target: '_blank', rel: 'noreferrer' }, doc.doi)
    : '—')
  metaKv('ISBN', doc.isbn || '—')
  metaKv('URL', doc.url ? h('a', { key: 'url', className: 'dsh-lit-link', href: doc.url, target: '_blank', rel: 'noreferrer' }, short(doc.url, 60)) : '—')
  metaKv('阅读状态', h('select', {
    key: 'rs', className: 'dsh-lit-select', value: doc.read_status || 'unread',
    onChange: function (e) { changeRead(e.target.value) },
  }, Object.keys(READ_STATUS).map(function (k) {
    return h('option', { key: k, value: k }, READ_STATUS[k] + ' (' + k + ')')
  })))
  metaKv('生命周期', doc.lifecycle_status === 'archived' ? '已归档' : '活动')
  metaKv('创建时间', fmtTime(doc.created_at))
  metaKv('更新时间', fmtTime(doc.updated_at))
  metaKv('工作区', doc.workspace_id || '—')

  const evidences = Array.isArray(doc.evidence) ? doc.evidence : []
  const attachments = h('div', { className: 'dsh-lit-card', key: 'att' },
    h('div', { className: 'dsh-lit-toolbar' },
      h('span', { className: 'dsh-lit-meta', style: { flex: 1, fontWeight: 600 } }, '附件'),
      !doc.attachment_path ? h('span', { className: 'dsh-lit-muted' }, '（无附件）') : null,
      h('input', { ref: fileRef, type: 'file', style: { display: 'none' }, onChange: onFile }),
      h('button', { className: 'dsh-lit-btn dsh-lit-btn-mini', disabled: uploading, onClick: function () { if (fileRef.current) fileRef.current.click() } }, uploading ? '上传中…' : '上传附件'),
      doc.attachment_path ? h('button', { className: 'dsh-lit-btn dsh-lit-btn-mini', onClick: openAttachment }, '打开') : null,
    ),
    doc.attachment_path ? h('div', { className: 'dsh-lit-kv', style: { marginTop: 8 } }, [
      h('span', { key: 'p1', className: 'dsh-lit-k' }, '路径'),
      h('span', { key: 'p2', className: 'dsh-lit-v' }, short(doc.attachment_path, 80)),
      h('span', { key: 'h1', className: 'dsh-lit-k' }, 'SHA256'),
      h('span', { key: 'h2', className: 'dsh-lit-v', style: { fontFamily: 'monospace' } }, short(doc.attachment_sha256 || '—', 40)),
    ]) : null,
  )

  const evidenceBox = h('div', { className: 'dsh-lit-card', key: 'evs' },
    h('div', { className: 'dsh-lit-toolbar', style: { marginBottom: 6 } },
      h('span', { className: 'dsh-lit-meta', style: { flex: 1, fontWeight: 600 } }, '关联证据 · ' + evidences.length + ' 条'),
      h('span', { className: 'dsh-lit-muted' }, '点击 ✕ 软删'),
    ),
    evidences.length
      ? h('div', { className: 'dsh-lit-list' }, evidences.map(function (ev) {
        return h(EvidenceRow, { key: 'ev' + ev.id, ev: ev, onDelete: removeEvidence })
      }))
      : h('div', { className: 'dsh-lit-empty' }, '（该文献下暂无证据）'),
    h('div', { className: 'dsh-lit-sect-h' }, '新增证据'),
    h('div', { className: 'dsh-lit-form' },
      h('div', { className: 'dsh-lit-field', style: { flex: '1 1 260px' } },
        h('label', null, '主张 claim *'),
        h('input', { className: 'dsh-lit-input', value: evClaim, placeholder: '一句话主张（如：该论文支持提示缓存可降低 41–80% 成本）', onChange: function (e) { setEvClaim(e.target.value) } }),
      ),
      h('div', { className: 'dsh-lit-field' },
        h('label', null, '立场'),
        h('select', { className: 'dsh-lit-select', value: evStance, onChange: function (e) { setEvStance(e.target.value) } },
          Object.keys(STANCE).map(function (k) { return h('option', { key: k, value: k }, STANCE[k]) })),
      ),
      h('div', { className: 'dsh-lit-field', style: { flex: '1 1 100%' } },
        h('label', null, '原文摘录 evidence_text（可空）'),
        h('textarea', { className: 'dsh-lit-input', style: { minHeight: 52, resize: 'vertical' }, value: evText, placeholder: '带章节/页码定位的原文摘录…', onChange: function (e) { setEvText(e.target.value) } }),
      ),
      h('button', { className: 'dsh-lit-btn dsh-lit-btn-primary', disabled: evBusy, onClick: addEvidence }, evBusy ? '添加中…' : '添加证据'),
    ),
  )

  const fullText = doc.full_text
    ? h('details', { key: 'ft', className: 'dsh-lit-details dsh-lit-card' },
      h('summary', null, '摘要/全文（' + doc.full_text.length + ' 字符）'),
      h('div', { className: 'dsh-lit-pre' }, String(doc.full_text)),
    )
    : null

  return h('div', null, [
    h('div', { key: 'nav', className: 'dsh-lit-toolbar' },
      h('button', { className: 'dsh-lit-btn dsh-lit-btn-mini', onClick: onBack }, '← 返回文档列表'),
      h('span', { className: 'dsh-lit-muted' }, '文献 #' + doc.id),
      msg ? h('span', { key: 'msg', className: msg.indexOf('失败') >= 0 || msg.indexOf('不可用') >= 0 ? 'dsh-lit-err' : 'dsh-lit-ok', style: { flex: 1 } }, msg) : h('span', { style: { flex: 1 } }),
      h('button', { key: 'arc', className: 'dsh-lit-btn dsh-lit-btn-mini', onClick: toggleArchive }, doc.lifecycle_status === 'archived' ? '恢复为活动' : '归档'),
      h('button', { key: 'del', className: 'dsh-lit-btn dsh-lit-btn-mini dsh-lit-btn-danger', onClick: delDoc }, '删除'),
    ),
    h('div', { key: 't', className: 'dsh-lit-item-title', style: { fontSize: 15, marginTop: 6 } },
      h('span', { className: 'dsh-lit-tt' }, doc.title || '(无题录)'),
      doc.lifecycle_status === 'archived' ? h('span', { key: 'a', className: 'dsh-lit-tag dsh-lit-arch-badge' }, '已归档') : null,
    ),
    h('div', { key: 'tags', className: 'dsh-lit-meta', style: { marginTop: 4 } },
      (Array.isArray(doc.tags) ? doc.tags : []).map(function (t, i) { return h('span', { key: 'tg' + i, className: 'dsh-lit-tag' }, String(t)) }),
      (doc.authors && doc.authors.length) ? h('span', { className: 'dsh-lit-muted' }, (doc.authors || []).length + ' 位作者') : null,
    ),
    h('div', { key: 'meta', className: 'dsh-lit-card', style: { marginTop: 10 } },
      h('div', { className: 'dsh-lit-kv' }, metaRows),
    ),
    h('div', { key: 'attsec', style: { marginTop: 10 } }, attachments),
    h('div', { key: 'evsec', style: { marginTop: 10 } }, evidenceBox),
    fullText ? h('div', { key: 'ftsec', style: { marginTop: 10 } }, fullText) : null,
  ])
}

function DocumentsView(props) {
  const workspaceId = props.workspaceId
  const [docs, setDocs] = React.useState([])
  const [query, setQuery] = React.useState('')
  const [input, setInput] = React.useState('')
  const [includeArchived, setIncludeArchived] = React.useState(false)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState('')
  const [openId, setOpenId] = React.useState(null)

  async function load() {
    setLoading(true); setError('')
    try {
      const res = await api('/documents' + qs({ workspace_id: workspaceId, q: query || '', include_archived: includeArchived || '' }))
      setDocs((res && res.documents) || [])
    } catch (e) { setError(String((e && e.message) || e)) }
    finally { setLoading(false) }
  }
  React.useEffect(function () { load() }, [query, includeArchived])

  function doSearch() { setQuery(input.trim()) }
  function backFromDetail() { setOpenId(null); load() }

  if (openId != null) {
    return h(DocDetail, { docId: openId, workspaceId: workspaceId, onBack: backFromDetail, onDeleted: backFromDetail })
  }

  return h('div', null, [
    h('div', { key: 'toolbar', className: 'dsh-lit-toolbar' },
      h('input', { key: 'q', className: 'dsh-lit-input', style: { maxWidth: 320 }, value: input, placeholder: '检索标题 / 作者 / 期刊 / 标签…', onChange: function (e) { setInput(e.target.value) }, onKeyDown: function (e) { if (e.key === 'Enter') doSearch() } }),
      h('button', { key: 's', className: 'dsh-lit-btn', onClick: doSearch }, '检索'),
      h('button', { key: 'r', className: 'dsh-lit-btn', onClick: function () { setInput(query); load() }, disabled: loading }, '刷新'),
      h('label', { key: 'arch', className: 'dsh-lit-meta', style: { cursor: 'pointer', gap: 4 } },
        h('input', { type: 'checkbox', checked: includeArchived, onChange: function (e) { setIncludeArchived(e.target.checked) } }),
        '含归档',
      ),
      h('span', { key: 'c', className: 'dsh-lit-count' }, '共 ' + docs.length + ' 篇'),
      error ? h('span', { key: 'e', className: 'dsh-lit-err' }, error) : null,
    ),
    h('div', { key: 'list', className: 'dsh-lit-list dsh-lit-scroll', style: { marginTop: 8 } },
      docs.length
        ? docs.map(function (d) {
          const tags = Array.isArray(d.tags) ? d.tags : []
          const authors = Array.isArray(d.authors) ? d.authors : []
          const isArch = d.lifecycle_status === 'archived'
          return h('button', { key: String(d.id), className: 'dsh-lit-item', onClick: function () { setOpenId(d.id) } },
            h('div', { className: 'dsh-lit-item-title' },
              h('span', { className: 'dsh-lit-tt' }, d.title || '(无题录)'),
              isArch ? h('span', { key: 'arch', className: 'dsh-lit-tag dsh-lit-arch-badge' }, '归档') : null,
              h('span', { key: 'rs', className: 'dsh-lit-tag' }, READ_STATUS[d.read_status] || d.read_status || '未读'),
            ),
            h('div', { className: 'dsh-lit-meta', style: { marginTop: 3 } },
              h('span', { key: 'au' }, authors.length ? authors.slice(0, 4).join('、') + (authors.length > 4 ? ' 等' : '') : '佚名'),
              d.year ? h('span', { key: 'yr' }, '· ' + d.year) : null,
              d.journal ? h('span', { key: 'jl' }, '· ' + short(d.journal, 40)) : null,
              d.type ? h('span', { key: 'ty', className: 'dsh-lit-tag' }, DOC_TYPE[d.type] || d.type) : null,
            ),
            tags.length ? h('div', { className: 'dsh-lit-meta', style: { marginTop: 4 } },
              tags.slice(0, 6).map(function (t, i) { return h('span', { key: String(i), className: 'dsh-lit-tag' }, String(t)) })) : null,
          )
        })
        : h('div', { className: 'dsh-lit-empty' }, loading ? '加载中…' : '（暂无文献。可通过代理/后台导入，或在此查看已有条目）'),
    ),
  ])
}

// ══════════════════════════════════════════════════════════════════
// 2) 知识视窗（列表 + 可选知识库过滤 + 含归档 + 详情）
// ══════════════════════════════════════════════════════════════════
function KnowledgeDetail(props) {
  const { kid, workspaceId, onBack } = props
  const [data, setData] = React.useState(null)
  const [evs, setEvs] = React.useState(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState('')

  React.useEffect(function () {
    let alive = true
    async function load() {
      setLoading(true); setError(''); setData(null); setEvs(null)
      try {
        const res = await api('/knowledge/' + encodeURIComponent(String(kid)))
        const item = (res && res.knowledge) || null
        if (!alive) return
        setData(item)
        if (item) {
          const ids = Array.isArray(item.sources) ? item.sources : []
          const fetched = await Promise.all(ids.map(function (id) {
            return api('/evidence/' + encodeURIComponent(String(id)))
              .then(function (r) { return { ok: true, evidence: (r && r.evidence) || null } })
              .catch(function () { return { ok: false, id: id } })
          }))
          if (alive) setEvs(fetched.filter(function (f) { return f.ok && f.evidence }))
        }
      } catch (e) {
        if (alive) setError(String((e && e.message) || e))
      } finally {
        if (alive) setLoading(false)
      }
    }
    load()
    return function () { alive = false }
  }, [kid])

  if (loading) return h('div', null, '加载知识条目详情…')
  if (error) return h('div', { className: 'dsh-lit-err' }, error)
  if (!data) return h('div', { className: 'dsh-lit-empty' }, '（条目不存在）')
  const it = data
  const isArch = isArchived(it)
  const rels = Array.isArray(it.relations) ? it.relations : []
  const srcs = Array.isArray(evs) ? evs : []

  const rows = []
  rows.push(h('span', { key: 'k1', className: 'dsh-lit-k' }, '知识库'))
  rows.push(h('span', { key: 'v1', className: 'dsh-lit-v' }, [libraryChip(it.library, 'lib')]))
  rows.push(h('span', { key: 'k2', className: 'dsh-lit-k' }, '归档'))
  rows.push(h('span', { key: 'v2', className: 'dsh-lit-v' }, isArch ? h('span', { key: 'a', className: 'dsh-lit-tag dsh-lit-arch-badge' }, '已归档') : h('span', { key: 'a', className: 'dsh-lit-tag' }, '活动')))
  rows.push(h('span', { key: 'k3', className: 'dsh-lit-k' }, 'source_memory_id'))
  rows.push(h('span', { key: 'v3', className: 'dsh-lit-v' }, it.source_memory_id != null ? String(it.source_memory_id) : '—'))
  rows.push(h('span', { key: 'k4', className: 'dsh-lit-k' }, '条目 ID'))
  rows.push(h('span', { key: 'v4', className: 'dsh-lit-v' }, String(it.id)))
  rows.push(h('span', { key: 'k5', className: 'dsh-lit-k' }, '工作区'))
  rows.push(h('span', { key: 'v5', className: 'dsh-lit-v' }, it.workspace_id || '—'))
  rows.push(h('span', { key: 'k6', className: 'dsh-lit-k' }, '创建时间'))
  rows.push(h('span', { key: 'v6', className: 'dsh-lit-v' }, fmtTime(it.created_at)))
  rows.push(h('span', { key: 'k7', className: 'dsh-lit-k' }, '更新时间'))
  rows.push(h('span', { key: 'v7', className: 'dsh-lit-v' }, fmtTime(it.updated_at)))

  return h('div', null, [
    h('div', { key: 'nav', className: 'dsh-lit-toolbar' },
      h('button', { className: 'dsh-lit-btn dsh-lit-btn-mini', onClick: onBack }, '← 返回知识列表'),
      h('span', { className: 'dsh-lit-muted' }, '知识点 #' + it.id),
    ),
    h('div', { key: 't', className: 'dsh-lit-item-title', style: { fontSize: 16, marginTop: 6 } },
      h('span', { className: 'dsh-lit-tt' }, it.concept || '(无概念名)'),
      isArch ? h('span', { key: 'a', className: 'dsh-lit-tag dsh-lit-arch-badge' }, '已归档') : null,
    ),
    h('div', { key: 'meta', className: 'dsh-lit-card', style: { marginTop: 10 } },
      h('div', { className: 'dsh-lit-kv' }, rows),
    ),
    h('div', { key: 'sum', className: 'dsh-lit-card', style: { marginTop: 10 } },
      h('div', { className: 'dsh-lit-meta', style: { fontWeight: 600, marginBottom: 4 } }, '摘要 summary'),
      it.summary ? h('div', { className: 'dsh-lit-ev-text' }, String(it.summary)) : h('div', { className: 'dsh-lit-empty' }, '（无摘要）'),
      h('div', { className: 'dsh-lit-sect-h', style: { marginBottom: 2 } }, '笔记 notes'),
      it.notes ? h('div', { className: 'dsh-lit-pre' }, String(it.notes)) : h('div', { className: 'dsh-lit-empty' }, '（无笔记）'),
    ),
    h('div', { key: 'rel', className: 'dsh-lit-card', style: { marginTop: 10 } },
      h('div', { className: 'dsh-lit-meta', style: { fontWeight: 600, marginBottom: 4 } }, '关联关系 relations · ' + rels.length),
      rels.length
        ? h('div', { className: 'dsh-lit-list' }, rels.map(function (r, i) {
          const srcIsSelf = String(r.source) === String(it.concept) || String(r.source_id) === String(it.id)
          const dstIsSelf = String(r.target) === String(it.concept) || String(r.target_id) === String(it.id)
          return h('div', { key: 'r' + i, className: 'dsh-lit-ev' },
            h('div', { className: 'dsh-lit-ev-head', style: { alignItems: 'center' } },
              h('span', { className: 'dsh-lit-ev-claim', style: srcIsSelf ? {} : { fontWeight: 400, opacity: .85 } },
                (srcIsSelf ? '（本条）' : '') + String(r.source == null ? r.source_id : r.source)),
              h('span', { className: 'dsh-lit-tag', style: { borderColor: '#60a5fa66', color: '#60a5fa' } }, '—' + String(r.relation || '关联') + '→'),
              h('span', { className: 'dsh-lit-ev-claim', style: dstIsSelf ? {} : { fontWeight: 400, opacity: .85 } },
                String(r.target == null ? r.target_id : r.target) + (dstIsSelf ? '（本条）' : '')),
            ),
            h('div', { className: 'dsh-lit-ev-foot' },
              h('span', { className: 'dsh-lit-muted' }, '#' + r.source_id + ' → #' + r.target_id)),
          )
        }))
        : h('div', { className: 'dsh-lit-empty' }, '（暂无关联关系）'),
    ),
    h('div', { key: 'src', className: 'dsh-lit-card', style: { marginTop: 10 } },
      h('div', { className: 'dsh-lit-meta', style: { fontWeight: 600, marginBottom: 4 } }, '关联证据 evidence_source · ' + srcs.length),
      srcs.length
        ? h('div', { className: 'dsh-lit-list' }, srcs.map(function (f) {
          const ev = f.evidence
          return h(EvidenceRow, { key: 'es' + ev.id, ev: ev })
        }))
        : h('div', { className: 'dsh-lit-empty' }, '（暂无关联证据）'),
    ),
  ])
}

function KnowledgeView(props) {
  const workspaceId = props.workspaceId
  const initialId = props.focusId
  const [items, setItems] = React.useState([])
  const [library, setLibrary] = React.useState('')
  const [includeArchived, setIncludeArchived] = React.useState(false)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState('')
  const [openId, setOpenId] = React.useState(initialId != null ? initialId : null)

  React.useEffect(function () {
    let alive = true
    async function load() {
      setLoading(true); setError('')
      const ws = qs({ workspace_id: workspaceId, library: library || '', archived: includeArchived || '', k: 300 })
      try {
        if (includeArchived) {
          // “含归档”：active + archived 两个批次合并展示，条目上带归档标记
          const [a, b] = await Promise.all([
            api('/knowledge-browse' + qs({ workspace_id: workspaceId, library: library || '', archived: false, k: 300 })),
            api('/knowledge-browse' + qs({ workspace_id: workspaceId, library: library || '', archived: true, k: 300 })),
          ])
          if (!alive) return
          const merged = (a.items || []).concat(b.items || [])
          merged.sort(function (x, y) { return Number(y.id) - Number(x.id) })
          setItems(merged)
        } else {
          const res = await api('/knowledge-browse' + ws)
          if (!alive) return
          setItems((res && res.items) || [])
        }
      } catch (e) {
        if (alive) setError(String((e && e.message) || e))
      } finally {
        if (alive) setLoading(false)
      }
    }
    load()
    return function () { alive = false }
  }, [workspaceId, library, includeArchived])

  React.useEffect(function () {
    if (initialId != null && props.onFocusConsumed) props.onFocusConsumed()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (openId != null) {
    return h(KnowledgeDetail, { kid: openId, workspaceId: workspaceId, onBack: function () { setOpenId(null) } })
  }

  const sel = h('select', {
    key: 'sel', className: 'dsh-lit-select', value: library, title: '按知识库过滤',
    onChange: function (e) { setLibrary(e.target.value) },
  }, [
    h('option', { key: 'all', value: '' }, '全部知识库'),
  ].concat(LIBRARIES.map(function (lib) {
    return h('option', { key: lib, value: lib }, lib + (LIB_LABEL[lib] ? ' · ' + LIB_LABEL[lib] : ''))
  })))

  return h('div', null, [
    h('div', { key: 'toolbar', className: 'dsh-lit-toolbar' },
      sel,
      h('label', { key: 'arch', className: 'dsh-lit-meta', style: { cursor: 'pointer', gap: 4 } },
        h('input', { type: 'checkbox', checked: includeArchived, onChange: function (e) { setIncludeArchived(e.target.checked) } }),
        '含归档',
      ),
      h('span', { key: 'count', className: 'dsh-lit-count' }, '共 ' + items.length + ' 条' + (includeArchived ? '（含归档）' : '')),
      error ? h('span', { key: 'e', className: 'dsh-lit-err' }, error) : null,
    ),
    h('div', { key: 'list', className: 'dsh-lit-list dsh-lit-scroll', style: { marginTop: 8 } },
      items.length
        ? items.map(function (it) {
          const arch = isArchived(it)
          return h('button', { key: String(it.id), className: 'dsh-lit-item', onClick: function () { setOpenId(it.id) } },
            h('div', { className: 'dsh-lit-item-title' },
              h('span', { className: 'dsh-lit-tt' }, it.concept || '(无概念名)'),
              libraryChip(it.library, 'lib' + it.id),
              arch ? h('span', { key: 'arch', className: 'dsh-lit-tag dsh-lit-arch-badge' }, '已归档') : null,
            ),
            it.summary ? h('div', { className: 'dsh-lit-summary' }, String(it.summary)) : null,
            h('div', { className: 'dsh-lit-meta', style: { marginTop: 4 } },
              it.source_memory_id != null ? h('span', { key: 'sm', className: 'dsh-lit-muted' }, 'memory#' + it.source_memory_id) : null,
              h('span', { key: 'id', className: 'dsh-lit-muted' }, '#' + it.id),
              it.updated_at ? h('span', { key: 'up', className: 'dsh-lit-muted' }, '更新 ' + fmtTime(it.updated_at)) : null,
            ),
          )
        })
        : h('div', { className: 'dsh-lit-empty' }, loading ? '加载中…' : '（该过滤条件下暂无知识点）'),
    ),
  ])
}

// ══════════════════════════════════════════════════════════════════
// 3) 知识图谱视窗（SVG 手绘力导向 + 库下拉过滤 + 节点着色）
// ══════════════════════════════════════════════════════════════════
function GraphView(props) {
  const workspaceId = props.workspaceId
  const onOpenKnowledge = props.onOpenKnowledge
  const W = 1000
  const H = 620
  const [library, setLibrary] = React.useState('')
  const [data, setData] = React.useState(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState('')
  const [tf, setTf] = React.useState({ k: 1, x: 0, y: 0 })
  const [overrides, setOverrides] = React.useState({})
  const [seed, setSeed] = React.useState(0)
  const [hover, setHover] = React.useState(null)
  const [info, setInfo] = React.useState(null)
  const svgRef = React.useRef(null)
  const gesture = React.useRef(null)

  async function load() {
    setLoading(true); setError('')
    try {
      const res = await api('/graph' + qs({ workspace_id: workspaceId, library: library || '' }))
      const g = (res && res.graph) || {}
      const nodes = Array.isArray(g.nodes) ? g.nodes : []
      const edges = Array.isArray(g.edges) ? g.edges : []
      setData({ nodes: nodes, edges: edges })
      setInfo(null); setOverrides({}); setTf({ k: 1, x: 0, y: 0 })
    } catch (e) { setError(String((e && e.message) || e)) }
    finally { setLoading(false) }
  }
  React.useEffect(function () { load() }, [library, workspaceId])

  const layout = React.useMemo(function () {
    if (!data) return {}
    return buildGraphLayout(data.nodes, data.edges, W, H, seed)
  }, [data, seed])

  // 非 passive 滚轮缩放
  React.useEffect(function () {
    const el = svgRef.current
    if (!el) return
    function onWheel(e) {
      e.preventDefault()
      const rect = el.getBoundingClientRect()
      const scaleX = rect.width / W
      const scaleY = rect.height / H
      const factor = e.deltaY < 0 ? 1.16 : 0.86
      setTf(function (prev) {
        const k2 = Math.max(0.35, Math.min(6, prev.k * factor))
        const wx = (e.clientX - rect.left) / scaleX
        const wy = (e.clientY - rect.top) / scaleY
        return { k: k2, x: wx - (wx - prev.x) / prev.k * k2, y: wy - (wy - prev.y) / prev.k * k2 }
      })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return function () { el.removeEventListener('wheel', onWheel) }
  }, [])

  function toWorld(e) {
    const rect = svgRef.current.getBoundingClientRect()
    const scaleX = rect.width / W
    const scaleY = rect.height / H
    return {
      x: (e.clientX - rect.left) / scaleX,
      y: (e.clientY - rect.top) / scaleY,
    }
  }

  function posOf(id) {
    const o = overrides[id]
    if (o) return o
    return layout[id]
  }

  function onPointerDown(e) {
    const svg = svgRef.current
    if (!svg) return
    svg.setPointerCapture(e.pointerId)
    const w = toWorld(e)
    // 命中的节点？
    let hit = null
    if (data) {
      data.nodes.some(function (n) {
        const p = posOf(String(n.id))
        if (!p) return false
        const dx = w.x - p.x, dy = w.y - p.y
        if (dx * dx + dy * dy <= (p.r + 6) * (p.r + 6)) { hit = n; return true }
        return false
      })
    }
    if (hit) {
      const p = posOf(String(hit.id))
      gesture.current = {
        mode: 'node', id: String(hit.id), node: hit,
        px: e.clientX, py: e.clientY,
        bx: p.x, by: p.y, k: tf.k, moved: false,
      }
    } else {
      gesture.current = { mode: 'pan', px: e.clientX, py: e.clientY, ox: tf.x, oy: tf.y, k: tf.k, moved: false }
    }
  }

  function onPointerMove(e) {
    const g = gesture.current
    if (!g) return
    const svg = svgRef.current
    const rect = svg.getBoundingClientRect()
    const dx = e.clientX - g.px
    const dy = e.clientY - g.py
    if (Math.abs(dx) + Math.abs(dy) > 3) g.moved = true
    if (g.mode === 'node') {
      const dWorldX = dx / (rect.width / W) / g.k
      const dWorldY = dy / (rect.height / H) / g.k
      setOverrides(function (prev) {
        const next = Object.assign({}, prev)
        next[g.id] = { id: g.id, r: (layout[g.id] && layout[g.id].r) || 10, x: g.bx + dWorldX, y: g.by + dWorldY }
        return next
      })
    } else {
      setTf(function (prev) { return { k: prev.k, x: g.ox + dx / (rect.width / W), y: g.oy + dy / (rect.height / H) } })
    }
  }

  function onPointerUp(e) {
    const g = gesture.current
    if (g && g.mode === 'node' && !g.moved && g.node) setInfo(g.node)
    gesture.current = null
    try { svgRef.current.releasePointerCapture(e.pointerId) } catch (err) { /* ignore */ }
  }

  const nodes = (data && data.nodes) || []
  const edges = (data && data.edges) || []
  const libCounts = {}
  nodes.forEach(function (n) { const k = n.library || 'unknown'; libCounts[k] = (libCounts[k] || 0) + 1 })

  const edgeEls = edges.map(function (e, i) {
    const a = posOf(String(e.source))
    const b = posOf(String(e.target))
    if (!a || !b) return null
    return h('g', { key: 'e' + i },
      h('title', null, (e.source_concept || String(e.source)) + ' —' + (e.relation || '关联') + '→ ' + (e.target_concept || String(e.target))),
      h('line', { x1: a.x, y1: a.y, x2: b.x, y2: b.y, className: 'dsh-lit-gedge', strokeWidth: 1.4 }),
    )
  })

  const nodeEls = nodes.map(function (n) {
    const p = posOf(String(n.id))
    if (!p) return null
    const col = libraryColor(n.library)
    const dim = hover != null && hover !== String(n.id) ? 0.4 : 1
    const label = String(n.concept || n.id)
    return h('g', {
      key: 'n' + n.id,
      className: 'dsh-lit-gnode',
      opacity: dim,
      onPointerDown: onPointerDown,
      onPointerEnter: function () { setHover(String(n.id)) },
      onPointerLeave: function () { setHover(null) },
    },
      h('title', null, label + (n.library ? ' [' + n.library + ']' : '')),
      h('circle', { cx: p.x, cy: p.y, r: p.r || 10, fill: col, stroke: 'rgba(0,0,0,.35)', strokeWidth: hover === String(n.id) ? 2 : 1 }),
      h('text', { x: p.x, y: p.y + (p.r || 10) + 12, className: 'dsh-lit-glabel', textAnchor: 'middle' }, clipLabel(label, 26)),
    )
  })

  function legendRows() {
    return LIBRARIES.concat('unknown').map(function (lib) {
      const c = libCounts[lib]
      if (!c) return null
      return h('span', { key: lib, className: 'dsh-lit-key' },
        h('span', { className: 'dsh-lit-dot', style: { background: libraryColor(lib) } }),
        (LIB_LABEL[lib] || lib) + ' ' + c)
    }).filter(Boolean)
  }

  const adj = {}
  edges.forEach(function (e) {
    adj[String(e.source)] = (adj[String(e.source)] || 0) + 1
    adj[String(e.target)] = (adj[String(e.target)] || 0) + 1
  })

  const infoPanel = info
    ? h('div', { className: 'dsh-lit-side' },
      h('div', { className: 'dsh-lit-card', style: { display: 'flex', flexDirection: 'column', gap: 6 } },
        h('div', { className: 'dsh-lit-muted' }, '图谱节点 #' + info.id),
        h('div', { className: 'dsh-lit-item-title' }, info.concept || '(无概念名)'),
        libraryChip(info.library, 'info'),
        h('div', { className: 'dsh-lit-kv' },
          h('span', { className: 'dsh-lit-k' }, '连接边数'),
          h('span', { className: 'dsh-lit-v' }, String(adj[String(info.id)] || 0)),
        ),
        onOpenKnowledge
          ? h('button', { className: 'dsh-lit-btn dsh-lit-btn-primary', onClick: function () { onOpenKnowledge(Number(info.id)) } }, '打开知识条目详情 →')
          : null,
        h('button', { className: 'dsh-lit-btn dsh-lit-btn-mini', onClick: function () { setInfo(null) } }, '关闭'),
      ))
    : null

  return h('div', null, [
    h('div', { key: 'toolbar', className: 'dsh-lit-toolbar' },
      h('label', { className: 'dsh-lit-meta', style: { gap: 4 } }, '知识库:'),
      h('select', { className: 'dsh-lit-select', value: library, onChange: function (e) { setLibrary(e.target.value) } },
        [h('option', { key: 'all', value: '' }, '全部（无过滤）')].concat(LIBRARIES.map(function (lib) {
          return h('option', { key: lib, value: lib }, lib + (LIB_LABEL[lib] ? ' · ' + LIB_LABEL[lib] : ''))
        }))),
      h('button', { key: 're', className: 'dsh-lit-btn dsh-lit-btn-mini', onClick: load, disabled: loading }, '重新加载'),
      h('button', { key: 'rz', className: 'dsh-lit-btn dsh-lit-btn-mini', onClick: function () { setTf({ k: 1, x: 0, y: 0 }); setOverrides({}); setSeed(seed + 1) } }, '重排 / 复位'),
      h('span', { key: 'count', className: 'dsh-lit-count' }, '节点 ' + nodes.length + ' · 边 ' + edges.length),
      error ? h('span', { key: 'e', className: 'dsh-lit-err' }, error) : null,
    ),
    h('div', { key: 'box', className: 'dsh-lit-card dsh-lit-graphbox', style: { marginTop: 8, padding: 10 } },
      h('div', { className: 'dsh-lit-svg-wrap' },
        h('div', { className: 'dsh-lit-abs' },
          h('svg', {
            ref: svgRef, className: 'dsh-lit-svg' + (gesture.current ? ' dsh-lit-dragging' : ''),
            viewBox: '0 0 ' + W + ' ' + H,
            onPointerDown: onPointerDown,
            onPointerMove: onPointerMove,
            onPointerUp: onPointerUp,
            onPointerCancel: function () { gesture.current = null },
          },
            h('g', { transform: 'translate(' + tf.x + ',' + tf.y + ') scale(' + tf.k + ')' },
              h('rect', { x: -2000, y: -2000, width: 8000, height: 8000, fill: 'transparent' }),
              edgeEls,
              nodeEls,
            ),
          ),
          loading ? h('div', { className: 'dsh-lit-loading' }, '图谱加载中…') : null,
        ),
        nodes.length === 0 && !loading
          ? h('div', { key: 'empty', className: 'dsh-lit-empty' }, '（当前过滤下暂无图谱节点' + (edges.length ? '，但有 ' + edges.length + ' 条悬空边' : '') + '。可先切换知识库或在知识视窗中沉淀知识点）')
          : null,
        edges.length === 0 && nodes.length > 0
          ? h('div', { className: 'dsh-lit-hint', style: { marginTop: 4 } }, '当前尚无关系边：节点已按知识库着色，建立 knowledge relations 后连线会出现。')
          : null,
        h('div', { className: 'dsh-lit-legend' },
          legendRows(),
          h('span', { className: 'dsh-lit-muted' }, '拖拽节点调整 · 滚轮缩放 · 拖空白平移 · 悬停高亮'),
        ),
      ),
      infoPanel,
    ),
  ])
}

// ══════════════════════════════════════════════════════════════════
// 4) 状况窗口（记忆库 / 知识 / 图谱 / 配置 状态卡）
// ══════════════════════════════════════════════════════════════════
function StatusView(props) {
  const workspaceId = props.workspaceId
  const [st, setSt] = React.useState(null)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState('')

  async function load() {
    setBusy(true); setError('')
    const ws = workspaceId || ''
    const res = {}
    const grab = async function (key, path) {
      try { res[key] = await api(path) } catch (e) { res[key + 'Err'] = String((e && e.message) || e) }
    }
    await Promise.all([
      grab('kb', '/kb/browse'),
      grab('count', '/knowledge-count' + qs({ workspace_id: ws })),
      grab('active', '/knowledge-browse' + qs({ workspace_id: ws, archived: false, k: 1000 })),
      grab('arch', '/knowledge-browse' + qs({ workspace_id: ws, archived: true, k: 1000 })),
      grab('graph', '/graph' + qs({ workspace_id: ws })),
      grab('cfg', '/config'),
    ])
    setSt(res)
    setBusy(false)
    const errs = ['kbErr', 'countErr', 'activeErr', 'archErr', 'graphErr', 'cfgErr']
      .filter(function (k) { return res[k] })
      .map(function (k) { return k.replace('Err', '') + ': ' + res[k] })
    if (errs.length) setError('部分数据源不可用：' + errs.join('；'))
  }
  React.useEffect(function () { load() }, [workspaceId])

  function card(label, big, subLines, color) {
    return h('div', { key: label, className: 'dsh-lit-stat' },
      h('div', { className: 'dsh-lit-stat-label' }, label),
      h('div', { className: 'dsh-lit-stat-big', style: color ? { color: color } : {} }, big),
      subLines.length ? h('div', { className: 'dsh-lit-stat-sub' }, subLines.map(function (l, i) {
        return h('div', { key: 'l' + i }, l)
      })) : null,
    )
  }

  const cards = []
  if (!st && busy) return h('div', null, '加载状况…')
  if (!st) return h('div', null, error || '加载失败')
  const kbLibs = (st.kb && st.kb.libraries) || {}
  const kbIds = Object.keys(kbLibs)
  const kbTotal = kbIds.reduce(function (acc, k) { return acc + Number((kbLibs[k] && kbLibs[k].total) || 0) }, 0)
  const kbArch = kbIds.reduce(function (acc, k) { return acc + Number((kbLibs[k] && kbLibs[k].archived) || 0) }, 0)
  const kbSub = [
    kbIds.length ? kbIds.map(function (k) { return k + ' ' + ((kbLibs[k] && kbLibs[k].total) || 0) }).join(' · ') : '（deepmemory 上游无库数据）',
    kbArch ? '其中归档 ' + kbArch + ' 条' : '',
    kbIds.length ? '库: ' + kbIds.join(' / ') : '',
  ].filter(Boolean)
  // runtime 库 topics 展示最热主题
  const hotLib = LIBRARIES.map(function (l) { return { l: l, t: kbLibs[l] && kbLibs[l].topics } })
    .filter(function (x) { return x.t })
    .sort(function (a, b) { return Object.keys(b.t).length - Object.keys(a.t).length })[0]
  if (hotLib) {
    const topics = Object.keys(hotLib.t)
      .filter(function (k) { return String(k) !== '0' && String(k) !== '' })
      .map(function (k) { return { name: k, n: Number(hotLib.t[k]) || 0 } })
      .sort(function (a, b) { return b.n - a.n })
      .slice(0, 4)
    if (topics.length) kbSub.push(hotLib.l + ' 主题: ' + topics.map(function (t) { return t.name + '×' + t.n }).join('、'))
  }
  cards.push(card('deepmemory 记忆库（5 库目录）', kbTotal ? String(kbTotal) + ' 条' : '—', kbSub, '#60a5fa'))

  const kCount = st.count && st.count.count != null ? Number(st.count.count) : null
  const activeItems = (st.active && st.active.items) || []
  const archItems = (st.arch && st.arch.items) || []
  const perLib = {}
  activeItems.forEach(function (it) { const l = it.library || 'unknown'; perLib[l] = (perLib[l] || 0) + 1 })
  const knSub = [
    LIBRARIES.map(function (l) { return l + ' ' + (perLib[l] || 0) }).join(' · '),
    archItems.length ? '另归档 ' + archItems.length + ' 条' : '无归档条目',
    st.activeErr || st.archErr ? '(分库数据不可用)' : '',
  ].filter(Boolean)
  cards.push(card('本库知识（literature 知识点）', kCount != null ? kCount + ' 条' : '—', knSub, '#34d399'))

  const g = (st.graph && st.graph.graph) || {}
  const gnodes = Array.isArray(g.nodes) ? g.nodes : []
  const gedges = Array.isArray(g.edges) ? g.edges : []
  const gLib = {}
  gnodes.forEach(function (n) { const l = n.library || 'unknown'; gLib[l] = (gLib[l] || 0) + 1 })
  cards.push(card('知识图谱（概念网络）', String(gnodes.length) + ' 节点', [
    '关系边 ' + gedges.length + ' 条',
    LIBRARIES.map(function (l) { return l + ' ' + (gLib[l] || 0) }).join(' · '),
  ], '#a78bfa'))

  const cfg = (st.cfg && st.cfg.config) || {}
  const cfgKeys = Object.keys(cfg)
  const cfgLines = cfgKeys.slice(0, 7).map(function (k) {
    const v = cfg[k]
    const sv = typeof v === 'string' ? v : JSON.stringify(v)
    return k + ': ' + short(sv, 46)
  })
  cards.push(card('配置摘要（/config）', String(cfgKeys.length) + ' 项', cfgKeys.length
    ? cfgLines.concat(cfgKeys.length > 7 ? ['… 等 ' + cfgKeys.length + ' 项'] : [])
    : ['（未配置任何项，可到 设置 → 插件配置 卡片维护）'], '#f59e0b'))

  return h('div', null, [
    h('div', { key: 'tool', className: 'dsh-lit-toolbar' },
      h('span', { className: 'dsh-lit-meta', style: { fontWeight: 600 } }, '状况窗口'),
      h('span', { className: 'dsh-lit-ws' }, 'workspace: ' + (workspaceId || '—')),
      h('button', { key: 'r', className: 'dsh-lit-btn dsh-lit-btn-mini', onClick: load, disabled: busy }, busy ? '刷新中…' : '刷新'),
      error ? h('span', { key: 'e', className: 'dsh-lit-err' }, error) : null,
    ),
    h('div', { key: 'cards', className: 'dsh-lit-stats', style: { marginTop: 8 } }, cards),
    h('div', { key: 'note', className: 'dsh-lit-hint', style: { marginTop: 8 } },
      '本窗口为只读状态摘要：deepmemory 记忆库计数来自 /kb/browse，本库知识与图谱计数来自 /knowledge-* 与 /graph，均按当前 workspace 统计。'),
  ])
}

// ══════════════════════════════════════════════════════════════════
// conversation 面板主组件（四子视图切换）
// ══════════════════════════════════════════════════════════════════
function LiteraturePanel(props) {
  const workspaceId = resolveWorkspaceId(props)
  const [view, setView] = React.useState('docs')
  const [focusId, setFocusId] = React.useState(null)

  function openKnowledge(id) { setFocusId(id); setView('knowledge') }

  const tabs = [
    { id: 'docs', label: '📄 文档' },
    { id: 'knowledge', label: '🧠 知识' },
    { id: 'graph', label: '🕸 图谱' },
    { id: 'status', label: '📊 状况' },
  ]
  const content = view === 'docs'
    ? h(DocumentsView, { key: 'docs', workspaceId: workspaceId })
    : view === 'knowledge'
      ? h(KnowledgeView, { key: 'knowledge', workspaceId: workspaceId, focusId: focusId, onFocusConsumed: function () { setFocusId(null) } })
      : view === 'graph'
        ? h(GraphView, { key: 'graph', workspaceId: workspaceId, onOpenKnowledge: openKnowledge })
        : h(StatusView, { key: 'status', workspaceId: workspaceId })

  return h('div', { className: 'dsh-lit-panel' },
    h('div', { className: 'dsh-lit-topbar' },
      h('span', { className: 'dsh-lit-brand' }, '📚 literature 文献知识库'),
      h('span', { className: 'dsh-lit-ws' }, workspaceId),
      h('div', { className: 'dsh-lit-tabs' },
        tabs.map(function (t) {
          return h('button', {
            key: t.id, className: 'dsh-lit-tab' + (view === t.id ? ' dsh-lit-tab-on' : ''),
            onClick: function () { setView(t.id) },
          }, t.label)
        }),
      ),
    ),
    h('div', { style: { display: 'flex', flexDirection: 'column', minWidth: 0 } }, content),
  )
}

// ══════════════════════════════════════════════════════════════════
// 插件配置卡片（设置 → 插件 → 插件配置页）—— 保持既有 schema 驱动实现
// ══════════════════════════════════════════════════════════════════
function ConfigView() {
  const [schema, setSchema] = React.useState(null)
  const [values, setValues] = React.useState({})
  const [msg, setMsg] = React.useState('')

  React.useEffect(function () {
    Promise.all([api('/config-schema'), api('/config')]).then(function (res) {
      const s = res[0], c = res[1]
      if (s && s.schema) setSchema(s.schema)
      if (c && c.config) setValues(c.config)
    }).catch(function (e) { setMsg('加载配置失败: ' + String((e && e.message) || e)) })
  }, [])

  if (!schema) return h('div', null, '加载配置…')

  const groups = Object.keys(schema)
  const rows = []
  groups.forEach(function (gname) {
    const g = schema[gname]
    rows.push(h('h4', { key: 'h' + gname, style: { margin: '12px 0 4px', fontSize: 13 } }, (g && g.description) || gname))
    const items = (g && g.items) || {}
    Object.keys(items).forEach(function (key) {
      const item = items[key]
      const full = gname + '.' + key
      const val = values[full] !== undefined ? values[full] : item.default
      rows.push(h('div', { key: full, style: { marginBottom: 8 } }, [
        h('label', { key: 'l', style: { display: 'block', fontSize: 12, fontWeight: 600 } },
          (item && (item.description || key)) || key + (item && item.readonly ? '（只读）' : '')),
        h('input', {
          key: 'i', value: val === undefined || val === null ? '' : String(val),
          readOnly: !!(item && item.readonly),
          style: { width: '100%', padding: '4px 8px', border: '1px solid #ccc', borderRadius: 4, background: 'transparent', color: 'inherit' },
          onChange: function (e) {
            let next = e.target.value
            if (item && item.type === 'number') next = Number(next)
            setValues(function (v) { return Object.assign({}, v, { [full]: next }) })
          },
        }),
        item && item.hint ? h('div', { key: 'hint', style: { fontSize: 11, color: '#888' } }, String(item.hint)) : null,
      ]))
    })
  })

  async function save() {
    try {
      await api('/config', { method: 'POST', body: values })
      setMsg('已保存')
    } catch (e) { setMsg('保存失败: ' + String((e && e.message) || e)) }
  }

  return h('div', null, [
    h('h3', { key: 't', style: { fontSize: 15 } }, 'literature 文献库配置'),
    ...rows,
    h('div', { key: 'actions', style: { marginTop: 12 } }, [
      h('button', { key: 's', onClick: save, className: 'dsh-lit-btn' }, '保存'),
      msg ? h('span', { key: 'm', style: { marginLeft: 8, fontSize: 12 } }, msg) : null,
    ]),
  ])
}

// ══════════════════════════════════════════════════════════════════
// 注册
// ══════════════════════════════════════════════════════════════════
function apply(ctx) {
  const slots = ctx.get('slots')
  if (slots === undefined) return

  if (typeof document !== 'undefined') {
    const existed = document.head.querySelector('style[data-plugin="dsh-literature"]')
    if (!existed) {
      const styleEl = document.createElement('style')
      styleEl.dataset.plugin = 'dsh-literature'
      styleEl.textContent = LIT_CSS
      document.head.appendChild(styleEl)
    }
  }

  // conversation 面板 tab：文献/知识/图谱/状况 四子视图
  slots.inject('conversation.view', function () {
    return slots.register(
      { name: 'conversation.view', id: 'literature', order: 60, label: '📚 literature' },
      function (props) { return React.createElement(LiteraturePanel, props) },
    )
  })

  // 插件配置卡片：设置 → 插件 → 插件配置页（配置项保留在此，tab 内不放置设置入口）
  slots.inject('settings.plugin.item', function* () {
    yield slots.register(
      { name: 'settings.plugin.item', id: 'literature', key: 'literature', order: 60, label: 'literature 文献库' },
      function () { return React.createElement(ConfigView, {}) },
    )
  })
}

return { name, apply }
  }
})
