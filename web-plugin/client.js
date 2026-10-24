__ModuleLoader__.load({
  id: 'dsh-literature',
  factory: (require) => {
const React = require('react')
const UI = require('@deepseek-ai/dsh-client-ui-primitives')
const h = React.createElement
const name = 'dsh-literature'
const API = '/lit-api/v1/literature'
const DEFAULT_WORKSPACE = 'deepseek-harness'
const LIBRARIES = ['bias', 'core', 'eco', 'project', 'runtime', 'matsci', 'maxphase']
const LIB_LABEL = {
  bias: 'bias 约束', core: 'core 核心', eco: 'eco 生态', project: 'project 项目', runtime: 'runtime 运行',
  // P22：库内存英文码，插件显示中文名
  matsci: '材料科学基础通用', maxphase: 'MAX相金属反应',
}
const LIB_COLOR = {
  bias: 'var(--dsw-alias-state-warn-primary)',
  core: 'var(--dsw-alias-brand-primary)',
  eco: 'var(--dsw-alias-state-success-primary)',
  project: 'var(--dsw-alias-state-business-primary)',
  runtime: 'var(--dsw-alias-state-error-primary)',
  // P22 新增两库：不走主题 token（剩余 token 色相不够用），改用中间明度固定色 ——
  // 色相刻意远离已有五个（琥珀/蓝/绿/紫/红）：matsci 青绿 ~174°、maxphase 品红 ~312°；
  // 对比度（白底/深底 #16181c）：#0e8f84 = 3.98:1 / 4.47:1，#cc3fb0 = 4.28:1 / 4.15:1，
  // 两个主题下都 ≥3:1（图形元素阈值）。若将来主题化，这两处是最小改动点。
  matsci: '#0e8f84',
  maxphase: '#cc3fb0',
  unknown: 'var(--dsw-alias-label-secondary)',
}
// ── 库列表：以 GET /libraries 为事实源；上面三个常量降级为「兜底」 ──
//  （加库 = 服务端插一行 ⇒ 插件刷新即见，不用改代码、不用重启任何东西）
const LIB_FALLBACK_LABEL = LIB_LABEL
const LIB_FALLBACK_COLOR = LIB_COLOR
let libraryCatalog = { codes: LIBRARIES.slice(), labels: Object.assign({}, LIB_LABEL), colors: Object.assign({}, LIB_COLOR), source: 'fallback' }
const libraryWatchers = new Set()
let libraryRequest = null            // 一次会话只拉一次
function libraryCodes() { return libraryCatalog.codes }
function libraryLabel(code) { const key = code == null ? '' : String(code); return libraryCatalog.labels[key] || LIB_FALLBACK_LABEL[key] || key || '未分类' }
function libraryKnown(code) { return libraryCatalog.codes.indexOf(String(code == null ? '' : code)) >= 0 }
function setLibraryCatalog(next) { libraryCatalog = next; libraryWatchers.forEach(function (watch) { watch() }) }
function loadLibraries(force) {
  if (libraryRequest && !force) return libraryRequest
  libraryRequest = api('/libraries').then(function (res) {
    const items = list(res && res.libraries).filter(function (item) { return item && item.code })
    if (!items.length) return libraryCatalog          // 空列表 ⇒ 保留兜底
    const codes = [], labels = {}, colors = {}
    items.forEach(function (item) {                    // 接口已按 sort_order, code 排好，无需再排
      const code = String(item.code)
      if (codes.indexOf(code) >= 0) return
      codes.push(code)
      labels[code] = String(item.display_name || item.label || code)
      if (item.color) {
        // 可能是 var(--dsw-…) 或 #RRGGBB；var() 里补一个主题内兜底，避免该 token 在当前主题缺失时圆点变透明
        colors[code] = String(item.color).replace(/^var\((--[A-Za-z0-9_-]+)\)$/, 'var($1, var(--dsw-alias-label-secondary))')
      }
    })
    setLibraryCatalog({ codes: codes, labels: labels, colors: colors, source: 'api' })
    return libraryCatalog
  }).catch(function () { return libraryCatalog })     // 失败/老服务端 ⇒ 兜底，不抛、不白屏
  return libraryRequest
}
function reloadLibraries() { return loadLibraries(true) }
function useLibraries() {
  const [, bump] = React.useState(0)
  React.useEffect(function () {
    let alive = true
    const watch = function () { if (alive) bump(function (n) { return n + 1 }) }
    libraryWatchers.add(watch)
    loadLibraries()
    return function () { alive = false; libraryWatchers.delete(watch) }
  }, [])
  return libraryCatalog
}
// 数据里出现「接口没返回的 code」时：按 code 原样显示并给中性色，信息不丢
function libraryDisplayLabel(code) { return code == null || code === '' ? '未分类' : libraryLabel(code) }
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
.dsh-lit-graph-edge { stroke:var(--dsw-alias-border-l2); fill:none; transition:opacity .14s, stroke-opacity .14s; }
/* 按边来源分线型：断言（支持/反驳）显眼、提示（相似）细淡、同源/同义中性、抽取按关系着色 */
.dsh-lit-graph-edge-sim { stroke-opacity:.45; }
.dsh-lit-graph-edge-support { stroke:#f2b26a; stroke-width:2.3; stroke-opacity:.95; }
.dsh-lit-graph-edge-contradict { stroke:#ff5f5f; stroke-width:2.8; stroke-opacity:1; stroke-dasharray:7 3.5; }
.dsh-lit-graph-edge-context { stroke:#a7b8c8; stroke-width:1.4; stroke-opacity:.72; }
.dsh-lit-graph-edge-synonym { stroke:#9aa7b2; stroke-width:1.3; stroke-opacity:.8; stroke-dasharray:3 3; }
.dsh-lit-graph-edge-extracted { stroke:#79c0ff; stroke-width:1.9; stroke-opacity:.9; }
.dsh-lit-graph-edge-dim { stroke-opacity:.1; }
/* 有机岛形：密度场 → marching squares → 平滑闭合路径 */
.dsh-lit-graph-island { pointer-events:none; transition:opacity .2s; }
.dsh-lit-graph-island-l0 { fill-opacity:.10; stroke-opacity:.42; stroke-width:1.3; }
.dsh-lit-graph-island-l1 { fill-opacity:.05; stroke-opacity:.3; stroke-width:1; stroke-dasharray:5 3; }
.dsh-lit-graph-island-name { fill:var(--dsw-alias-label-secondary); font-size:12px; paint-order:stroke; stroke:var(--dsw-alias-bg-layer-1); stroke-width:3; pointer-events:none; }
.dsh-lit-graph-key-line { width:26px; height:10px; flex:none; }
/* 左右分栏：左=图谱，右=知识快速预览（可折叠） */
.dsh-lit-graphbox { display:grid; grid-template-columns:minmax(0,1fr); gap:12px; align-items:start; }
.dsh-lit-graphbox-preview { grid-template-columns:minmax(0,1fr) 340px; }
.dsh-lit-graph-preview { min-width:0; display:flex; flex-direction:column; gap:9px; max-height:clamp(480px,86vh,920px); overflow:auto;
  background:var(--dsw-alias-bg-layer-1); border:1px solid var(--dsw-alias-border-l1); border-radius:8px; padding:12px; }
.dsh-lit-preview-head { display:flex; align-items:flex-start; gap:8px; }
.dsh-lit-preview-title { margin:0; font-size:15px; font-weight:600; line-height:1.35; overflow-wrap:anywhere; }
.dsh-lit-preview-sub { color:var(--dsw-alias-label-secondary); font-size:11.5px; }
.dsh-lit-preview-kv { display:grid; grid-template-columns:auto 1fr; gap:3px 10px; font-size:12px; color:var(--dsw-alias-label-secondary); }
.dsh-lit-preview-kv b { color:var(--dsw-alias-label-primary); font-weight:600; }
.dsh-lit-preview-chips { display:flex; gap:6px; flex-wrap:wrap; }
.dsh-lit-preview-chips span { font-size:11.5px; padding:1px 8px; border-radius:9px; background:var(--dsw-alias-bg-layer-2); color:var(--dsw-alias-label-secondary); }
.dsh-lit-preview-list { display:flex; flex-direction:column; gap:2px; margin:0; padding:0; list-style:none; }
.dsh-lit-preview-item { display:flex; align-items:center; gap:6px; width:100%; padding:4px 6px; border:0; border-radius:6px;
  background:transparent; color:inherit; font:inherit; text-align:left; cursor:pointer; }
.dsh-lit-preview-item:hover { background:var(--dsw-alias-bg-layer-2); }
.dsh-lit-preview-item .t { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.dsh-lit-preview-item .k { margin-left:auto; flex:none; font-size:11px; color:var(--dsw-alias-label-secondary); }
.dsh-lit-preview-section { font-size:11px; letter-spacing:.06em; color:var(--dsw-alias-label-secondary); }
.dsh-lit-preview-evs { display:flex; flex-direction:column; gap:8px; margin:0; padding:0; list-style:none; }
.dsh-lit-preview-ev { border:1px solid var(--dsw-alias-border-l1); border-radius:6px; padding:7px 8px; display:flex; flex-direction:column; gap:4px; }
.dsh-lit-preview-ev-head { display:flex; align-items:center; gap:8px; flex-wrap:wrap; font-size:11px; }
.dsh-lit-preview-ev-claim { font-size:12.5px; line-height:1.45; }
.dsh-lit-preview-ev-text { font-size:11.5px; line-height:1.5; color:var(--dsw-alias-label-secondary); border-left:2px solid var(--dsw-alias-border-l2); padding-left:7px; white-space:pre-wrap; overflow-wrap:anywhere; }
.dsh-lit-preview-more { align-self:flex-start; border:0; background:transparent; color:var(--dsw-alias-brand-primary); font:inherit; font-size:11px; cursor:pointer; padding:0; }
/* ── P29 认识演进链（试点） ── */
.dsh-lit-chain-list { display:flex; flex-direction:column; gap:16px; }
.dsh-lit-chain-scope { font-size:11px; color:var(--dsw-alias-label-secondary); }
.dsh-lit-chain-hero { display:flex; gap:16px; align-items:stretch; flex-wrap:wrap; padding:12px; border-radius:10px;
  border:1px solid var(--dsw-alias-border-l1); background:var(--dsw-alias-bg-layer-1); }
.dsh-lit-chain-hero-main { display:flex; align-items:baseline; gap:8px; flex:none; padding-right:16px; border-right:1px solid var(--dsw-alias-border-l1); }
.dsh-lit-chain-hero-num { font-size:40px; line-height:1; font-weight:700; color:var(--dsw-alias-state-success-primary); font-variant-numeric:tabular-nums; }
.dsh-lit-chain-hero-unit { font-size:12px; color:var(--dsw-alias-label-secondary); }
.dsh-lit-chain-hero-side { display:flex; flex-direction:column; gap:6px; min-width:0; flex:1 1 260px; }
.dsh-lit-chain-hero-counts { display:flex; gap:6px; flex-wrap:wrap; }
.dsh-lit-chain-hero-note { font-size:11px; line-height:1.5; color:var(--dsw-alias-label-secondary); }
.dsh-lit-chain-hero-note b { color:var(--dsw-alias-label-primary); }
.dsh-lit-chain-flow { display:flex; flex-direction:column; gap:0; }
.dsh-lit-chain-stage { border:1px solid var(--dsw-alias-border-l1); border-radius:10px; padding:10px 12px; display:flex; flex-direction:column; gap:6px; background:var(--dsw-alias-bg-layer-1); }
.dsh-lit-chain-stage-from { border-style:solid; }
.dsh-lit-chain-stage-to { border-color:var(--dsw-alias-state-success-primary); }
.dsh-lit-chain-stage-head { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.dsh-lit-chain-stage-name { font-size:12px; font-weight:600; color:var(--dsw-alias-label-primary); }
.dsh-lit-chain-statement { font-size:14px; line-height:1.6; }
.dsh-lit-chain-meta { display:flex; flex-direction:column; gap:3px; font-size:11px; color:var(--dsw-alias-label-secondary); }
.dsh-lit-chain-year-unknown { display:inline-flex; align-items:center; gap:4px; padding:1px 7px; border:1px dashed var(--dsw-alias-border-l2); border-radius:9px; font-size:11px; color:var(--dsw-alias-label-secondary); }
.dsh-lit-chain-transcribed { color:var(--dsw-alias-state-warn-primary); }
.dsh-lit-chain-arrow { display:flex; align-items:center; gap:8px; padding:6px 0 6px 14px; font-size:11.5px; color:var(--dsw-alias-label-secondary); }
.dsh-lit-chain-arrow-line { width:2px; align-self:stretch; min-height:18px; background:var(--dsw-alias-border-l2); margin-left:4px; }
.dsh-lit-chain-arrow b { color:var(--dsw-alias-label-primary); }
.dsh-lit-chain-ev { border:1px solid var(--dsw-alias-border-l1); border-radius:8px; padding:8px 10px; display:flex; flex-direction:column; gap:5px; min-width:0; }
.dsh-lit-chain-ev-invalid { border-style:dashed; border-color:var(--dsw-alias-state-error-primary); background:color-mix(in srgb, var(--dsw-alias-state-error-primary) 7%, transparent); }
.dsh-lit-chain-ev-weak { border-color:var(--dsw-alias-state-warn-primary); }
.dsh-lit-chain-ev-head { display:flex; align-items:center; gap:8px; flex-wrap:wrap; font-size:11px; color:var(--dsw-alias-label-secondary); }
.dsh-lit-chain-ev-title { font-size:12.5px; font-weight:600; }
.dsh-lit-chain-quote { margin:0; padding:6px 8px; border-left:2px solid var(--dsw-alias-border-l2); background:var(--dsw-alias-bg-layer-2);
  font-size:11.5px; line-height:1.55; white-space:pre-wrap; overflow-wrap:anywhere; color:var(--dsw-alias-label-secondary); }
.dsh-lit-chain-quote-open { color:var(--dsw-alias-label-primary); }
.dsh-lit-chain-flag { font-size:11px; line-height:1.5; color:var(--dsw-alias-state-warn-primary); }
.dsh-lit-chain-prov { font-size:11px; }
.dsh-lit-chain-prov-btn { border:0; background:transparent; color:var(--dsw-alias-brand-primary); font:inherit; font-size:11px; cursor:pointer; padding:0; }
.dsh-lit-chain-hero-how { font-size:10.5px; color:var(--dsw-alias-label-secondary); border-bottom:1px dashed var(--dsw-alias-border-l2); cursor:help; }
/* 条件分支：中性虚线 + 左粗边，视觉上既不属于反驳方也不属于新认识方 */
.dsh-lit-chain-branch { border:1px dashed var(--dsw-alias-border-l2); border-left:4px solid var(--dsw-alias-label-secondary);
  border-radius:8px; padding:9px 11px; display:flex; flex-direction:column; gap:5px; background:transparent; }
.dsh-lit-chain-branch-head { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.dsh-lit-chain-branch-icon { font-size:13px; opacity:.85; }
.dsh-lit-chain-branch-cond { font-size:12.5px; font-weight:600; }
.dsh-lit-chain-branch-holds { font-size:12.5px; line-height:1.55; color:var(--dsw-alias-label-primary); }
.dsh-lit-chain-branch-why { font-size:11.5px; line-height:1.55; color:var(--dsw-alias-label-secondary); }
.dsh-lit-chain-aligned { border:1px solid var(--dsw-alias-border-l1); border-radius:8px; overflow:hidden; }
.dsh-lit-chain-aligned-head { display:flex; align-items:center; gap:8px; width:100%; padding:7px 10px; border:0;
  background:var(--dsw-alias-bg-layer-2); color:var(--dsw-alias-label-primary); font:inherit; font-size:12px; text-align:left; cursor:pointer; }
.dsh-lit-chain-aligned-head .dsh-lit-muted { margin-left:auto; }
.dsh-lit-chain-aligned-item { display:flex; flex-direction:column; gap:5px; padding:8px 10px; border-top:1px solid var(--dsw-alias-border-l1); }
.dsh-lit-chain-genesis { font-size:10.5px; line-height:1.55; color:var(--dsw-alias-label-secondary); padding-top:8px; border-top:1px dashed var(--dsw-alias-border-l1); }
.dsh-lit-chain-anchor { font-size:11px; color:var(--dsw-alias-label-secondary); }
.dsh-lit-chain-warn { font-size:11.5px; line-height:1.5; color:var(--dsw-alias-state-warn-primary); background:color-mix(in srgb, var(--dsw-alias-state-warn-primary) 12%, transparent); border-radius:6px; padding:5px 7px; }
.dsh-lit-chain-invalid-why { font-size:11.5px; line-height:1.5; color:var(--dsw-alias-state-error-primary); }
.dsh-lit-chain-more { align-self:flex-start; border:0; background:transparent; color:var(--dsw-alias-brand-primary); font:inherit; font-size:11px; cursor:pointer; padding:0; }
.dsh-lit-chain-caveats { margin:0; padding-left:18px; font-size:11.5px; line-height:1.6; color:var(--dsw-alias-label-secondary); }
.dsh-lit-chain-caveats li { margin:2px 0; }
.dsh-lit-preview-warn { font-size:11.5px; line-height:1.45; color:var(--dsw-alias-state-warn-primary); background:color-mix(in srgb, var(--dsw-alias-state-warn-primary) 12%, transparent); border-radius:6px; padding:5px 7px; }
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

function fmtSize(bytes) {
  const b = Number(bytes) || 0
  if (b < 1024) return b + ' B'
  if (b < 1048576) return (b / 1024).toFixed(1) + ' KB'
  return (b / 1048576).toFixed(1) + ' MB'
}

function isArchived(item) { return !!item && (item.archived === 1 || item.archived === true || String(item.archived) === 'true') }
function libraryColor(library) { const key = library == null ? '' : String(library); return libraryCatalog.colors[key] || LIB_FALLBACK_COLOR[key] || LIB_FALLBACK_COLOR.unknown }
function message(error) { return String(error && error.message || error) }
function list(value) { return Array.isArray(value) ? value : [] }
function pathFor(kind, id, workspaceId) { return '/' + kind + '/' + encodeURIComponent(String(id)) + qs({ workspace_id: workspaceId }) }
// P18 新接口：一次拿全某知识点的证据（含 claim / evidence_text），口径与 /graph 的 ev_* 计数一致。
// limit=0 不限条数、max_chars=0 不截断（截断与否交给前端折叠，避免丢信息）。
function knowledgeEvidencePath(kid, workspaceId, options) {
  const opts = options || {}
  return '/knowledge/' + encodeURIComponent(String(kid)) + '/evidence' + qs({
    workspace_id: workspaceId,
    limit: opts.limit == null ? 0 : opts.limit,
    max_chars: opts.max_chars == null ? 0 : opts.max_chars,
  })
}
async function fetchKnowledgeEvidence(kid, workspaceId) {
  const res = await api(knowledgeEvidencePath(kid, workspaceId))
  const items = list(res && res.evidence)
  const count = res && res.count != null ? Number(res.count) : items.length
  return { items: items, count: isFinite(count) ? count : items.length }
}
// 接口尚未上线（404）时，知识详情视图退回旧的逐条取法；其余错误照实报出来。
function isMissingEndpoint(error) { return /404|not found|Not Found/.test(message(error)) }

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
  // 有会话但工作区表尚未加载：返回 null（调用方显示加载态），
  // 避免先按 DEFAULT 渲染出 deepseek-harness 再跳转（视觉闪烁）。
  if (serverWs === null) return null
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
    libraryDisplayLabel(library))
}

function archivedChip() { return h('span', { className: 'dsh-lit-mini dsh-lit-archived' }, '已归档') }

function LibrarySelect(props) {
  // 选项 = 接口目录（按接口顺序）+ 数据里出现但目录没有的 code（原样显示，别丢信息）
  const catalog = useLibraries()
  const codes = catalog.codes.slice()
  list(props.extra).forEach(function (code) { if (code && codes.indexOf(String(code)) < 0) codes.push(String(code)) })
  if (props.value && codes.indexOf(String(props.value)) < 0) codes.push(String(props.value))
  return h('select', {
    className: 'dsh-lit-select', value: props.value, 'aria-label': '知识库', title: '知识库',
    onChange: function (event) { props.onChange(event.target.value) },
  }, h('option', { value: '' }, '全部知识库'),
  codes.map(function (code) { return h('option', { key: code, value: code }, libraryDisplayLabel(code)) }))
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

function buildGraphLayout(nodes, edges, width, height, seed, communities, inset, values, radii, subdivisions, contentAspect) {
  const positions = Object.create(null), islands = []
  if (!nodes.length) return { positions: positions, islands: islands }
  const value = values || {}, nodeRadius = radii || {}
  const top = inset ? inset.top : 36, bottom = inset ? inset.bottom : 36
  const usableHeight = Math.max(100, height - top - bottom)
  // 打包用的宽高比：优先用「容器真实宽高比」——宽容器就该摊成宽群岛，否则左右必然大片空白
  const aspect = Math.max(0.2, contentAspect || (width - 72) / usableHeight)
  const localEdges = new Map(communities.themes.map(function (theme) { return [theme.id, []] }))
  edges.forEach(function (edge) {
    const a = communities.byNode.get(String(edge.source)), b = communities.byNode.get(String(edge.target))
    if (a && a === b && String(edge.source) !== String(edge.target)) localEdges.get(a.id).push(edge)
  })
  const plans = []
  communities.themes.forEach(function (theme) {
    const radius = 42 + Math.sqrt(theme.members.length) * 48
    // 价值向心 + 子岛分扇区：组内按价值降序排环（最高价值靠组心），组间按扇区摆开 ⇒ 子岛互不重叠
    const ranked = theme.members.slice().sort(function (a, b) {
      return (value[b] || 0) - (value[a] || 0) || String(a).localeCompare(String(b))
    })
    const groupInfo = subdivisions && subdivisions.get(theme.id)
    let grouped = [ranked]
    if (groupInfo && groupInfo.themes.length > 1) {
      grouped = groupInfo.themes.map(function (sub) {
        return sub.members.slice().sort(function (a, b) { return (value[b] || 0) - (value[a] || 0) || String(a).localeCompare(String(b)) })
      })
    }
    const sector = grouped.length > 1 ? Math.PI * 2 / grouped.length : 0
    // 细分岛多留 50% 的半径 + 更靠外的扇区：子岛之间要留出海岸线的空隙
    const layoutRadius = grouped.length > 1 ? radius * 1.5 : radius
    const offset = grouped.length > 1 ? layoutRadius * 0.7 : 0
    const groupRadius = grouped.length > 1
      ? Math.min(layoutRadius * 0.3, offset * Math.sin(Math.PI / grouped.length) * 0.88)
      : layoutRadius - 44
    const points = []
    grouped.forEach(function (members, groupIndex) {
      const angle0 = (groupIndex + seed * 0.618) * sector - Math.PI / 2
      const centreX = grouped.length > 1 ? Math.cos(angle0) * offset : 0
      const centreY = grouped.length > 1 ? Math.sin(angle0) * offset : 0
      members.forEach(function (id, index) {
        const angle = (index + seed * 0.618) * 2.399963229728653
        const ring = members.length === 1 ? 0 : groupRadius * Math.sqrt((index + 0.5) / members.length)
        const size = nodeRadius[String(id)]
        const point = { id: id, x: centreX + Math.cos(angle) * ring, y: centreY + Math.sin(angle) * ring,
          cx: centreX, cy: centreY, ring: ring, groupRadius: groupRadius, vx: 0, vy: 0,
          r: size || (9 + Math.min(10, Math.sqrt(communities.adjacency.get(id).size) * 1.8)) }
        positions[id] = point
        points.push(point)
      })
    })
    const iterations = points.length > 240 ? 160 : 280
    function constrain(point) {
      const distance = Math.hypot(point.x, point.y), limit = layoutRadius - point.r - 22
      if (distance > limit) { point.x *= limit / distance; point.y *= limit / distance }
      if (grouped.length > 1) {                       // 子岛点不出自己的扇区圆
        const dx = point.x - point.cx, dy = point.y - point.cy
        const local = Math.hypot(dx, dy) || 1, localLimit = point.groupRadius + point.r * .6
        if (local > localLimit) { point.x = point.cx + dx / local * localLimit; point.y = point.cy + dy / local * localLimit }
      }
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
        const dx = point.x - point.cx, dy = point.y - point.cy
        const distance = Math.hypot(dx, dy) || 1
        const pull = (distance - point.ring) * 0.02      // 价值向心：拉回所属价值环（相对组心）
        point.vx -= dx / distance * pull
        point.vy -= dy / distance * pull
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
    // 本岛的有机轮廓（局部坐标）→ 用「轮廓半径」而不是「圆半径」参与打包，海岸线之间才有空隙
    const sigmaBase = Math.max(14, layoutRadius * 0.07), sigmaCap = Math.max(40, layoutRadius * 0.28)
    const shape = graphIslandShape(points, { base: sigmaBase, cap: sigmaCap, step: 7, threshold: .3 })
    plans.push({ theme: theme, points: points, r: shape ? shape.r : layoutRadius, cx: shape ? shape.cx : 0,
      cy: shape ? shape.cy : 0, sigmaBase: sigmaBase, sigmaCap: sigmaCap })
  })
  // 打包：非重叠摆放岛屿（间隙 30px），再按轮廓中心平移各岛
  plans.forEach(function (plan) {
    const island = { theme: plan.theme, x: 0, y: 0, r: plan.r + 30 }
    if (islands.length) {
      let best = null, score = Infinity
      islands.forEach(function (anchor) {
        for (let step = 0; step < 48; step += 1) {
          const angle = step * Math.PI / 24
          const x = anchor.x + Math.cos(angle) * (anchor.r + island.r + 30)
          const y = anchor.y + Math.sin(angle) * (anchor.r + island.r + 30)
          const cost = x * x / aspect + y * y * aspect
          if (cost >= score || islands.some(function (other) { return Math.hypot(x - other.x, y - other.y) < island.r + other.r + 29 })) continue
          best = { x: x, y: y }; score = cost
        }
      })
      island.x = best ? best.x : Math.max.apply(null, islands.map(function (other) { return other.x + other.r })) + island.r + 30
      island.y = best ? best.y : 0
    }
    islands.push(island)
    plan.island = island
    const dx = island.x - plan.cx, dy = island.y - plan.cy
    plan.points.forEach(function (point) { point.x += dx; point.y += dy })
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
  plans.forEach(function (plan) {
    plan.island.sigmaBase = plan.sigmaBase * scale
    plan.island.sigmaCap = plan.sigmaCap * scale
    plan.island.localRadius = plan.r * scale
  })
  return { positions: positions, islands: islands }
}

function KnowledgeDetail(props) {
  const { kid, workspaceId } = props
  const [docId, setDocId] = React.useState(null)
  const resource = useResource(async function () {
    const res = await api(pathFor('knowledge', kid, workspaceId))
    if (!res || !res.knowledge) throw new Error('知识条目不存在')
    const item = res.knowledge
    // P19：一次请求拿全（替代原来对 item.sources 的 N 次 fan-out）
    try {
      const payload = await fetchKnowledgeEvidence(kid, workspaceId)
      return { item: item, evidence: payload.items.map(function (ev) { return { id: ev.id, evidence: ev } }), evidenceCount: payload.count, evidencePath: 'endpoint' }
    } catch (error) {
      // 旧服务端（接口未重启生效）才回退逐条取；业务错误（401/超时等）照实显示，不掩盖
      if (!isMissingEndpoint(error)) return { item: item, evidence: [], evidenceError: message(error) }
      const fallback = await Promise.all(list(item.sources).map(async function (id) {
        try {
          const result = await api(pathFor('evidence', id, workspaceId))
          if (!result || !result.evidence) throw new Error('证据不存在')
          return { id: id, evidence: result.evidence }
        } catch (inner) { return { id: id, error: message(inner) } }
      }))
      return { item: item, evidence: fallback, evidenceCount: fallback.length, evidencePath: 'fanout' }
    }
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
        data.evidenceError ? h(Notice, { text: '证据接口不可用：' + data.evidenceError, error: true, retry: resource.reload })
          : data.evidence.length ? data.evidence.map(function (result) {
            return result.evidence ? h(EvidenceRow, { key: result.id, ev: result.evidence, onOpenDocument: setDocId })
              : h(Notice, { key: result.id, text: '证据 #' + result.id + '：' + result.error, error: true, retry: resource.reload })
          }) : h(Empty, null, '暂无关联证据'),
        data.evidencePath === 'fanout' && data.evidence.length ? h('div', { className: 'dsh-lit-muted' },
          '旧服务端逐条取回 ' + data.evidence.length + ' 条（/knowledge/<id>/evidence 需重启后生效）') : null)
    ) : null)
}

// ── P29 认识演进链（试点）：数据完全驱动，加一条链 = 服务端 /chains 多一条数据，不改代码 ──
const CHAIN_STRENGTH = {
  strong: { key: 'strong', label: 'strong 强', hint: '直接冲突/直接反驳' },
  weak: { key: 'weak', label: 'weak 弱', hint: '间接佐证，未直接否定旧认识' },
  invalid: { key: 'invalid', label: 'invalid 不成立', hint: '经核验不构成证据' },
}
const CHAIN_STATUS = { superseded: '已被取代', current: '当前认识', refined_by_later_work: '被后续工作细化', open: '待验证', experiment_settled: '🔬 实验已裁决', single: '单篇证据', consensus: '有共识', gap: '研究空白', disputed: '有分歧' }
const CHAIN_POLARITY = { negative: '否定式', positive: '肯定式' }
const CHAIN_ROLE = { refutes: '反驳', supports: '支持', qualifies: '限定' }
const CHAIN_STRENGTH_ORDER = ['strong', 'weak', 'invalid']
function chainStrengthOf(item) {
  const key = String(item && item.strength || '').toLowerCase()
  return CHAIN_STRENGTH[key] || { key: key || 'unknown', label: String(item && item.strength || '未标强度'), hint: '' }
}
// 数据里的文本用 **…** 标记强调：渲染成 <strong>，其余原样（不做别的 markdown）
function chainRich(text) {
  const raw = String(text == null ? '' : text)
  if (raw.indexOf('**') < 0) return raw
  return raw.split('**').map(function (part, index) {
    if (!part) return ''
    return index % 2 === 1 ? h('strong', { key: 'b' + index }, part) : part
  })
}
function chainStatusLabel(status) { return CHAIN_STATUS[String(status || '')] || String(status || '') }
function chainPolarityLabel(polarity) { return CHAIN_POLARITY[String(polarity || '')] || String(polarity || '') }
function chainRoleLabel(role) { return CHAIN_ROLE[String(role || '')] || String(role || '') }
// 归一化：接口可以返回 {chains:[…]} / […] / 单个链对象
function normalizeChains(payload) {
  const raw = payload && payload.chains ? payload.chains : payload
  const items = Array.isArray(raw) ? raw : (raw && (raw.chain_id || raw.topic || raw.from_belief) ? [raw] : [])
  return items.filter(function (item) { return item && (item.chain_id || item.topic) })
}
async function fetchChains() {
  try {
    const payload = await api('/chains')
    return { chains: normalizeChains(payload), error: '' }
  } catch (error) {
    return { chains: [], error: message(error) }     // JSON/接口读不到 ⇒ 空态，不白屏
  }
}
// 独立来源数 vs 证据条数：主标题只给独立来源，证据条数降为副信息（数据自带的独立来源字段优先）
function chainStrengthSummary(chain) {
  const summary = chain.evidence_summary || {}
  const transitions = list(chain.transitions)
  const groups = {}
  transitions.forEach(function (item) {
    if (chainStrengthOf(item).key === 'invalid') return     // 不成立的证据不计入独立来源
    const group = String(item.source_group || item.doc || '')
    if (group) groups[group] = (groups[group] || 0) + 1
  })
  // Q3 裁决：以「证据分组去重」为准（可审计）；与数据字段不一致时两个都显示并告警，不静默选边
  const audited = Object.keys(groups).length
  const declarations = []
  function declare(label, value) {
    if (value == null || value === '') return
    const number = Number(value)
    if (isFinite(number)) declarations.push({ label: label, value: number })
  }
  declare('independent_sources', chain.independent_sources)
  declare('evidence_summary.distinct_independent_sources', summary.distinct_independent_sources)
  const mismatchList = declarations.filter(function (item) { return item.value !== audited })
  const declared = declarations.length ? declarations[0].value : null
  const mismatch = mismatchList.length > 0
  const independent = audited
  const total = Number(summary.total) || transitions.length
  const biggest = Object.keys(groups).reduce(function (max, key) { return Math.max(max, groups[key]) }, 0)
  return {
    independent: independent,
    audited: audited,
    declared: declared,
    mismatch: mismatch,
    mismatchList: mismatchList,
    scope: summary.scope || '',
    groups: list(chain.source_groups).length ? list(chain.source_groups) : Object.keys(groups),
    total: total,
    strong: Number(summary.strong) || transitions.filter(function (item) { return chainStrengthOf(item).key === 'strong' }).length,
    weak: Number(summary.weak) || transitions.filter(function (item) { return chainStrengthOf(item).key === 'weak' }).length,
    invalid: Number(summary.invalid) || transitions.filter(function (item) { return chainStrengthOf(item).key === 'invalid' }).length,
    biggest: biggest,
    note: summary.note || '',
  }
}
function ChainEvidence(props) {
  const item = props.item
  const strength = chainStrengthOf(item)
  const open = !!props.open
  const quote = String(item.quote == null ? '' : item.quote)
  return h('div', { className: 'dsh-lit-chain-ev' + (strength.key === 'invalid' ? ' dsh-lit-chain-ev-invalid' : '') + (strength.key === 'weak' ? ' dsh-lit-chain-ev-weak' : '') },
    h('div', { className: 'dsh-lit-chain-ev-head' },
      h('span', { className: 'dsh-lit-mini', style: { color: strength.key === 'invalid' ? 'var(--dsw-alias-state-error-primary)' : strength.key === 'strong' ? 'var(--dsw-alias-state-success-primary)' : strength.key === 'weak' ? 'var(--dsw-alias-state-warn-primary)' : 'inherit' } }, strength.label),
      h('span', null, String(item.doc || '') + (item.year ? ' · ' + item.year : '') + (item.journal ? ' · ' + String(item.journal) : '')),
      h('span', null, chainRoleLabel(item.role)),
      item.source_group ? h('span', { className: 'dsh-lit-muted' }, item.source_group) : null),
    h('div', { className: 'dsh-lit-chain-ev-title' }, String(item.title || '')),
    // 标题出处：可点，点开显示这套 title/journal/year 是从哪来的（数据出错时有人能发现）
    props.provenance || item.title_source ? h('div', { className: 'dsh-lit-chain-prov' },
      h('button', { type: 'button', className: 'dsh-lit-chain-prov-btn', onClick: function () { props.onToggleProv(props.itemKey) } },
        'ⓘ 标题出处：' + String(item.title_source || props.provenance.titles_source || '未标注') + (props.provOpen ? '（收起）' : '')),
      props.provOpen ? h('div', { className: 'dsh-lit-muted' },
        [props.provenance && props.provenance.note ? String(props.provenance.note) : '',
          props.provenance && props.provenance.corrected_at ? '修正于 ' + String(props.provenance.corrected_at) : '',
          item.journal ? '期刊 ' + String(item.journal) : ''].filter(Boolean).join(' · ')) : null) : null,
    // 原文锚点：section + 字符区间（字段缺失就不显示），让人能回原文核对
    (function () {
      const parts = []
      if (item.section) parts.push(String(item.section))
      if (item.char_start != null && item.char_end != null) parts.push('字符 ' + item.char_start + '-' + item.char_end)
      else if (item.char_start != null) parts.push('字符 ' + item.char_start + '+')
      if (item.anchor) parts.push(String(item.anchor))
      return parts.length ? h('div', { className: 'dsh-lit-chain-anchor' }, '原文锚点：' + parts.join(' · ')) : null
    })(),
    // 原文照实显示：不裁、不改写；含 PDF 拼接残片时把提示一并摆出来
    h('blockquote', { className: 'dsh-lit-chain-quote' + (open ? ' dsh-lit-chain-quote-open' : '') }, quote),
    item.quote_clean_note ? h('div', { className: 'dsh-lit-chain-flag' }, '原文含 PDF 双栏拼接残片：本视图照实显示未裁剪 —— ' + String(item.quote_clean_note)) : null,
    strength.key === 'invalid' ? h('div', { className: 'dsh-lit-chain-invalid-why' },
      '不构成证据' + (item.invalid_reason ? '：' + String(item.invalid_reason) : '') + (item.why ? '（' + String(item.why) + '）' : '')) : null,
    open ? h(React.Fragment, null,
      item.why ? h('div', { className: 'dsh-lit-text' }, String(item.why)) : null,
      item.caveat ? h('div', { className: 'dsh-lit-chain-flag' }, '抽取疑点：' + String(item.caveat)) : null,
      h('div', { className: 'dsh-lit-muted' }, '出现编号 ' + String(item.occ || '—') + ' · 来源组 ' + String(item.source_group || '—'))) : null,
    h('button', { type: 'button', className: 'dsh-lit-chain-more', onClick: function () { props.onToggle(props.itemKey) } },
      open ? '收起' : '展开（判定理由 / 疑点）'))
}
function ChainCard(props) {
  const chain = props.chain
  const summary = chainStrengthSummary(chain)
  const from = chain.from_belief || {}
  const to = chain.to_belief || {}
  const transitions = list(chain.transitions)
  const openMap = props.openMap || {}
  const idOf = function (item, index) { return String(chain.chain_id || 'chain') + ':' + String(item.occ || item.doc || index) }
  return h('div', { className: 'dsh-lit-box dsh-lit-stack' },
    h('div', null,
      h('h2', { className: 'dsh-lit-heading' }, String(chain.topic || '（未命名认识演进）')),
      chain.scope_note ? h('div', { className: 'dsh-lit-chain-scope' }, String(chain.scope_note)) : null,
      chain.data_provenance ? h('div', { className: 'dsh-lit-chain-scope' },
        '数据出处：标题/期刊/年份来自 ' + String(chain.data_provenance.titles_source || '未标注') +
        (chain.data_provenance.corrected_at ? ' · 修正于 ' + String(chain.data_provenance.corrected_at) : '') +
        (chain.data_provenance.note ? ' —— ' + String(chain.data_provenance.note) : '')) : null),
    // ① 主标题：独立来源数（大）——证据条数只作副信息
    h('div', { className: 'dsh-lit-chain-hero' },
      h('div', {
        className: 'dsh-lit-chain-hero-main',
        title: '按证据的 source_group 去重计数（invalid 不成立的证据不计入）—— 可逐条审计；与数据标注值不一致时会在下方给出告警',
      },
        h('div', { className: 'dsh-lit-chain-hero-num' }, String(summary.independent)),
        h('div', null, h('div', { className: 'dsh-lit-chain-hero-unit' }, '篇独立论文'), h('div', { className: 'dsh-lit-chain-hero-unit' }, '共同反驳旧认识')),
        h('span', { className: 'dsh-lit-chain-hero-how', title: '按证据的 source_group 去重计数（invalid 不计入）' }, '怎么算的')),
      h('div', { className: 'dsh-lit-chain-hero-side' },
        h('div', { className: 'dsh-lit-chain-hero-counts' },
          list(summary.groups).map(function (group) { return h('span', { key: group, className: 'dsh-lit-mini' }, String(group)) })),
        h('div', { className: 'dsh-lit-chain-hero-note' },
          '证据 ' + summary.total + ' 条（', h('b', null, 'strong ' + summary.strong), ' · ',
          h('b', null, 'weak ' + summary.weak), ' · ', h('b', null, 'invalid ' + summary.invalid), '）',
          summary.biggest ? '——其中 ' + summary.biggest + ' 条来自同一篇论文，' : '',
          '强度看独立来源数，不看证据条数'),
        summary.mismatch ? h('div', { className: 'dsh-lit-chain-warn' },
          '⚠ 不一致：证据分组算出 ' + summary.audited + ' 个独立来源；数据标注 ' +
          summary.mismatchList.map(function (item) { return item.value + '（' + item.label + '）' }).join('、') +
          ' —— 按证据分组显示，请核查数据') : null,
        summary.scope ? h('div', { className: 'dsh-lit-chain-hero-note' }, chainRich(summary.scope)) : null,
        summary.note ? h('div', { className: 'dsh-lit-chain-hero-note' }, String(summary.note)) : null)),
    // ② 两端认识 + 被谁反驳
    h('div', { className: 'dsh-lit-chain-flow' },
      h('div', { className: 'dsh-lit-chain-stage dsh-lit-chain-stage-from' },
        h('div', { className: 'dsh-lit-chain-stage-head' },
          h('span', { className: 'dsh-lit-chain-stage-name' }, '旧认识 · ' + String(from.assertion_id || '')),
          h('span', { className: 'dsh-lit-mini' }, chainStatusLabel(from.status) || '已陈述'),
          from.polarity ? h('span', { className: 'dsh-lit-mini' }, chainPolarityLabel(from.polarity)) : null),
        h('div', { className: 'dsh-lit-chain-statement' }, String(from.statement || '')),
        h('div', { className: 'dsh-lit-chain-meta' },
          h('div', null, '年份：', from.year != null && from.year !== ''
            ? h('span', null, String(from.year))
            : h('span', { className: 'dsh-lit-chain-year-unknown' }, '未给出（不臆造）'),
            from.year_note ? h('span', null, ' —— ', chainRich(from.year_note)) : null),
          from.evidence_source ? h('div', { className: 'dsh-lit-chain-transcribed' }, '来源标注：' + String(from.evidence_source)) : null)),
      h('div', { className: 'dsh-lit-chain-arrow' },
        h('div', { className: 'dsh-lit-chain-arrow-line' }),
        h('div', null, '被 ', h('b', null, summary.independent + ' 篇独立论文'), ' ', chainRoleLabel(list(transitions)[0] && transitions[0].role) || '反驳',
          ' ⇒ 旧认识被取代')),
      h('div', { className: 'dsh-lit-chain-stage dsh-lit-chain-stage-to' },
        h('div', { className: 'dsh-lit-chain-stage-head' },
          h('span', { className: 'dsh-lit-chain-stage-name' }, '新认识 · ' + String(to.assertion_id || '')),
          h('span', { className: 'dsh-lit-mini' }, chainStatusLabel(to.status) || '当前'),
          to.polarity ? h('span', { className: 'dsh-lit-mini' }, chainPolarityLabel(to.polarity)) : null),
        h('div', { className: 'dsh-lit-chain-statement' }, String(to.statement || '')))),
    // ③ 实验裁决：文献只提供观点分布，**"谁对"由实验裁决** —— 这是本系统唯一由用户提供的一层
    list(chain.experiment_verdicts).length ? h('div', { className: 'dsh-lit-stack' },
      h('div', { className: 'dsh-lit-section-head' },
        h('h3', { className: 'dsh-lit-title' },
          '🔬 实验裁决 · ' + list(chain.experiment_verdicts).length + ' 条'
          + '（文献只给观点分布，谁对由实验裁决）')),
      list(chain.experiment_verdicts).map(function (v, index) {
        const dir = { support_side: '支持正方', refute_side: '支持反方',
                      neither: '两方都不成立（新解释）', inconclusive: '尚无结论' }[v.verdict] || v.verdict
        const st = { proposed: '待确认', confirmed: '已确认', retracted: '已撤回' }[v.status] || v.status
        const col = v.status === 'confirmed'
          ? 'var(--dsw-alias-state-error-primary, #e24a4a)'
          : 'var(--dsw-alias-state-warn-primary, #e0a020)'
        const cond = v.conditions || {}
        const meas = v.measured || {}
        return h('div', { key: 'exp' + index, className: 'dsh-lit-box dsh-lit-stack',
                          style: { borderLeft: '3px solid ' + col, paddingLeft: '10px' } },
          h('div', { className: 'dsh-lit-actions' },
            h('span', { style: { color: col, fontWeight: 700 } }, '🔬 ' + dir),
            h('span', { className: 'dsh-lit-mini' }, st),
            v.performed_by ? h('span', { className: 'dsh-lit-muted' }, 'by ' + String(v.performed_by)) : null,
            v.performed_at ? h('span', { className: 'dsh-lit-muted' },
              new Date(Number(v.performed_at) * 1000).toISOString().slice(0, 10)) : null),
          h('div', { className: 'dsh-lit-text' }, String(v.note || '')),
          Object.keys(cond).length ? h('div', { className: 'dsh-lit-muted' },
            '实验条件：' + Object.keys(cond).map(function (k) {
              return k + '=' + String(cond[k])
            }).join(' ｜ ')) : null,
          Object.keys(meas).length ? h('div', { className: 'dsh-lit-muted', style: { fontFamily: 'ui-monospace, monospace' } },
            '实测：' + JSON.stringify(meas).slice(0, 240)) : null,
          list(v.attachments).length ? h('div', { className: 'dsh-lit-muted' },
            '附件 ' + list(v.attachments).length + ' 个：' + list(v.attachments).join(', ').slice(0, 160)) : null,
          v.status !== 'confirmed' ? h('div', { className: 'dsh-lit-chain-flag' },
            '⚠ 尚未确认（确认后才算"实验已裁决"）') : null)
      })) : null,
    // ③ 条件分支：一条并列的适用范围（不是反驳、不是争议）—— 虚线中性边框 + 📐
    list(chain.condition_branches).length ? h('div', { className: 'dsh-lit-stack' },
      h('div', { className: 'dsh-lit-section-head' },
        h('h3', { className: 'dsh-lit-title' }, '📐 条件分支 · ' + list(chain.condition_branches).length + ' 条（并列适用范围：既不是反驳，也不是争议）')),
      list(chain.condition_branches).map(function (branch, index) {
        return h('div', { key: index, className: 'dsh-lit-chain-branch' },
          h('div', { className: 'dsh-lit-chain-branch-head' },
            h('span', { className: 'dsh-lit-chain-branch-icon', 'aria-hidden': true }, '📐'),
            h('span', { className: 'dsh-lit-chain-branch-cond' }, String(branch.condition || '（未命名条件）')),
            h('span', { className: 'dsh-lit-mini' }, '条件不同 ⇒ 各自成立'),
            branch.quality_tier ? h('span', { className: 'dsh-lit-muted' }, '文本质量 ' + String(branch.quality_tier)) : null),
          branch.holds ? h('div', { className: 'dsh-lit-chain-branch-holds' }, chainRich(branch.holds)) : null,
          h('div', { className: 'dsh-lit-chain-ev-head' },
            h('span', null, String(branch.doc || '') + (branch.year ? ' · ' + branch.year : '') + (branch.journal ? ' · ' + String(branch.journal) : ''))),
          branch.title ? h('div', { className: 'dsh-lit-chain-ev-title' }, String(branch.title)) : null,
          branch.quote ? h('blockquote', { className: 'dsh-lit-chain-quote' }, String(branch.quote)) : null,
          branch.why_branch ? h('div', { className: 'dsh-lit-chain-branch-why' }, '为什么是分支而非争议：', chainRich(branch.why_branch)) : null)
      })) : null,
    // ④ 同向补充（可折叠，默认收起）：把"曾被误判 + 已更正"留在界面上
    list(chain.aligned_support).length ? (function () {
      const items = list(chain.aligned_support)
      const open = !!props.alignedOpen
      return h('div', { className: 'dsh-lit-chain-aligned' },
        h('button', {
          type: 'button', className: 'dsh-lit-chain-aligned-head', 'aria-expanded': open ? 'true' : 'false',
          onClick: function () { props.onToggleAligned() },
        },
          h('span', null, '✓ 同向补充（曾被判定器误判）· ' + items.length + ' 条'),
          h('span', { className: 'dsh-lit-muted' }, open ? '收起' : '展开')),
        open ? h('div', { className: 'dsh-lit-stack' }, items.map(function (item, index) {
          return h('div', { key: index, className: 'dsh-lit-chain-aligned-item' },
            h('div', { className: 'dsh-lit-chain-ev-head' },
              h('span', { className: 'dsh-lit-mini' }, '✓ 同向补充'),
              h('span', null, String(item.doc || '') + (item.year ? ' · ' + item.year : '') + (item.journal ? ' · ' + String(item.journal) : '')),
              item.quality_tier ? h('span', { className: 'dsh-lit-muted' }, '文本质量 ' + String(item.quality_tier)) : null),
            item.title ? h('div', { className: 'dsh-lit-chain-ev-title' }, String(item.title)) : null,
            item.quote ? h('blockquote', { className: 'dsh-lit-chain-quote' }, String(item.quote)) : null,
            item.relation ? h('div', { className: 'dsh-lit-text' }, chainRich(item.relation)) : null,
            item.note ? h('div', { className: 'dsh-lit-chain-flag' }, '⚠ ' + String(item.note)) : null)
        })) : null)
    })() : null,
    // ⑤ 证据：按强度分组，invalid 也显示（不隐藏）
    h('div', { className: 'dsh-lit-stack' },
      CHAIN_STRENGTH_ORDER.map(function (key) {
        const items = transitions.filter(function (item) { return chainStrengthOf(item).key === key })
        if (!items.length) return null
        const meta = CHAIN_STRENGTH[key]
        return h('div', { key: key, className: 'dsh-lit-stack' },
          h('div', { className: 'dsh-lit-section-head' },
            h('h3', { className: 'dsh-lit-title' }, (meta ? meta.label : key) + ' · ' + items.length + ' 条' + (meta && meta.hint ? '（' + meta.hint + '）' : ''))),
          items.map(function (item, index) {
            const id = idOf(item, index)
            return h(ChainEvidence, {
              key: id, itemKey: id, item: item, open: !!openMap[id], onToggle: props.onToggle,
              provenance: chain.data_provenance || null, provOpen: !!(props.provMap || {})[id], onToggleProv: props.onToggleProv,
            })
          }))
      })),
    // ④ 后续认识（试点只展示到当前认识）
    list(chain.next_beliefs).length ? h('div', null,
      h('div', { className: 'dsh-lit-section-head' }, h('h3', { className: 'dsh-lit-title' }, '后续认识（试点未展开）')),
      h('div', { className: 'dsh-lit-stack' }, list(chain.next_beliefs).map(function (item, index) {
        return h('div', { key: index, className: 'dsh-lit-evidence' },
          h('div', { className: 'dsh-lit-actions' },
            h('strong', { className: 'dsh-lit-content' }, String(item.statement || '')),
            h('span', { className: 'dsh-lit-mini' }, chainStatusLabel(item.status) || String(item.status || ''))),
          item.note ? h('div', { className: 'dsh-lit-muted' }, String(item.note)) : null)
      }))) : null,
    // ⑤ caveats 原样
    list(chain.caveats).length ? h('div', null,
      h('div', { className: 'dsh-lit-section-head' }, h('h3', { className: 'dsh-lit-title' }, '已知局限（原样展示）')),
      h('ul', { className: 'dsh-lit-chain-caveats' }, list(chain.caveats).map(function (text, index) {
        return h('li', { key: index }, chainRich(text))
      }))) : null,
    // ⑥ 生成前提：什么时候、用什么规则/模型/温度算出来的、是否人核（缺项不臆造）
    (function () {
      const meta = chain.generation || chain.pipeline || {}
      const parts = []
      const at = meta.generated_at || meta.created_at || chain.generated_at
      const rule = meta.candidate_rule || meta.rule_version || chain.candidate_rule
      const model = meta.model || meta.extract_model || chain.extract_model
      const temperature = meta.temperature != null ? meta.temperature : chain.temperature
      const verified = meta.verified_note || meta.verified || chain.verified_note
      if (at) parts.push('生成：' + String(at))
      if (rule) parts.push('候选规则 ' + String(rule))
      if (model) parts.push('抽取模型 ' + String(model))
      if (temperature != null && temperature !== '') parts.push('temperature ' + String(temperature))
      if (verified) parts.push('核验：' + String(verified))
      // generation.scope_note（如"基于 9 篇已抽取文献、17 篇逐篇判定"）也是前提的一部分
      const scopeNote = meta.scope_note || chain.scope_generation_note
      if (scopeNote) parts.push('范围 ' + String(scopeNote))
      return h('div', { className: 'dsh-lit-chain-genesis', title: '这条链的每个数字都有前提：候选规则版本 / 模型 / 温度 / 是否人工核验' },
        parts.length ? parts.join(' ｜ ') : '生成信息：数据未提供（缺 generation 字段：生成时间 / 候选规则 / 模型 / temperature / 核验状态）')
    })())
}
function ChainsView(props) {
  const resource = useResource(async function () { return fetchChains() }, [props.workspaceId])
  const [openMap, setOpenMap] = React.useState({})
  const [provMap, setProvMap] = React.useState({})
  const [alignedOpen, setAlignedOpen] = React.useState(false)   // 同向补充默认收起
  const data = resource.data
  const chains = list(data && data.chains)
  function toggleProv(key) {
    setProvMap(function (previous) { const next = Object.assign({}, previous); next[key] = !previous[key]; return next })
  }
  function toggle(key) {
    setOpenMap(function (previous) {
      const next = Object.assign({}, previous)
      next[key] = !previous[key]
      return next
    })
  }
  return h('div', { className: 'dsh-lit-stack', 'aria-busy': resource.loading },
    h('div', { className: 'dsh-lit-actions' },
      h('span', { className: 'dsh-lit-title' }, '🧭 认识演进 · 试点'),
      h('span', { className: 'dsh-lit-count' }, resource.loading ? '加载中…' : chains.length + ' 条链'),
      h(Button, { icon: 'refresh', title: '重新加载链数据', onClick: resource.reload, disabled: resource.loading })),
    resource.error ? h(Notice, { text: '链数据加载失败：' + message(resource.error), error: true, retry: resource.reload }) : null,
    data && data.error ? h(Notice, { text: '试点数据未加载：' + data.error, error: true, retry: resource.reload }) : null,
    !resource.loading && !chains.length
      ? h(Empty, null, '试点数据未加载（GET /chains 无数据或接口未就绪）—— 空态不是错误，补上数据文件即可显示')
      : null,
    chains.map(function (chain, index) {
      return h(ChainCard, {
        key: String(chain.chain_id || index), chain: chain, openMap: openMap, onToggle: toggle,
        provMap: provMap, onToggleProv: toggleProv,
        alignedOpen: alignedOpen, onToggleAligned: function () { setAlignedOpen(function (previous) { return !previous }) },
      })
    }))
}

function KnowledgeView(props) {
  const workspaceId = props.workspaceId
  const [library, setLibrary] = React.useState('')
  const [includeArchived, setIncludeArchived] = React.useState(false)
  const [openId, setOpenId] = React.useState(null)
  useLibraries()
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
      h(LibrarySelect, { value: library, onChange: setLibrary,
        extra: Array.from(new Set(items.map(function (item) { return item && item.library }).filter(function (code) { return code && !libraryKnown(code) }))).sort() }),
      h(ArchiveCheck, { value: includeArchived, onChange: setIncludeArchived }),
      h(Button, { icon: 'refresh', title: '刷新知识列表', onClick: function () { reloadLibraries(); resource.reload() }, disabled: resource.loading }),
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

// 岛群图谱：v3 的观感能力内联进插件自身——有机岛形轮廓 + 价值向心布局 + 放大细分 +
// 按边来源分线型 + 拖动高亮。数据只走既有的 api('/graph')，不再有独立页面 / 外链 / 公开目录。

// ── 边来源 → 线型（P4 口径：断言显眼、提示细淡） ──
const GRAPH_EDGE_STYLES = {
  support: { className: 'dsh-lit-graph-edge-support', label: '断言·支持（证据·暖色实线）' },
  contradict: { className: 'dsh-lit-graph-edge-contradict', label: '断言·反驳（证据·红虚线）' },
  context: { className: 'dsh-lit-graph-edge-context', label: '同源（证据·中性细线）' },
  synonym: { className: 'dsh-lit-graph-edge-synonym', label: '同义（证据·同名重复·灰虚线）' },
  extracted: { className: 'dsh-lit-graph-edge-extracted', label: '抽取（按关系着色）' },
  similarity: { className: 'dsh-lit-graph-edge-sim', label: '相似（向量·提示·细淡）' },
}
// 同一对节点上多条边时，只画最高优先级的一条：断言 > 抽取 > 同源/同义 > 相似
const GRAPH_EDGE_RANK = { contradict: 5, support: 4, extracted: 3, context: 2, synonym: 2, similarity: 1 }
function graphEdgeKind(edge) {
  const provenance = String(edge.provenance || edge.prov || 'similarity')
  const relation = String(edge.relation || '')
  if (provenance === 'evidence') {
    if (relation.indexOf('反驳') >= 0) return 'contradict'
    if (relation.indexOf('支持') >= 0) return 'support'
    if (relation.indexOf('同义') >= 0) return 'synonym'
    return 'context'
  }
  if (provenance === 'extracted') return 'extracted'
  return 'similarity'
}
function buildGraphLinks(edges) {
  const byPair = new Map()
  edges.forEach(function (edge) {
    const a = String(edge.source), b = String(edge.target)
    if (a === b) return
    const key = a < b ? a + '|' + b : b + '|' + a
    const kind = graphEdgeKind(edge)
    let link = byPair.get(key)
    if (!link) {
      link = { key: key, source: a, target: b, kind: kind, kinds: {}, relations: [], provenance: String(edge.provenance || 'similarity'), count: 0 }
      byPair.set(key, link)
    }
    link.count += 1
    link.kinds[kind] = (link.kinds[kind] || 0) + 1
    if (link.relations.indexOf(String(edge.relation || '')) < 0) link.relations.push(String(edge.relation || ''))
    if ((GRAPH_EDGE_RANK[kind] || 0) > (GRAPH_EDGE_RANK[link.kind] || 0)) { link.kind = kind; link.provenance = String(edge.provenance || 'similarity') }
  })
  return Array.from(byPair.values())
}

// ── 知识价值 → 半径：秩映射（非线性），ev_*/use_count/rating 未落地时按 0 兜底 ──
function graphNodeValue(node, degree) {
  const num = function (value) { const n = Number(value); return isFinite(n) ? n : 0 }
  return degree + (3 * num(node.ev_support) + 1.2 * num(node.ev_context) + 2 * num(node.ev_contradict))
    + 2 * num(node.use_count) + 4 * num(node.rating)
}
function graphValuePercents(list) {
  const sorted = list.slice().sort(function (a, b) { return a.value - b.value || String(a.id).localeCompare(String(b.id)) })
  const pct = new Map()
  sorted.forEach(function (item, index) {
    pct.set(String(item.id), Math.pow(sorted.length > 1 ? index / (sorted.length - 1) : .5, .85))
  })
  return pct
}

// ── 有机岛形：成员高斯核叠加成密度场 → marching squares 提等值线 → 二次平滑成闭合路径 ──
function graphIslandSigma(members, base, cap) {
  const count = members.length
  const sigma = new Map()
  if (!count) return function () { return base }
  if (count === 1) { sigma.set(members[0], base); return function (m) { return sigma.get(m) || base } }
  const inTree = new Uint8Array(count), dist = new Float64Array(count).fill(Infinity)
  const parent = new Int32Array(count).fill(-1), need = new Float64Array(count)
  dist[0] = 0
  for (let iter = 0; iter < count; iter += 1) {
    let u = -1
    for (let i = 0; i < count; i += 1) if (!inTree[i] && (u < 0 || dist[i] < dist[u])) u = i
    inTree[u] = 1
    if (parent[u] >= 0) {
      const half = Math.sqrt(dist[u]) / 3.3
      need[u] = Math.max(need[u], half); need[parent[u]] = Math.max(need[parent[u]], half)
    }
    for (let v = 0; v < count; v += 1) {
      if (inTree[v]) continue
      const dx = members[u].x - members[v].x, dy = members[u].y - members[v].y, d2 = dx * dx + dy * dy
      if (d2 < dist[v]) { dist[v] = d2; parent[v] = u }
    }
  }
  // σ 至少覆盖到 MST 邻居，保证一个岛 = 一块连通的陆地（不会碎成一堆小圆）
  members.forEach(function (m, i) { sigma.set(m, Math.min(cap, Math.max(base + (m.r || 8) * .9, need[i]))) })
  return function (m) { return sigma.get(m) || base }
}
function graphDensityField(members, sigmaOf, step) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity, sigmaMax = 0
  members.forEach(function (m) {
    const sigma = sigmaOf(m); sigmaMax = Math.max(sigmaMax, sigma)
    x0 = Math.min(x0, m.x); y0 = Math.min(y0, m.y); x1 = Math.max(x1, m.x); y1 = Math.max(y1, m.y)
  })
  const pad = sigmaMax * 2.6
  x0 -= pad; y0 -= pad; x1 += pad; y1 += pad
  const nx = Math.ceil((x1 - x0) / step) + 1, ny = Math.ceil((y1 - y0) / step) + 1
  const values = new Float32Array(nx * ny)
  members.forEach(function (m) {
    const sigma = sigmaOf(m), twoSigma2 = 2 * sigma * sigma, reach = sigma * 2.6
    const i0 = Math.max(0, Math.floor((m.x - reach - x0) / step)), i1 = Math.min(nx - 1, Math.ceil((m.x + reach - x0) / step))
    const j0 = Math.max(0, Math.floor((m.y - reach - y0) / step)), j1 = Math.min(ny - 1, Math.ceil((m.y + reach - y0) / step))
    for (let j = j0; j <= j1; j += 1) {
      const dy = y0 + j * step - m.y
      for (let i = i0; i <= i1; i += 1) {
        const dx = x0 + i * step - m.x
        values[j * nx + i] += Math.exp(-(dx * dx + dy * dy) / twoSigma2)
      }
    }
  })
  return { values: values, nx: nx, ny: ny, x0: x0, y0: y0, step: step }
}
function graphContour(field, threshold) {
  const values = field.values, nx = field.nx, ny = field.ny, x0 = field.x0, y0 = field.y0, step = field.step
  const points = new Map(), adjacency = new Map()
  function point(id) {
    let p = points.get(id)
    if (p) return p
    const cell = id >> 1, i = cell % nx, j = Math.floor(cell / nx)
    if (id & 1) {
      const a = values[cell], b = values[cell + nx], u = (threshold - a) / ((b - a) || 1e-9)
      p = [x0 + i * step, y0 + (j + u) * step]
    } else {
      const a = values[cell], b = values[cell + 1], u = (threshold - a) / ((b - a) || 1e-9)
      p = [x0 + (i + u) * step, y0 + j * step]
    }
    points.set(id, p); return p
  }
  function link(a, b) {
    point(a); point(b)
    if (!adjacency.has(a)) adjacency.set(a, [])
    if (!adjacency.has(b)) adjacency.set(b, [])
    adjacency.get(a).push(b); adjacency.get(b).push(a)
  }
  for (let j = 0; j < ny - 1; j += 1) {
    for (let i = 0; i < nx - 1; i += 1) {
      const cell = j * nx + i
      const a = values[cell], b = values[cell + 1], cc = values[cell + nx + 1], d = values[cell + nx]
      const code = (a > threshold ? 8 : 0) | (b > threshold ? 4 : 0) | (cc > threshold ? 2 : 0) | (d > threshold ? 1 : 0)
      if (code === 0 || code === 15) continue
      const top = cell * 2, bottom = (cell + nx) * 2, left = cell * 2 + 1, right = (cell + 1) * 2 + 1
      switch (code) {
        case 1: case 14: link(left, bottom); break
        case 2: case 13: link(bottom, right); break
        case 3: case 12: link(left, right); break
        case 4: case 11: link(top, right); break
        case 6: case 9: link(top, bottom); break
        case 7: case 8: link(left, top); break
        case 5:
          if ((a + b + cc + d) / 4 > threshold) { link(left, top); link(bottom, right) } else { link(top, right); link(left, bottom) }
          break
        case 10:
          if ((a + b + cc + d) / 4 > threshold) { link(top, right); link(left, bottom) } else { link(left, top); link(bottom, right) }
          break
        default: break
      }
    }
  }
  const seen = new Set(), loops = []
  adjacency.forEach(function (neighbors, start) {
    if (seen.has(start)) return
    const loop = []
    let previous = -1, current = start
    while (current !== undefined && !seen.has(current)) {
      seen.add(current); loop.push(points.get(current))
      const next = neighbors[0] !== previous ? neighbors[0] : neighbors[1]
      previous = current; current = next
      if (current !== undefined) neighbors = adjacency.get(current) || []
    }
    if (loop.length > 4) loops.push(loop)
  })
  // 去掉内环（湖）：岛是实心的
  return loops.filter(function (loop) {
    return !loops.some(function (other) { return other !== loop && other.length > loop.length && graphPointInPolygon(loop[0], other) })
  })
}
function graphPointInPolygon(point, polygon) {
  let inside = false
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
    const a = polygon[i], b = polygon[j]
    if ((a[1] > point[1]) !== (b[1] > point[1]) && point[0] < (b[0] - a[0]) * (point[1] - a[1]) / ((b[1] - a[1]) || 1e-9) + a[0]) inside = !inside
  }
  return inside
}
function graphLoopsPath(loops) {
  let path = ''
  loops.forEach(function (loop) {
    const count = loop.length
    function mid(i) { const a = loop[i % count], b = loop[(i + 1) % count]; return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] }
    const first = mid(0)
    path += 'M' + first[0].toFixed(1) + ',' + first[1].toFixed(1)
    for (let i = 1; i <= count; i += 1) {
      const p = loop[i % count], m = mid(i)
      path += 'Q' + p[0].toFixed(1) + ',' + p[1].toFixed(1) + ' ' + m[0].toFixed(1) + ',' + m[1].toFixed(1)
    }
    path += 'Z'
  })
  return path
}
function graphIslandShape(members, options) {
  const opts = options || {}
  if (!members.length) return null
  const sigmaOf = graphIslandSigma(members, opts.base || 24, opts.cap || 96)
  const field = graphDensityField(members, sigmaOf, opts.step || 7)
  const loops = graphContour(field, opts.threshold || .3)
  if (!loops.length) return null
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
  loops.forEach(function (loop) {
    loop.forEach(function (p) {
      x0 = Math.min(x0, p[0]); y0 = Math.min(y0, p[1]); x1 = Math.max(x1, p[0]); y1 = Math.max(y1, p[1])
    })
  })
  return { path: graphLoopsPath(loops), cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, r: Math.max(x1 - x0, y1 - y0) / 2 }
}
// 岛内细分用的社区发现：多层级 Louvain（带分辨率 γ），确定性洗牌保证刷新稳定
function graphLouvain(members, adjacency, gamma, seed) {
  let random = seed == null ? 7 : seed
  function nextRandom() { random = (random * 1664525 + 1013904223) >>> 0; return random / 4294967296 }
  const ids = members.slice()
  let graph = new Map()
  ids.forEach(function (id) {
    const inner = new Map()
    const source = adjacency.get(id) || new Map()
    source.forEach(function (weight, other) { if (other !== id) inner.set(other, weight) })
    graph.set(id, inner)
  })
  let levelMembers = new Map(ids.map(function (id) { return [id, [id]] }))
  for (let level = 0; level < 12; level += 1) {
    let total = 0
    graph.forEach(function (inner) { inner.forEach(function (weight) { total += weight }) })
    if (!total) break
    const degree = new Map()
    graph.forEach(function (inner, id) { let sum = 0; inner.forEach(function (weight) { sum += weight }); degree.set(id, sum) })
    const community = new Map(Array.from(graph.keys()).map(function (id) { return [id, id] }))
    const totals = new Map(degree)
    let improved = false
    for (let pass = 0; pass < 40; pass += 1) {
      let moved = false
      const order = Array.from(graph.keys())
      for (let i = order.length - 1; i > 0; i -= 1) { const j = Math.floor(nextRandom() * (i + 1)); const t = order[i]; order[i] = order[j]; order[j] = t }
      order.forEach(function (id) {
        const mine = community.get(id)
        totals.set(mine, (totals.get(mine) || 0) - degree.get(id))
        const weights = new Map()
        graph.get(id).forEach(function (weight, other) { const c = community.get(other); weights.set(c, (weights.get(c) || 0) + weight) })
        let best = mine, bestGain = (weights.get(mine) || 0) - gamma * (totals.get(mine) || 0) * degree.get(id) / total
        weights.forEach(function (weight, c) {
          const gain = weight - gamma * (totals.get(c) || 0) * degree.get(id) / total
          if (gain > bestGain + 1e-12) { best = c; bestGain = gain }
        })
        totals.set(best, (totals.get(best) || 0) + degree.get(id))
        if (best !== mine) { community.set(id, best); moved = true; improved = true }
      })
      if (!moved) break
    }
    if (!improved) break
    const merged = new Map()
    graph.forEach(function (inner, id) {
      const c = community.get(id)
      if (!merged.has(c)) merged.set(c, { members: [], edges: new Map() })
      const target = merged.get(c)
      target.members = target.members.concat(levelMembers.get(id) || [id])
      inner.forEach(function (weight, other) {
        const oc = community.get(other)
        target.edges.set(oc, (target.edges.get(oc) || 0) + weight)
      })
    })
    const nextGraph = new Map(), nextMembers = new Map()
    merged.forEach(function (value, c) { nextGraph.set(c, value.edges); nextMembers.set(c, value.members) })
    graph = nextGraph
    levelMembers = nextMembers
    if (graph.size <= 1) break
  }
  const out = new Map()
  let index = 0
  Array.from(levelMembers.keys()).sort(function (a, b) { return (levelMembers.get(b).length - levelMembers.get(a).length) || String(a).localeCompare(String(b)) })
    .forEach(function (c) {
      levelMembers.get(c).forEach(function (id) { out.set(id, index) })
      index += 1
    })
  return out
}
// 放大细分：岛内跑一次 Louvain（γ=1.2），得到 L1 子岛
function buildGraphSubIslands(nodes, edges, communities) {
  const nodeMap = new Map(nodes.map(function (node) { return [String(node.id), node] }))
  const adjacency = new Map()
  communities.themes.forEach(function (theme) { theme.members.forEach(function (id) { adjacency.set(id, new Map()) }) })
  edges.forEach(function (edge) {
    const a = String(edge.source), b = String(edge.target)
    if (a === b || !adjacency.has(a) || !adjacency.has(b)) return
    if (communities.byNode.get(a) !== communities.byNode.get(b)) return
    adjacency.get(a).set(b, (adjacency.get(a).get(b) || 0) + 1)
    adjacency.get(b).set(a, (adjacency.get(b).get(a) || 0) + 1)
  })
  const subdivisions = new Map()
  communities.themes.forEach(function (theme) {
    if (theme.members.length < 8) return
    const partition = graphLouvain(theme.members, adjacency, 1.2, 7)
    const groups = new Map()
    theme.members.forEach(function (id) {
      const key = partition.get(id) || 0
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key).push(id)
    })
    if (groups.size < 2) return
    const ordered = Array.from(groups.values()).sort(function (a, b) { return b.length - a.length || String(a[0]).localeCompare(String(b[0])) })
    // 子岛数量封顶（≤5）：多出来的小簇并进最大簇，保证布局的扇区与绘制轮廓用的是同一套分区
    const cap = Math.max(2, Math.min(5, Math.floor(theme.members.length / 12)))
    const kept = ordered.slice(0, cap)
    const rest = ordered.slice(cap).reduce(function (all, members) { return all.concat(members) }, [])
    if (rest.length) kept[0] = kept[0].concat(rest)
    const subThemes = kept.map(function (members, index) {
      const representative = members.slice().sort(function (a, b) {
        return (adjacency.get(b) ? adjacency.get(b).size : 0) - (adjacency.get(a) ? adjacency.get(a).size : 0) || String(a).localeCompare(String(b))
      })[0]
      const node = nodeMap.get(String(representative))
      return { id: theme.id + '.' + index, members: members, representative: representative,
        name: String((node && node.concept) || '细分 ' + (index + 1)), color: theme.color }
    })
    const byNode = new Map()
    subThemes.forEach(function (sub) { sub.members.forEach(function (id) { byNode.set(id, sub) }) })
    subdivisions.set(theme.id, { themes: subThemes, byNode: byNode })
  })
  return subdivisions
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
  const [dragId, setDragId] = React.useState(null)
  const [expandedEvidence, setExpandedEvidence] = React.useState({})
  useLibraries()          // 库列表接口回来后重渲染（图例/筛选/着色都跟着变）
  const fitK = React.useRef(1)
  const groupRef = React.useRef(null)
  const touched = React.useRef(false)   // 用户手动缩放/平移过 ⇒ 不自动重新 fit
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
  // 可视区（viewBox）：高度固定 = 世界高，宽度按容器宽高比伸缩，并以世界中心为中心。
  // 这样 <svg viewBox> 的宽高比 = 容器宽高比，xMidYMid meet 不再产生左右留白。
  const viewW = Math.round(H * Math.max(0.6, Math.min(3.2, ((size.width || 1080) || 1) / Math.max(160, (size.height || 800)))))
  const viewH = H
  const communities = React.useMemo(function () { return buildGraphThemes(nodes, edges) }, [resource.data])
  // 价值 = 去重关系数 + 证据加权 + 使用/评分（ev_*/use_count/rating 未就绪时按 0 兜底）
  const degrees = React.useMemo(function () {
    const out = {}
    edges.forEach(function (edge) {
      const source = String(edge.source), target = String(edge.target)
      out[source] = (out[source] || 0) + 1; out[target] = (out[target] || 0) + 1
    })
    return out
  }, [resource.data])
  const values = React.useMemo(function () {
    const raw = nodes.map(function (node) { return { id: node.id, value: graphNodeValue(node, degrees[String(node.id)] || 0) } })
    const percents = graphValuePercents(raw)
    const out = {}
    raw.forEach(function (item) { out[String(item.id)] = { value: item.value, pct: percents.get(String(item.id)) || 0, r: 7.5 + 15.5 * (percents.get(String(item.id)) || 0) } })
    return out
  }, [resource.data, degrees])
  // 岛内细分（放大后出现的子岛）：先算分区，布局阶段就按子岛分扇区，保证子岛不重叠
  const subdivisions = React.useMemo(function () { return buildGraphSubIslands(nodes, edges, communities) }, [communities])
  // 容器宽高比：用「不含预览栏」的宽度（侧栏开合时布局不重排，只是重新 fit）；量化到 0.2 避免抖
  const layoutAspect = React.useMemo(function () {
    const vpW = (size.width || 1080) + (selNode ? 352 : 0)
    const vpH = size.height || 800
    const raw = (vpW - 36) / Math.max(120, vpH - 36)      // 去掉 18px 边距后的可用区宽高比
    return Math.round(Math.max(0.7, Math.min(3, raw)) * 10) / 10
  }, [size.width, size.height, selNode ? 1 : 0])
  const layout = React.useMemo(function () {
    const numericValues = {}, numericRadii = {}
    Object.keys(values).forEach(function (id) { numericValues[id] = values[id].value; numericRadii[id] = values[id].r })
    return buildGraphLayout(nodes, edges, WORLD_W, WORLD_H, seed, communities,
      fullscreen ? { top: 140, bottom: 120 } : null, numericValues, numericRadii, subdivisions, layoutAspect)
  }, [communities, seed, fullscreen, values, subdivisions, layoutAspect])
  // 岛轮廓（有机形状）
  const shapes = React.useMemo(function () {
    const positions = layout.positions || {}
    const nodeMap = new Map(nodes.map(function (node) { return [String(node.id), node] }))
    const islandByTheme = new Map((layout.islands || []).map(function (island) { return [String(island.theme.id), island] }))
    function pack(theme, level, parentId, color) {
      const members = theme.members.map(function (id) { return positions[id] }).filter(Boolean)
      if (!members.length) return null
      let options
      if (level === 0) {
        const island = islandByTheme.get(String(theme.id))
        options = { base: (island && island.sigmaBase) || 26, cap: (island && island.sigmaCap) || 104, step: 7, threshold: .3 }
      } else {
        // 子岛的 σ 跟着自身尺度走（与父岛同样的比例），否则缩小后轮廓会互相压住
        let centreX = 0, centreY = 0
        members.forEach(function (m) { centreX += m.x; centreY += m.y })
        centreX /= members.length; centreY /= members.length
        let spread = 1
        members.forEach(function (m) { spread = Math.max(spread, Math.hypot(m.x - centreX, m.y - centreY) + m.r) })
        options = { base: Math.max(8, spread * 0.16), cap: Math.max(28, spread * 0.5), step: 5, threshold: .34 }
      }
      const shape = graphIslandShape(members, options)
      if (!shape) return null
      const node = nodeMap.get(String(theme.representative)) || nodeMap.get(String(theme.members[0]))
      return { id: String(theme.id), parent: parentId == null ? null : String(parentId), level: level, color: color,
        path: shape.path, cx: shape.cx, cy: shape.cy, r: shape.r, count: theme.members.length,
        name: String((node && node.concept) || '主题') }
    }
    const level0 = communities.themes.map(function (theme) { return pack(theme, 0, null, theme.color) }).filter(Boolean)
    const level1 = []
    subdivisions.forEach(function (inner, themeId) {
      const parent = communities.themes.find(function (theme) { return String(theme.id) === String(themeId) })
      inner.themes.forEach(function (sub) { const shape = pack(sub, 1, themeId, (parent && parent.color) || '#5b6673'); if (shape) level1.push(shape) })
    })
    return { level0: level0, level1: level1 }
  }, [layout, communities, subdivisions])
  const links = React.useMemo(function () { return buildGraphLinks(edges) }, [resource.data])
  const linkCounts = React.useMemo(function () {
    const counts = { similarity: 0, support: 0, contradict: 0, context: 0, synonym: 0, extracted: 0 }
    links.forEach(function (link) { counts[link.kind] = (counts[link.kind] || 0) + 1 })
    return counts
  }, [links])
  function contentBox() {
    // 真实内容外接盒：<g> 的 getBBox() 是世界坐标下的几何外接盒（含岛轮廓曲线、文字），
    // 不含该 <g> 自身的平移/缩放 ⇒ 与当前 tf 无关，可直接用来算 fit。
    const group = groupRef.current
    if (group && typeof group.getBBox === 'function') {
      try {
        const box = group.getBBox()
        if (box && box.width > 0 && box.height > 0) return box
      } catch (error) { /* jsdom 之类没有 getBBox 的宿主走下面的兜底 */ }
    }
    // 兜底：节点圆 + 半径余量
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    Object.keys(layout.positions || {}).forEach(function (id) {
      const p = layout.positions[id]; if (!p) return
      const r = (p.r || 9) + 12
      minX = Math.min(minX, p.x - r); minY = Math.min(minY, p.y - r)
      maxX = Math.max(maxX, p.x + r); maxY = Math.max(maxY, p.y + r)
    })
    if (!isFinite(minX)) return null
    return { x: minX, y: minY, width: Math.max(1, maxX - minX), height: Math.max(1, maxY - minY) }
  }
  function fitContent() {
    // 自动 fit + 居中：tf 平移在 viewBox 用户坐标系里；viewBox 的宽高比 = 容器宽高比
    // （见 viewBox 计算）⇒ 没有 letterbox，可见区中心恒为 (W/2,H/2)。
    // v15：改用「真实渲染外接盒」（含岛轮廓与控制点、文字），并按屏幕 18px 边距留白，
    // 不再用节点 bbox × 0.88 的经验系数——那正是"只用了 60%、看着靠左"的根因。
    const svg = svgRef.current
    const rect = svg ? svg.getBoundingClientRect() : null
    const vpW = (rect && rect.width) || size.width || 1080
    const vpH = (rect && rect.height) || size.height || 800
    const box = contentBox()
    if (!box) { setTf({ k: 0.27, x: W / 2, y: H / 2 }); return }
    const pxPerUnit = Math.min(vpW / viewW, vpH / viewH) || 0.27   // viewBox → 屏幕比例（无 letterbox）
    const visibleW = Math.min(viewW, vpW / pxPerUnit), visibleH = Math.min(viewH, vpH / pxPerUnit)
    const padUser = 18 / pxPerUnit                            // 屏幕 18px 边距 → 用户单位
    const fitW = Math.max(40, visibleW - padUser * 2), fitH = Math.max(40, visibleH - padUser * 2)
    const k = Math.max(0.12, Math.min(8, Math.min(fitW / box.width, fitH / box.height)))
    const cx = box.x + box.width / 2, cy = box.y + box.height / 2
    fitK.current = k          // 相对缩放基准：岛内细分按 k / fitK 出现
    touched.current = false   // 重新 fit = 回到自动视图
    setTf({ k: k, x: W / 2 - cx * k, y: H / 2 - cy * k })
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
  // 容器宽度变化（窗口 resize / 侧栏开合）→ 自动重新 fit 到新容器；用户接管过视图就不动
  React.useEffect(function () {
    if (touched.current) return
    fitContent()
  }, [size.width, size.height])
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
      touched.current = true
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
    setDragId(node ? String(node.id) : null)
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
    } else { touched.current = true; setTf({ k: drag.k, x: drag.x + dx, y: drag.y + dy }) }
  }

  function finish(event, cancelled) {
    const drag = gesture.current
    if (!drag || drag.pointerId !== event.pointerId) return
    gesture.current = null
    setDragId(null)
    const svg = svgRef.current
    if (svg && svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId)
    if (!cancelled && !drag.moved) {
      // v15：点节点 = 右侧快速预览（不再直接跳全屏详情）；全屏详情走预览栏里的按钮
      if (drag.node) setSelNode(drag.node)
      else if (selNode) setSelNode(null)          // 点空白 = 收起预览，图谱恢复全宽
    }
  }

  function zoom(factor) {
    touched.current = true
    setTf(function (previous) {
      const k = Math.max(0.12, Math.min(8, previous.k * factor))
      return { k: k, x: W / 2 - (W / 2 - previous.x) * k / previous.k, y: H / 2 - (H / 2 - previous.y) * k / previous.k }
    })
  }

  function reset() { setOverrides({}); setSeed(function (value) { return value + 1 }) }
  // 快速预览：当前选中节点的价值/证据/一跳邻居（数据全部来自同一条 /graph，无新增请求）
  const previewId = selNode ? String(selNode.id) : ''
  const previewLinks = previewId ? links.filter(function (link) { return link.source === previewId || link.target === previewId }) : []
  const previewNeighbors = previewLinks.map(function (link) {
    const otherId = link.source === previewId ? link.target : link.source
    const other = nodes.find(function (node) { return String(node.id) === otherId })
    return other ? { node: other, link: link } : null
  }).filter(Boolean).sort(function (a, b) {
    return (values[String(b.node.id)] ? values[String(b.node.id)].value : 0) - (values[String(a.node.id)] ? values[String(a.node.id)].value : 0)
  })
  // 逐条证据：P18 的 /knowledge/<id>/evidence，一次拿全（max_chars=0 不截断，前端折叠）
  const evidenceRes = useResource(async function () {
    if (!previewId) return null
    return fetchKnowledgeEvidence(previewId, props.workspaceId)
  }, [previewId, props.workspaceId])
  const evidenceItems = evidenceRes.data ? evidenceRes.data.items : []
  const nodeEvidenceCount = selNode
    ? (Number(selNode.ev_support) || 0) + (Number(selNode.ev_contradict) || 0) + (Number(selNode.ev_context) || 0)
    : 0
  const evidenceMismatch = !!evidenceRes.data && evidenceItems.length !== nodeEvidenceCount
  React.useEffect(function () {
    // 预览栏开合会改变图谱列宽：等 grid 重排后用 rAF 重新 fit（复用同一套 fit 逻辑）
    const frame = typeof requestAnimationFrame === 'function' ? requestAnimationFrame(function () { fitContent() }) : null
    return function () { if (frame && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(frame) }
  }, [previewId])
  // 拖动/悬停高亮：一跳邻居与相连边突出，其余淡化
  const active = dragId || hover
  const neighbors = new Set(active == null ? [] : [active])
  edges.forEach(function (edge) {
    const source = String(edge.source), target = String(edge.target)
    if (source === active) neighbors.add(target)
    if (target === active) neighbors.add(source)
  })
  const degree = degrees
  const counts = {}
  nodes.forEach(function (node) {
    // 按「接口返回的 code 集合」判存在；接口没返回的 code 原样成行（不再一律塞进 unknown）
    const library = node.library == null || node.library === '' ? 'unknown' : String(node.library)
    counts[library] = (counts[library] || 0) + 1
  })
  const extraLibraries = Object.keys(counts).filter(function (code) { return code !== 'unknown' && !libraryKnown(code) }).sort()
  const legendLibraries = libraryCodes().filter(function (code) { return counts[code] })
  Object.keys(counts).sort().forEach(function (code) { if (code !== 'unknown' && legendLibraries.indexOf(code) < 0) legendLibraries.push(code) })
  if (counts.unknown) legendLibraries.push('unknown')
  // 相对缩放：过阈值后岛内子岛交叉淡入；放大后只在视野中心那座岛里保留细分
  const zrel = fitK.current > 0 ? tf.k / fitK.current : 1
  const subOpacity = Math.max(0, Math.min(1, (zrel - 1.45) / 1.15))
  const viewCenter = { x: (W / 2 - tf.x) / (tf.k || 1), y: (H / 2 - tf.y) / (tf.k || 1) }
  let focusIsland = null
  if (subOpacity > 0 && shapes.level0.length) {
    let best = Infinity
    shapes.level0.forEach(function (shape) {
      const distance = Math.hypot(shape.cx - viewCenter.x, shape.cy - viewCenter.y)
      if (distance < best) { best = distance; focusIsland = shape }
    })
  }

  if (detailId != null) return h(KnowledgeDetail, { key: detailId, kid: detailId, workspaceId: props.workspaceId, backLabel: '返回图谱', onBack: function () { setDetailId(null) } })

  return h('div', { className: 'dsh-lit-stack', 'aria-busy': resource.loading },
    h('div', { className: 'dsh-lit-actions' },
      h(LibrarySelect, { value: library, onChange: setLibrary, extra: extraLibraries }),
      h(Button, { icon: 'refresh', title: '刷新图谱（含库列表）', onClick: function () { reloadLibraries(); resource.reload() }, disabled: resource.loading }),
      h(Button, { icon: 'reset', title: '重排并重置视图', onClick: reset, disabled: !nodes.length }),
      h(Button, { icon: 'zoomOut', title: '缩小', onClick: function () { zoom(1 / 1.25) }, disabled: tf.k <= 0.12 }),
      h('span', { className: 'dsh-lit-mini', style: { minWidth: 44, justifyContent: 'center' } }, Math.round(tf.k * 100) + '%'),
      h(Button, { icon: 'zoomIn', title: '放大', onClick: function () { zoom(1.25) }, disabled: tf.k >= 8 }),
      h('span', { className: 'dsh-lit-count' }, nodes.length + ' 节点 · ' + links.length + ' 连线 · ' + shapes.level0.length + ' 岛')),
    h(Notice, { text: resource.error, error: true, retry: resource.reload }),
    h('div', { className: 'dsh-lit-graph-legend', 'aria-label': '知识库图例' },
      legendLibraries.map(function (library) {
        return h('span', { key: library, className: 'dsh-lit-graph-key', title: library === 'unknown' ? '未分类' : library },
          h('i', { className: 'dsh-lit-graph-dot', style: { background: libraryColor(library) }, 'aria-hidden': true }),
          libraryDisplayLabel(library) + ' ' + (counts[library] || 0))
      })),
    h('div', { className: 'dsh-lit-graph-legend', 'aria-label': '关系线型图例' },
      ['support', 'contradict', 'context', 'synonym', 'similarity', 'extracted'].map(function (kind) {
        const style = GRAPH_EDGE_STYLES[kind]
        return h('span', { key: kind, className: 'dsh-lit-graph-key', title: style.label },
          h('svg', { className: 'dsh-lit-graph-key-line', viewBox: '0 0 26 10', 'aria-hidden': true },
            h('line', { x1: 1, y1: 5, x2: 25, y2: 5, className: 'dsh-lit-graph-edge ' + style.className })),
          style.label.split('（')[0] + ' ' + (linkCounts[kind] || 0))
      }),
      h('span', { className: 'dsh-lit-count' }, zrel < 1.45 ? '放大到 ' + Math.round(1.45 * 100) + '% 看岛内细分' : '岛内细分：' + shapes.level1.length + ' 块')),
    h('div', { className: 'dsh-lit-graphbox' + (selNode ? ' dsh-lit-graphbox-preview' : '') },
      h('div', { className: 'dsh-lit-graph-stage' },
        h('svg', {
          ref: svgRef, className: 'dsh-lit-graph-svg', role: 'group', 'aria-label': '知识概念关系图',
          viewBox: (W / 2 - viewW / 2) + ' ' + (H / 2 - viewH / 2) + ' ' + viewW + ' ' + viewH,
          onPointerDown: function (event) { start(event, null) }, onPointerMove: move,
          onPointerUp: function (event) { finish(event, false) }, onPointerCancel: function (event) { finish(event, true) },
          onLostPointerCapture: function () { gesture.current = null; setDragId(null) },
        }, h('g', { ref: groupRef, transform: 'translate(' + tf.x + ',' + tf.y + ') scale(' + tf.k + ')' },
          h('g', { className: 'dsh-lit-graph-islands', 'aria-hidden': true },
            shapes.level0.map(function (shape) {
              const dim = focusIsland && shape.id !== focusIsland.id ? Math.max(.25, 1 - subOpacity * .7) : 1
              return h('path', { key: 'i0-' + shape.id, className: 'dsh-lit-graph-island dsh-lit-graph-island-l0',
                d: shape.path, fill: shape.color, stroke: shape.color, opacity: dim })
            }),
            shapes.level1.map(function (shape) {
              const inFocus = !focusIsland || shape.parent === focusIsland.id
              return h('path', { key: 'i1-' + shape.id, className: 'dsh-lit-graph-island dsh-lit-graph-island-l1',
                d: shape.path, fill: shape.color, stroke: shape.color, opacity: inFocus ? subOpacity : 0 })
            }),
            shapes.level0.filter(function (shape) { return shape.count > 2 }).map(function (shape) {
              const dim = focusIsland && shape.id !== focusIsland.id ? .3 : 1
              return h('text', { key: 'il-' + shape.id, className: 'dsh-lit-graph-island-name', x: shape.cx, y: shape.cy - shape.r - 5,
                textAnchor: 'middle', opacity: dim }, short(shape.name, 16) + ' · ' + shape.count)
            })),
          links.map(function (link) {
            const a = pos(link.source), b = pos(link.target)
            if (!a || !b) return null
            const style = GRAPH_EDGE_STYLES[link.kind] || GRAPH_EDGE_STYLES.similarity
            const hot = active == null || link.source === active || link.target === active
            const emphasis = active != null && hot ? { strokeWidth: 3.4, strokeOpacity: 1 } : null
            return h('line', { key: 'e' + link.key, className: 'dsh-lit-graph-edge ' + style.className + (hot ? '' : ' dsh-lit-graph-edge-dim'),
              x1: a.x, y1: a.y, x2: b.x, y2: b.y, style: emphasis || undefined,
              strokeWidth: link.kind === 'similarity' && !emphasis ? 1.4 : undefined },
              h('title', null, (a.concept || link.source) + ' → ' + link.relations.join('/') + ' → ' + (b.concept || link.target)
                + (link.count > 1 ? '（' + link.count + ' 条）' : '')))
          }),
          nodes.map(function (node) {
            const point = pos(node.id)
            if (!point) return null
            const selected = selNode && String(selNode.id) === String(node.id)
            const hot = active === String(node.id) || selected
            const info = values[String(node.id)]
            const evidence = (Number(node.ev_support) || 0) + (Number(node.ev_context) || 0) + (Number(node.ev_contradict) || 0)
            return h('g', {
              key: 'n' + node.id, className: 'dsh-lit-graph-node', 'data-node-id': String(node.id),
              tabIndex: 0, role: 'button', 'aria-label': node.concept || String(node.id), 'aria-pressed': !!selected,
              opacity: active != null && !neighbors.has(String(node.id)) ? 0.25 : 1,
              onPointerDown: function (event) { start(event, node) },
              onClick: function () { setSelNode(node) },
              onPointerEnter: function () { setHover(String(node.id)) }, onPointerLeave: function () { setHover(null) },
              onFocus: function () { setHover(String(node.id)) }, onBlur: function () { setHover(null) },
              onKeyDown: function (event) {
                if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelNode(node) }
              },
            },
              h('title', null, (node.concept || node.id) + ' · ' + libraryDisplayLabel(node.library) + ' · ' + (degree[String(node.id)] || 0) + ' 关系'
                + ' · 价值 ' + (info ? info.value.toFixed(1) : '—') + (evidence ? ' · 证据 ' + evidence : '')
                + (node.summary ? '\n' + short(node.summary, 140) : '')),
              h('circle', { cx: point.x, cy: point.y, r: point.r, fill: libraryColor(node.library),
                stroke: hot ? 'var(--dsw-alias-label-primary)' : 'var(--dsw-alias-bg-layer-1)', strokeWidth: hot ? 2.5 : 1 }),
              h('text', { x: point.x, y: point.y + point.r + 14, className: 'dsh-lit-graph-label', textAnchor: 'middle' }, short(node.concept || node.id, 22)))
          }))),
        resource.loading || !nodes.length ? h('div', { className: 'dsh-lit-graph-overlay', role: 'status' },
          resource.loading ? '加载图谱…' : resource.error ? '图谱加载失败' : '暂无匹配的图谱节点') : null),
      selNode ? h('aside', { className: 'dsh-lit-graph-preview', 'aria-label': '知识快速预览' },
        h('div', { className: 'dsh-lit-preview-head' },
          h('div', { className: 'dsh-lit-content' },
            h('h2', { className: 'dsh-lit-preview-title' }, selNode.concept || '无概念名'),
            h('div', { className: 'dsh-lit-preview-sub' }, '知识 #' + selNode.id + ' · ' + libraryDisplayLabel(selNode.library))),
          h(Button, { icon: 'close', title: '收起预览（图谱恢复全宽）', onClick: function () { setSelNode(null) } })),
        h('div', { className: 'dsh-lit-preview-chips' },
          h('span', null, '价值 ' + (values[previewId] ? values[previewId].value.toFixed(1) : '—')),
          h('span', null, '连接 ' + (degree[previewId] || 0)),
          Number(selNode.rating) ? h('span', null, '评分 ' + selNode.rating) : null,
          Number(selNode.use_count) ? h('span', null, '使用 ' + selNode.use_count) : null),
        selNode.summary ? h('p', { className: 'dsh-lit-text' }, selNode.summary) : h('div', { className: 'dsh-lit-muted' }, '（无摘要）'),
        h('div', { className: 'dsh-lit-preview-section' }, '证据'),
        h('div', { className: 'dsh-lit-preview-chips' },
          h('span', null, '支持 ' + (Number(selNode.ev_support) || 0)),
          h('span', null, '反驳 ' + (Number(selNode.ev_contradict) || 0)),
          h('span', null, '背景 ' + (Number(selNode.ev_context) || 0))),
        // 逐条证据走 P18 的 /knowledge/<id>/evidence（见下方 evidenceRes）；字段名以详情返回的 `sources` 为准
        // （P18 另加了等价别名 evidence_ids）。
        (Number(selNode.ev_support) || 0) + (Number(selNode.ev_contradict) || 0) + (Number(selNode.ev_context) || 0)
          ? null : h('div', { className: 'dsh-lit-muted' }, '该节点暂无证据计数（若服务端未重启，ev_* 字段会缺省为 0）'),
        h('div', { className: 'dsh-lit-preview-section' }, '证据明细' + (evidenceRes.data ? ' · ' + evidenceItems.length + ' 条' : '')),
        evidenceRes.loading ? h('div', { className: 'dsh-lit-muted' }, '加载证据…')
          : evidenceRes.error ? h('div', { className: 'dsh-lit-preview-warn' }, '证据接口不可用：' + evidenceRes.error + '（概念/摘要/邻居不受影响；404 常见于服务端未重启）')
            : evidenceMismatch ? h('div', { className: 'dsh-lit-preview-warn' },
              '接口返回 ' + evidenceItems.length + ' 条 ≠ 节点计数 ' + nodeEvidenceCount + ' 条（ev_* 口径不一致，值得排查）')
              : null,
        evidenceItems.length ? h('ul', { className: 'dsh-lit-preview-evs' },
          evidenceItems.map(function (ev) {
            const stance = STANCE[ev.stance] ? ev.stance : 'contextual'
            const text = String(ev.evidence_text == null ? '' : ev.evidence_text)
            const open = !!expandedEvidence[String(ev.id)]
            const clip = 220
            return h('li', { key: 'ev' + ev.id, className: 'dsh-lit-preview-ev' },
              h('div', { className: 'dsh-lit-preview-ev-head' },
                h('span', { className: 'dsh-lit-mini dsh-lit-stance-' + stance }, STANCE[ev.stance] || ev.stance || STANCE.contextual),
                ev.confidence != null ? h('span', { className: 'dsh-lit-muted' }, '置信 ' + Math.round(Number(ev.confidence) * 100) + '%') : null,
                ev.chapter_anchor ? h('span', { className: 'dsh-lit-muted' }, '章节 ' + String(ev.chapter_anchor)) : null,
                ev.page != null && ev.page !== '' ? h('span', { className: 'dsh-lit-muted' }, '页 ' + String(ev.page)) : null),
              h('div', { className: 'dsh-lit-preview-ev-claim' }, ev.claim || '（无 claim）'),
              text ? h('div', { className: 'dsh-lit-preview-ev-text' }, open || text.length <= clip ? text : text.slice(0, clip) + '…') : null,
              text.length > clip ? h('button', {
                type: 'button', className: 'dsh-lit-preview-more',
                onClick: function () { setExpandedEvidence(function (previous) { const next = Object.assign({}, previous); next[String(ev.id)] = !previous[String(ev.id)]; return next }) },
              }, open ? '收起' : '展开全文（' + text.length + ' 字）') : null,
              ev.doc_id ? h('div', { className: 'dsh-lit-muted' }, '文档 #' + ev.doc_id) : null)
          })) : (!evidenceRes.loading && !evidenceRes.error ? h('div', { className: 'dsh-lit-muted' }, '该节点暂无关联证据') : null),
        h('div', { className: 'dsh-lit-preview-section' }, '一跳邻居 · ' + previewNeighbors.length),
        previewNeighbors.length ? h('ul', { className: 'dsh-lit-preview-list' },
          previewNeighbors.slice(0, 40).map(function (item) {
            const style = GRAPH_EDGE_STYLES[item.link.kind] || GRAPH_EDGE_STYLES.similarity
            return h('li', { key: item.link.key },
              h('button', {
                type: 'button', className: 'dsh-lit-preview-item', title: style.label,
                onClick: function () { setSelNode(item.node); centerOn(item.node, 1.6) },
              },
                h('i', { className: 'dsh-lit-graph-dot', style: { background: libraryColor(item.node.library) }, 'aria-hidden': true }),
                h('span', { className: 't' }, item.node.concept || String(item.node.id)),
                h('span', { className: 'k' }, style.label.split('（')[0])))
            })
          ) : h('div', { className: 'dsh-lit-muted' }, '该节点没有显式关系'),
        h(Button, { icon: 'open', className: 'dsh-lit-btn-primary', onClick: function () { openDetail(selNode) } }, '打开完整详情')) : null))
}

function StatusView(props) {
  useLibraries()
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
    kbIds.map(function (key) { return libraryDisplayLabel(key) + ' ' + Number(kb[key].total || 0) }).join(' · ') || '暂无库数据',
  ] : [], data && data.kb.error))
  const active = list(data && data.active.value && data.active.value.items)
  const archived = list(data && data.archived.value && data.archived.value.items)
  const perLibrary = {}
  active.forEach(function (item) { perLibrary[item.library] = (perLibrary[item.library] || 0) + 1 })
  const count = data && data.count.value && data.count.value.count
  cards.push(card('本库知识', count == null ? '—' : count + ' 条', data ? [
    data.active.error ? '分库计数不可用' : (active.length >= 1000 ? '已载入：' : '') + libraryCodes().map(function (library) { return libraryDisplayLabel(library) + ' ' + (perLibrary[library] || 0) }).join(' · '),
    data.archived.error ? '归档计数不可用' : '另归档 ' + (archived.length >= 1000 ? '至少 ' : '') + archived.length + ' 条',
  ] : [], data && [data.count.error, data.active.error, data.archived.error].filter(Boolean).join('；')))
  const graph = data && data.graph.value && data.graph.value.graph || {}
  cards.push(card('图谱规模', list(graph.nodes).length + ' 节点', data ? [
    list(graph.edges).length + ' 条关系',
    libraryCodes().map(function (library) { return libraryDisplayLabel(library) + ' ' + list(graph.nodes).filter(function (node) { return node.library === library }).length }).join(' · '),
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

// ── 技能管理视图（skill 管理体系 v0.2：登记 / 版本 / 审核状态 / 使用统计 / 全局发布）
const SCOPE_LABEL = { workspace: '私有', global: '全局' }
const LIFECYCLE_LABEL = { draft: '草稿', active: '生效', deprecated: '已弃用', archived: '已归档' }
const REVIEW_LABEL = { pending: '待审核', approved: '已审核', rejected: '已拒绝' }
const SOURCE_LABEL = { github: 'GitHub', distilled: '蒸馏', manual: '手工', imported: '导入' }

// 错误边界：SkillView 里任何渲染异常都不再让面板变黑，而是把错误显示出来。
// （此前"点技能 → 整个 Tab 全黑"就是异常被 DSH 错误边界吞掉，看不到原因。）
class SkillErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { err: '' }
  }
  static getDerivedStateFromError(err) {
    return { err: String((err && err.message) || err) }
  }
  componentDidCatch(err, info) {
    try { console.error('[literature] SkillView 渲染异常:', err, info) } catch (e) {}
  }
  render() {
    if (this.state.err) {
      return h('div', { className: 'dsh-lit-stack' },
        h('div', { className: 'dsh-lit-notice dsh-lit-notice-error', role: 'alert' },
          h('strong', null, '技能页渲染出错：'),
          h('div', { className: 'dsh-lit-content', style: { whiteSpace: 'pre-wrap', wordBreak: 'break-all' } },
            this.state.err)),
        h(Button, { icon: 'refresh', title: '重试', onClick: () => this.setState({ err: '' }) }, '重试'))
    }
    return this.props.children
  }
}

function SkillViewInner(props) {
  const [scope, setScope] = React.useState('')
  const [lifecycle, setLifecycle] = React.useState('')
  const [q, setQ] = React.useState('')
  const [selected, setSelected] = React.useState('')
  const [filePath, setFilePath] = React.useState('')
  const [busy, setBusy] = React.useState('')
  const [notice, setNotice] = React.useState(null)

  // 有搜索词时走关键词检索（完全名 > 前缀 > FTS > 标签，确定性排序）；
  // 无搜索词时走原来的全量列表。两条路结果字段不同，这里归一成同一形状。
  const skills = useResource(function () {
    const term = String(q || '').trim()
    if (!term) {
      return api('/skills' + qs({ workspace_id: props.workspaceId, scope: scope, lifecycle: lifecycle }))
    }
    return api('/skill-search' + qs({
      q: term, limit: 100,
      lifecycle: lifecycle || '',
      workspace_id: props.workspaceId,
    })).then(function (data) {
      const rows = list(data && data.skills).map(function (x) {
        return {
          id: x.skill_id, slug: x.name, title: x.title || x.name,
          summary_l0: x.l0, description: x.description,
          scope: x.scope, lifecycle: x.lifecycle,
          active_version_id: x.version_id,
          visibility: x.visibility, tier: x.tier, apply_90d: x.apply_90d,
        }
      })
      return { skills: rows, count: rows.length, __search: true }
    })
  }, [props.workspaceId, scope, lifecycle, q])

  const detail = useResource(function () {
    if (!selected) return Promise.resolve(null)
    const base = '/skills/' + encodeURIComponent(selected)
    return Promise.all([
      api(base + qs({ workspace_id: props.workspaceId })),
      api(base + '/versions' + qs({ workspace_id: props.workspaceId })),
      api(base + '/stats' + qs({ workspace_id: props.workspaceId })),
    ]).then(function (r) {
      return { skill: r[0] && r[0].skill, versions: list(r[1] && r[1].versions), stats: r[2] && r[2].stats }
    })
  }, [selected, props.workspaceId])

  function reload() { skills.reload(); if (selected) detail.reload() }

  function act(label, path, body) {
    setBusy(label); setNotice(null)
    api(path, { method: 'POST', body: body || {} }).then(function () {
      setNotice({ text: label + ' 成功', error: false }); reload()
    }).catch(function (error) {
      setNotice({ text: label + ' 失败：' + message(error), error: true })
    }).then(function () { setBusy('') })
  }

  const items = list(skills.data && skills.data.skills)
  const d = detail.data || null

  const filters = h('div', { className: 'dsh-lit-actions' },
    h('label', { className: 'dsh-lit-field' }, '搜索',
      h('input', {
        className: 'dsh-lit-input',
        type: 'search',
        value: q,
        placeholder: '技能名 / 标签 / 描述关键词',
        'aria-label': '关键词搜索技能',
        style: { minWidth: '220px' },
        onChange: function (e) { setQ(e.target.value) },
      })),
    h('label', { className: 'dsh-lit-field' }, '范围',
      h('select', { className: 'dsh-lit-select', value: scope, 'aria-label': '范围', onChange: function (e) { setScope(e.target.value) } },
        h('option', { value: '' }, '全部'),
        h('option', { value: 'workspace' }, '私有'),
        h('option', { value: 'global' }, '全局'))),
    h('label', { className: 'dsh-lit-field' }, '状态',
      h('select', { className: 'dsh-lit-select', value: lifecycle, 'aria-label': '生命周期', onChange: function (e) { setLifecycle(e.target.value) } },
        h('option', { value: '' }, '全部'),
        ['draft', 'active', 'deprecated', 'archived'].map(function (name) {
          return h('option', { key: name, value: name }, LIFECYCLE_LABEL[name] || name)
        }))))

  const listBox = skills.loading ? h('div', { className: 'dsh-lit-muted' }, '加载中…')
    : !items.length ? h(Empty, null, String(q || '').trim()
        ? '没有匹配「' + String(q).trim() + '」的技能（关键词路是确定性的：不命中就不返回）'
        : '暂无技能（先导入 GitHub 素体或从记忆蒸馏产生 draft）')
    : h('div', { className: 'dsh-lit-stack' }, items.map(function (item) {
      return h('button', {
        key: item.id, type: 'button',
        title: '点击查看详情',
        style: { cursor: 'pointer', textAlign: 'left', width: '100%', display: 'block' },
        className: 'dsh-lit-box' + (selected === item.id ? ' dsh-lit-graphbox-selected' : ''),
        onClick: function () { setSelected(item.id); setFilePath('') },
      },
        h('div', { className: 'dsh-lit-title' }, '🧩 ' + (item.title || item.slug)),
        h('div', { className: 'dsh-lit-mini' },
          (SCOPE_LABEL[item.scope] || item.scope) + ' · ' + (LIFECYCLE_LABEL[item.lifecycle] || item.lifecycle) +
          (item.active_version_id ? ' · v' + item.active_version_id : ' · 无生效版本') +
          (item.visibility === 'model' ? ' · 🤖 模型可见' : ' · 👤 仅用户') +
          (item.apply_90d ? ' · 90天用 ' + item.apply_90d + ' 次' : '')),
        h('div', { className: 'dsh-lit-muted' }, short(item.summary_l0 || item.description || item.slug, 70)))
    }))

  const detailBox = !selected ? h('div', { className: 'dsh-lit-muted' }, '选择左侧技能查看详情')
    : detail.loading ? h('div', { className: 'dsh-lit-muted' }, '加载中…')
    : detail.error ? h(Notice, { text: detail.error, error: true, retry: detail.reload })
    : (!d || !d.skill)
      // 防御：useResource 的初始 state 与每次重载都会把 data 置 null，
      // 此前这里直接读 d.skill，导致 "Cannot read properties of null (reading 'skill')"
      // 把整个技能面板打黑（2026-09-17 实报）。
      ? h('div', { className: 'dsh-lit-stack' },
        h('div', { className: 'dsh-lit-muted' },
          '未能加载该技能详情（可能无权限、已删除，或工作区不匹配）'),
        h(Button, { icon: 'refresh', title: '重试', onClick: detail.reload }, '重试'))
    : h('div', { className: 'dsh-lit-stack' },
      h(Section, { title: d.skill.title || d.skill.slug },
        h(KV, { rows: [
          ['slug', d.skill.slug],
          ['范围', (SCOPE_LABEL[d.skill.scope] || d.skill.scope) + (d.skill.workspace_id ? ' · ' + short(d.skill.workspace_id, 12) : '')],
          ['生命周期', LIFECYCLE_LABEL[d.skill.lifecycle] || d.skill.lifecycle],
          ['可见性', d.skill.visibility === 'model' ? '模型可调用' : '仅用户调用'],
          ['来源区', d.skill.origin_workspace_id ? short(d.skill.origin_workspace_id, 12) : '—'],
        ] })),
      (function () {
        const latest = list(d.versions)[0]
        if (!latest || !latest.overview_l1) return null
        return h(Section, { title: '概览 L1' },
          h('div', { className: 'dsh-lit-muted', style: { whiteSpace: 'pre-wrap', lineHeight: '1.6' } },
            latest.overview_l1),
          latest.summary_l0
            ? h('div', { className: 'dsh-lit-mini', style: { marginTop: '6px' } }, 'L0：' + latest.summary_l0)
            : null,
          h('div', { className: 'dsh-lit-mini' },
            'L2 正文 ' + (latest.skill_md ? latest.skill_md.length + ' 字符' : '—') +
            '（按需加载，不在此处展开）'))
      })(),
      h(Section, { title: '版本历史', count: d.versions.length },
        d.versions.length ? h('div', { className: 'dsh-lit-stack' }, d.versions.map(function (v) {
          return h('div', { key: v.id, className: 'dsh-lit-box' },
            h('div', { className: 'dsh-lit-mini' },
              'v' + v.version + ' · ' + (REVIEW_LABEL[v.review_status] || v.review_status) +
              ' · ' + (SOURCE_LABEL[v.source_kind] || v.source_kind)),
            h('div', { className: 'dsh-lit-muted', title: 'artifact_sha256' },
              short(v.content_sha256 || '', 16) + ' · ' + (list(v.files).length || 0) + ' 个附件'),
            v.source_url ? h('div', { className: 'dsh-lit-muted' }, short(v.source_url, 60)) : null,
            list(v.ignored_frontmatter_keys).length
              ? h('div', { className: 'dsh-lit-muted' }, 'DSH 忽略字段：' + list(v.ignored_frontmatter_keys).join(', '))
              : null,
            h('div', { className: 'dsh-lit-actions' },
              h(Button, {
                disabled: !!busy || v.review_status === 'approved', title: '审核通过',
                onClick: function () { act('审核通过', '/skill-versions/' + v.id + '/review', { decision: 'approve', reviewer: 'ui-reviewer', workspace_id: props.workspaceId }) },
              }, '通过'),
              h(Button, {
                disabled: !!busy || v.review_status === 'rejected', title: '拒绝该版本',
                onClick: function () { act('拒绝', '/skill-versions/' + v.id + '/review', { decision: 'reject', reviewer: 'ui-reviewer', workspace_id: props.workspaceId }) },
              }, '拒绝')))
        })) : h('div', { className: 'dsh-lit-muted' }, '暂无版本')),
      h(Section, { title: '使用统计' },
        h(KV, { rows: [
          ['加载次数', d.stats.load_count],
          ['应用任务', d.stats.applied_run_count],
          ['效果', d.stats.effectiveness == null
            ? '暂无评价' + (d.stats.effectiveness_reason ? '（' + d.stats.effectiveness_reason + '）' : '')
            : Math.round(d.stats.effectiveness * 100) + '% · 样本 ' + d.stats.effectiveness_samples],
          ['评价覆盖', d.stats.coverage == null ? '—' : Math.round(d.stats.coverage * 100) + '%'],
          ['调用路径', d.stats.invocation_counts ? JSON.stringify(d.stats.invocation_counts.load || {}) : '—'],
        ] })),
      h('div', { className: 'dsh-lit-actions' },
        d.skill.scope === 'workspace'
          ? h(Button, {
            title: '发布为全局（需批准人）', disabled: !!busy,
            onClick: function () { act('发布为全局', '/skills/' + encodeURIComponent(selected) + '/promote', { approver: 'ui-reviewer', workspace_id: props.workspaceId }) },
          }, '发布为全局')
          : null,
        h(Button, { icon: 'refresh', title: '刷新详情', onClick: reload, disabled: detail.loading })))

  return h('div', { className: 'dsh-lit-stack', 'aria-busy': skills.loading },
    h('div', { className: 'dsh-lit-actions' },
      h('h2', { className: 'dsh-lit-title dsh-lit-content' }, '技能'),
      h(Button, { icon: 'refresh', title: '刷新技能列表', onClick: reload, disabled: skills.loading })),
    h(Notice, { text: skills.error, error: true, retry: skills.reload }),
    h(Notice, { text: notice && notice.text, error: notice && notice.error, success: notice && !notice.error }),
    filters,
    // 主从布局：列表在左、详情在右。
    // 此前两者是上下堆叠，点列表项后详情渲染在屏幕下方，用户以为"点不动"。
    h('div', {
      style: { display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'flex-start' },
    },
      h('div', { style: { flex: '1 1 200px', minWidth: '200px' }, className: 'dsh-lit-stack' }, listBox),
      h('div', { style: { flex: '1 1 300px', minWidth: '300px' }, className: 'dsh-lit-stack' }, detailBox)))
}


function SkillView(props) {
  return h(SkillErrorBoundary, null, h(SkillViewInner, props))
}


// ── 长任务监控（阶段 4）：数据来自 GET /jobs，服务端 jobs.db 独立于知识库 ──
const JOB_ICON = { running: '▶', done: '✓', failed: '✗', stalled: '⚠', cancelled: '⊘' }
const JOB_STATUS_LABEL = {
  running: '运行中', done: '已完成', failed: '失败', stalled: '卡死（心跳停止）', cancelled: '已取消',
}
function jobStatusColor(status) {
  if (status === 'running') return 'var(--dsw-alias-state-info-primary, #2196f3)'
  if (status === 'done') return 'var(--dsw-alias-state-success-primary, #22b573)'
  if (status === 'failed') return 'var(--dsw-alias-state-error-primary, #e24a4a)'
  if (status === 'stalled') return 'var(--dsw-alias-state-warn-primary, #e0a020)'
  return 'var(--dsw-alias-text-secondary, #999)'
}
function fmtDuration(seconds) {
  const n = Number(seconds)
  if (!isFinite(n) || n < 0) return '—'
  if (n < 60) return Math.round(n) + 's'
  if (n < 3600) return Math.floor(n / 60) + 'm' + String(Math.floor(n % 60)).padStart(2, '0') + 's'
  return Math.floor(n / 3600) + 'h' + String(Math.floor((n % 3600) / 60)).padStart(2, '0') + 'm'
}
async function fetchJobs() {
  const payload = await api('/jobs?limit=60')
  return { jobs: list(payload && payload.jobs), counts: (payload && payload.counts) || {}, stale: payload && payload.stale_after_sec }
}
function JobRow(props) {
  const job = props.job
  const color = jobStatusColor(job.status)
  const pct = job.percent
  const eta = job.eta_sec ? ' · 还剩 ' + fmtDuration(job.eta_sec) : ''
  const hb = job.status === 'running'
    ? ' · 心跳 ' + Math.round(job.heartbeat_age_sec) + 's 前'
    : (job.status === 'stalled' ? ' · ⚠ 心跳已停 ' + Math.round(job.heartbeat_age_sec) + 's' : '')
  return h('div', { className: 'dsh-lit-evidence' },
    h('div', { className: 'dsh-lit-actions' },
      h('span', { style: { color: color, fontWeight: 700 } }, JOB_ICON[job.status] || '?'),
      h('span', { className: 'dsh-lit-mini' }, JOB_STATUS_LABEL[job.status] || job.status),
      h('strong', { className: 'dsh-lit-content' }, String(job.title || job.kind || '')),
      h('span', { className: 'dsh-lit-muted' }, pct == null ? '—' : pct.toFixed(1) + '%')),
    h('div', {
      style: { height: '8px', borderRadius: '4px', background: 'var(--dsw-alias-bg-tertiary, #eee)', overflow: 'hidden', margin: '6px 0' },
    }, h('div', { style: { height: '100%', width: (pct == null ? 30 : Math.max(0, Math.min(100, pct))) + '%', background: color, transition: 'width .4s' } })),
    h('div', { className: 'dsh-lit-muted' },
      String(job.done) + ' / ' + String(job.total) + ' · 用时 ' + fmtDuration(job.elapsed_sec) + eta + hb),
    job.error ? h('div', { className: 'dsh-lit-chain-flag' }, '✗ ' + String(job.error).slice(0, 240)) : null,
    h('div', { className: 'dsh-lit-muted', style: { fontSize: '10px', opacity: 0.6 } }, String(job.id || '')))
}
function JobsView(props) {
  const resource = useResource(async function () { return fetchJobs() }, [props.workspaceId])
  const data = resource.data || {}
  const jobs = list(data.jobs)
  const counts = data.counts || {}
  const running = jobs.filter(function (j) { return j.status === 'running' || j.status === 'stalled' })
  const finished = jobs.filter(function (j) { return j.status !== 'running' && j.status !== 'stalled' })
  const loaded = !resource.loading && !resource.error
  return h('div', { className: 'dsh-lit-stack', 'aria-busy': resource.loading },
    h('div', { className: 'dsh-lit-actions' },
      h('span', { className: 'dsh-lit-title' }, '⏱ 长任务'),
      h('span', { className: 'dsh-lit-count' },
        resource.loading ? '加载中…' : (running.length + ' 进行中 / ' + finished.length + ' 历史')),
      h(Button, { icon: 'refresh', title: '重新加载任务列表', onClick: resource.reload, disabled: resource.loading })),
    h('div', { className: 'dsh-lit-muted' },
      '心跳超 ' + String(data.stale || 90) + ' 秒未更新 ⇒ 自动标为「卡死」。任务数据存在独立 jobs.db，不占知识库。'),
    resource.error ? h('div', { className: 'dsh-lit-chain-flag' }, '接口不可用：' + String(resource.error)) : null,
    !resource.loading && !jobs.length
      ? h('div', { className: 'dsh-lit-muted' }, '当前没有任务记录。长任务（夜间抽取 / 矩阵判定 / 向量回填）开始时会自动出现。')
      : null,
    running.length
      ? h('div', { className: 'dsh-lit-stack' },
        h('div', { className: 'dsh-lit-section-head' }, h('h3', { className: 'dsh-lit-title' }, '进行中 · ' + running.length)),
        running.map(function (j) { return h(JobRow, { key: j.id, job: j }) }))
      : null,
    finished.length
      ? h('div', { className: 'dsh-lit-stack' },
        h('div', { className: 'dsh-lit-section-head' }, h('h3', { className: 'dsh-lit-title' }, '最近完成 · ' + finished.length)),
        finished.slice(0, 20).map(function (j) { return h(JobRow, { key: j.id, job: j }) }))
      : null,
    loaded && counts && Object.keys(counts).length
      ? h('div', { className: 'dsh-lit-muted' },
        '状态统计：' + Object.keys(counts).map(function (k) { return (JOB_STATUS_LABEL[k] || k) + ' ' + counts[k] }).join(' ｜ '))
      : null)
}


// ── 命题矩阵（阶段 3.3）：49 条命题 × 正反证据计数，数据来自 GET /propositions ──
const PROP_STATUS = {
  consensus: { label: '有共识', color: 'var(--dsw-alias-state-success-primary, #22b573)' },
  disputed: { label: '有分歧', color: 'var(--dsw-alias-state-error-primary, #e24a4a)' },
  single: { label: '单篇证据', color: 'var(--dsw-alias-state-warn-primary, #e0a020)' },
  gap: { label: '研究空白', color: 'var(--dsw-alias-text-secondary, #999)' },
}
async function fetchPropositions() {
  const payload = await api('/propositions')
  return { propositions: list(payload && payload.propositions) }
}
function PropRow(props) {
  const p = props.prop
  const st = PROP_STATUS[p.status] || { label: p.status, color: 'inherit' }
  return h('div', { className: 'dsh-lit-evidence' },
    h('div', { className: 'dsh-lit-actions' },
      h('span', { style: { color: st.color, fontWeight: 700, minWidth: '56px' } }, st.label),
      h('span', { className: 'dsh-lit-mini', style: { fontFamily: 'ui-monospace, monospace' } }, String(p.proposition_id)),
      h('span', { className: 'dsh-lit-content' }, String(p.canonical || '（无命题文本）')),
      h('span', { className: 'dsh-lit-muted' },
        String(p.branch || '') + ' ｜ 支持 ' + p.support + ' ｜ 反驳 ' + p.refute + ' ｜ 限定 ' + p.qualifies)),
    p.not_addressed || p.found_corrupt
      ? h('div', { className: 'dsh-lit-muted' },
        '未涉及 ' + p.not_addressed + (p.found_corrupt ? ' ｜ 残句待查 ' + p.found_corrupt : ''))
      : null)
}
function PropositionsView(props) {
  const resource = useResource(async function () { return fetchPropositions() }, [props.workspaceId])
  const [filter, setFilter] = React.useState('')
  const data = resource.data || {}
  const all = list(data.propositions)
  const rows = all.filter(function (p) { return !filter || p.status === filter })
  const counts = {}
  all.forEach(function (p) { counts[p.status] = (counts[p.status] || 0) + 1 })
  return h('div', { className: 'dsh-lit-stack', 'aria-busy': resource.loading },
    h('div', { className: 'dsh-lit-actions' },
      h('span', { className: 'dsh-lit-title' }, '📋 命题矩阵'),
      h('span', { className: 'dsh-lit-count' }, resource.loading ? '加载中…' : all.length + ' 条命题'),
      h(Button, { icon: 'refresh', title: '重新加载', onClick: resource.reload, disabled: resource.loading })),
    h('div', { className: 'dsh-lit-muted' },
      '文献只提供观点分布；判定哪一方成立需要实验。这里如实记录正反两方证据数，不做"谁对"的裁决。'),
    h('div', { className: 'dsh-lit-actions', style: { flexWrap: 'wrap', gap: '6px' } },
      ['', 'disputed', 'consensus', 'single', 'gap'].map(function (k) {
        const label = k ? ((PROP_STATUS[k] || {}).label || k) + ' ' + (counts[k] || 0) : '全部 ' + all.length
        const active = filter === k
        return h('button', {
          key: k || 'all',
          type: 'button',
          className: 'dsh-lit-btn' + (active ? ' dsh-lit-btn-active' : ''),
          title: k ? ('只看' + label) : '显示全部命题',
          onClick: function () { setFilter(k) },
          style: active ? { fontWeight: 700 } : null,
        }, label)
      })),
    resource.error ? h('div', { className: 'dsh-lit-chain-flag' }, '接口不可用：' + String(resource.error)) : null,
    !resource.loading && !rows.length
      ? h('div', { className: 'dsh-lit-muted' }, '没有符合条件的命题。')
      : null,
    rows.map(function (p) {
      return h(PropRow, { key: p.proposition_id, prop: p })
    }))
}

const TABS = [
  { id: 'docs', label: '📄 文档', component: DocumentsView },
  { id: 'knowledge', label: '🧠 知识', component: KnowledgeView },
  { id: 'graph', label: '🕸 图谱', component: GraphView },
  { id: 'chains', label: '🧭 认识演进', component: ChainsView },
  { id: 'propositions', label: '📋 命题', component: PropositionsView },
  { id: 'jobs', label: '⏱ 任务', component: JobsView },
  { id: 'skills', label: '🧩 技能', component: SkillView },
  { id: 'status', label: '📊 状况', component: StatusView },
]

function PanelBody(props) {
  useLibraries()          // 面板根订阅一次：库列表接口回来即重渲染（老服务端/失败时静默用兜底）
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
  if (workspaceId === null) {
    return h('div', { className: 'dsh-lit-panel' },
      h('div', { className: 'dsh-lit-muted', role: 'status' }, '正在解析工作区…'))
  }
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
  // 设置 → 插件。0.1.7 起旧槽 `settings.plugin.item` 已删除，改用插件页的 `plugins.item`
  // 列表槽：注册项以「内嵌视图」参与渲染——view==='summary' 取其一行描述，其余渲染整卡。
  // 旧代码的 key 与第三个「注册条件」参数在新槽不存在，generator 形式也不再需要。
  slots.inject('plugins.item', function () {
    return slots.register(
      { name: 'plugins.item', id: 'literature', order: 60, label: () => 'literature 文献库' },
      function (props) {
        if (props && props.view === 'summary') return '文献库与知识图谱配置（数据来自 literature-server）'
        return h(ConfigView, {})
      },
    )
  })
}

return { name, apply }
  }
})
