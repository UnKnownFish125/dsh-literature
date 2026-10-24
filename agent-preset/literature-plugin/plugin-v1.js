// dsh-literature agent 工具载体（contract-v0.2 §4.4 冻结 + v1.2 修复）
// 工具：literature_add / literature_search / literature_attach /
//       literature_update / literature_link_evidence
//
// 【v1.2 关键修复 2026-09-16】
// 1) 补 export const inject = ['tools']（此前缺失，与 kb 插件不一致）。
// 2) 相对 URL 换绝对 URL + Bearer：本插件跑在 dsh-web 的 Node 进程内，
//    fetch('/lit-api/...') 会被 undici 拒绝；/lit-api 只服务浏览器同源请求。
// 3) 服务基址与 token 一律由 systemd unit 显式注入，**禁止跨环境 fallback**
//    （兜底路径会让测试实例命中生产 token + 默认 6260 → 直写生产库）。
// 4) workspace_id 一律**显式传入**：不硬编码、不做隐式兜底。此前 DEFAULT_WS 是
//    'deepseek-hardness'（拼写错+自造值），历史上曾导致 139 条知识写进孤儿工作区；
//    改成空串同样危险——服务端空 ws 会落到"不加过滤"或上游任意区数据。
// 5) literature_attach 由空桩改为真实实现（multipart 上传 + 回写文档）。
// 6) 补 literature_update（原错误信息引用了它，但工具并不存在）。

import fs from 'node:fs'
import path from 'node:path'
import { defineTool } from '/usr/local/node/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-tools/lib/index.js'

// 与 kb 插件（同样是 'dsh-literature'）区分：DSH 以 name 作注册键，
// 同名会导致后加载者覆盖前者（astra 评审步骤 6 要求先验证/改名）。
export const name = 'dsh-literature-io'

export const inject = ['tools']

// ── 显式绑定（无兜底）──────────────────────────────────────────────────────
const PORT = String(process.env.LITERATURE_SERVER_PORT || '').trim()
const API = PORT ? `http://127.0.0.1:${PORT}/v1/literature` : ''
const TOKEN_FILE = String(process.env.LITERATURE_API_TOKEN_FILE || '').trim()

function readToken() {
  if (!TOKEN_FILE) return ''
  try {
    return fs.readFileSync(TOKEN_FILE, 'utf8').trim()
  } catch {
    return ''
  }
}

/** 配置自检：返回错误描述或空串。**不抛异常**——插件异常会炸掉所有会话的每个回合。 */
function configProblem() {
  if (!API) return 'LITERATURE_SERVER_PORT 未注入（拒绝隐式默认端口，防误连生产）'
  if (!TOKEN_FILE) return 'LITERATURE_API_TOKEN_FILE 未注入（拒绝跨环境 token fallback）'
  if (!readToken()) return `token 文件不可读: ${TOKEN_FILE}`
  return ''
}

async function api(path_, opts = {}) {
  const problem = configProblem()
  if (problem) throw new Error(`[literature] 配置错误：${problem}`)
  const { method = 'GET', body } = opts
  const res = await fetch(API + path_, {
    method,
    headers: {
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      Authorization: `Bearer ${readToken()}`,
    },
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`)
  return data
}

/** multipart 上传（Node 18+ 原生 FormData/Blob）。 */
async function apiUpload(path_, filePath) {
  const problem = configProblem()
  if (problem) throw new Error(`[literature] 配置错误：${problem}`)
  const buf = fs.readFileSync(filePath)
  const form = new FormData()
  form.append('file', new Blob([buf]), path.basename(filePath))
  const res = await fetch(API + path_, {
    method: 'POST',
    headers: { Authorization: `Bearer ${readToken()}` }, // 不要手工设 Content-Type，交给 FormData
    body: form,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`)
  return data
}

/** 所有工具都必须显式给出工作区 UUID（禁止硬编码/隐式兜底）。 */
const WS_PARAM = {
  type: 'string',
  required: true,
  description: '宿主工作区 UUID（按 DSH_SESSION_ID→/www/dsh/home/storages/workspace.json 解析）。禁止硬编码或留空。',
}

function needWs(args) {
  const ws = String((args && args.workspace_id) || '').trim()
  if (!ws) throw new Error('workspace_id is required（服务端与插件都不做兜底：错误值会写进孤儿工作区）')
  return ws
}

/** id 入参归一（P5）：单 id / 数字字符串 / "1,2" / 数组 → 去重 int 数组（保序）。 */
function normalizeIds(value) {
  let raw
  if (Array.isArray(value)) raw = value
  else if (value === undefined || value === null || value === '') raw = []
  else if (typeof value === 'string' && value.includes(',')) raw = value.split(',')
  else raw = [value]
  const out = []
  for (const v of raw) {
    if (v === undefined || v === null || v === '') continue
    const n = Number(v)
    if (!Number.isInteger(n)) throw new Error(`knowledge id 必须是整数: ${JSON.stringify(v)}`)
    if (!out.includes(n)) out.push(n)
  }
  return out
}

export function apply(ctx) {
  const outSchema = { type: 'object', additionalProperties: true }
  const textRender = (value) => [{ type: 'text', text: typeof value === 'string' ? value : JSON.stringify(value) }]

  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'literature_add',
    description: 'Add a literature/paper/book to the literature library (title/authors/year/doi/tags).',
    parameters: {
      title: { type: 'string', required: true, description: 'Title of the document.' },
      type: { type: 'string', description: 'paper | book | report | web', default: 'paper' },
      authors: { type: 'array', description: 'List of author names.', default: [] },
      year: { type: 'integer', description: 'Publication year.' },
      doi: { type: 'string', description: 'DOI identifier.' },
      tags: { type: 'array', description: 'Tags.', default: [] },
      workspace_id: WS_PARAM,
    },
    output: { schema: outSchema, render: (args, value) => textRender(value) },
    async execute(args) {
      const ws = needWs(args)
      const doc = await api('/documents', { method: 'POST', body: { ...args, workspace_id: ws } })
      return { ok: true, id: doc.document.id, title: doc.document.title, workspace_id: ws, document: doc.document }
    },
  })))

  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'literature_search',
    description: 'Search literature, evidence and knowledge in the literature library. Returns documents with authors/year/doi plus claims aggregation and graph overview.',
    parameters: {
      query: { type: 'string', required: true, description: 'Search keywords (title/author/journal).' },
      k: { type: 'integer', description: 'Max results.', default: 5 },
      workspace_id: WS_PARAM,
    },
    output: { schema: outSchema, render: (args, value) => textRender(value) },
    async execute(args) {
      const ws = needWs(args)
      const data = await api(`/documents?q=${encodeURIComponent(String(args.query || ''))}&workspace_id=${encodeURIComponent(ws)}`)
      const docs = (data.documents || []).slice(0, args.k || 5).map((d) => ({
        id: d.id, title: d.title, authors: d.authors || [], year: d.year,
        doi: d.doi, read_status: d.read_status,
      }))
      return { ok: true, count: docs.length, workspace_id: ws, results: docs }
    },
  })))

  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'literature_attach',
    description: 'Attach a file (PDF/EPUB) to a literature record: uploads the file then writes attachment_path/attachment_sha256 back to the document.',
    parameters: {
      document_id: { type: 'integer', required: true, description: 'Document id to attach to.' },
      file: { type: 'string', required: true, description: 'Absolute file path on this server to upload.' },
      workspace_id: WS_PARAM,
    },
    output: { schema: outSchema, render: (args, value) => textRender(value) },
    async execute(args) {
      const ws = needWs(args)
      const filePath = String(args.file || '')
      if (!fs.existsSync(filePath)) throw new Error(`文件不存在: ${filePath}`)
      const up = await apiUpload('/attachments', filePath)
      const attachmentPath = up.attachment_path || up.path
      const attachmentSha = up.attachment_sha256 || up.sha256
      if (!attachmentPath) throw new Error('上传成功但响应缺少 attachment_path')
      const updated = await api(`/documents/${encodeURIComponent(args.document_id)}`, {
        method: 'PATCH',
        body: { attachment_path: attachmentPath, attachment_sha256: attachmentSha, workspace_id: ws },
      })
      return { ok: true, document_id: args.document_id, attachment_path: attachmentPath,
               attachment_sha256: attachmentSha, workspace_id: ws, document: updated.document }
    },
  })))

  // 新增：原 literature_attach 的错误信息引用了它，但工具从未定义
  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'literature_update',
    description: 'Update fields of an existing literature document (title/authors/year/doi/tags/read_status/attachment_path...).',
    parameters: {
      document_id: { type: 'integer', required: true, description: 'Document id to update.' },
      patch: { type: 'object', required: true, description: 'Fields to update (e.g. {"read_status":"read"}).', additionalProperties: true },
      workspace_id: WS_PARAM,
    },
    output: { schema: outSchema, render: (args, value) => textRender(value) },
    async execute(args) {
      const ws = needWs(args)
      const body = { ...(args.patch || {}), workspace_id: ws }
      const updated = await api(`/documents/${encodeURIComponent(args.document_id)}`, { method: 'PATCH', body })
      return { ok: true, document_id: args.document_id, workspace_id: ws, document: updated.document }
    },
  })))

  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'literature_link_evidence',
    description:
      'Attach ONE evidence (claim/quote with stance) to one or MORE knowledge points. '
      + 'Idempotent on the (claim, stance) PAIR: the same normalized claim (strip + collapse whitespace + lowercase) WITH the same stance '
      + 'REUSES the existing evidence row instead of creating a duplicate, so the same evidence row can back several knowledge points. '
      + 'The SAME claim with a DIFFERENT stance creates a SEPARATE row — never fold an opposite stance into an existing row (both rows must stay). '
      + 'Attach to existing knowledge items by id (knowledge_ids / knowledge_id), or create new ones by concept / concepts. '
      + 'IMPORTANT — conflicting evidence must be captured, never skipped: if the document contains anything that contradicts existing knowledge, '
      + 'narrows or qualifies a claim, or is a counter-example / negative result / failed reproduction / stated limitation, '
      + 'extract it as its OWN evidence row with stance="contradicting". '
      + 'Do NOT fold it into a supporting row, and do NOT leave it at the default "contextual" just because it reads as a limitation. '
      + 'Positive example: quote "naive full-context caching … can paradoxically increase latency" '
      + '=> {claim: "Naive full-context caching can paradoxically increase latency.", stance: "contradicting", relation: "反驳"}. '
      + 'Negative example: labelling that same quote "supporting", or dropping it because "it is only a limitation", is WRONG. '
      + 'contradicting means conflicting / negating / boundary-narrowing claims — it is NOT about negative wording. '
      + 'When you also create a knowledge item, set relation to one of the 6 controlled words ONLY: '
      + '支持 (supports) | 反驳 (refutes) | 细化 (refines) | 依赖 (depends on) | 替代 (replaces) | 同义 (synonymous); '
      + 'direction is source = this evidence/knowledge, target = the referenced existing knowledge. '
      + 'Keep stance and relation consistent: supporting => 支持, contradicting => 反驳, contextual => relation may be empty. '
      + 'Never emit a vague relation such as 相关. Vocabulary + prompt fragments: /www/dsh-literature-deploy/literature-server/RELATION_VOCAB.md (§5.A/§5.B).',
    parameters: {
      claim: { type: 'string', required: true, description: 'The claim in one sentence. Same normalized claim + same stance reuses the existing evidence row (no duplicate); the same claim with a different stance creates a separate row.' },
      stance: {
        type: 'string',
        description:
          'supporting | contradicting | contextual. The default "contextual" is ONLY for neutral background / method / data claims. '
          + 'You MUST use "contradicting" for any counter-example, negative result, conflicting conclusion, boundary or qualifying condition, '
          + 'or author-stated limitation found in the document — extract each of those as a SEPARATE evidence row. '
          + 'When unsure, do not downgrade a contradicting item to supporting/contextual; downgrade the relation instead (leave it empty).',
        default: 'contextual',
      },
      evidence_text: { type: 'string', description: 'Original quote with source location.' },
      doc_id: { type: 'integer', description: 'Document id this evidence maps to.' },
      concept: { type: 'string', description: 'Legacy single knowledge point: if given, also create a knowledge item with this concept (kept for backwards compatibility).' },
      concepts: { type: 'array', description: 'Create one knowledge item per concept; all of them attach to the SAME evidence row (one evidence → several knowledge points).' },
      knowledge_ids: { type: 'array', description: 'Ids of EXISTING knowledge items to attach this evidence to (a single integer is also accepted).' },
      knowledge_id: { type: 'integer', description: 'Single existing knowledge item id — scalar form of knowledge_ids, kept for backwards compatibility.' },
      workspace_id: WS_PARAM,
    },
    output: { schema: outSchema, render: (args, value) => textRender(value) },
    async execute(args) {
      const ws = needWs(args)
      // 1) 一条 evidence：同 claim 幂等复用既有行（不再每次新建重复行）
      const ev = await api('/evidence', {
        method: 'POST',
        body: {
          claim: args.claim, stance: args.stance || 'contextual',
          evidence_text: args.evidence_text || '', doc_id: args.doc_id, workspace_id: ws,
        },
      })
      const evidenceId = ev.evidence.id
      const result = { ok: true, evidence_id: evidenceId, reused: !!ev.reused, workspace_id: ws }
      if (ev.stance_conflict) {
        // 同 claim 但本次 stance 与既有行不同：显式回报，不静默丢信息（不改既有行）
        result.stance_conflict = true
        result.stance = ev.evidence.stance
        result.stance_requested = ev.stance_requested
      }

      // 2) 新建知识点（老写法 concept + 新写法 concepts 列表）→ 全部挂到同一条 evidence
      const concepts = []
      const pushConcept = (c) => {
        const s = String(c === undefined || c === null ? '' : c).trim()
        if (s && !concepts.includes(s)) concepts.push(s)
      }
      if (args.concept) pushConcept(args.concept)
      const extra = Array.isArray(args.concepts) ? args.concepts : (args.concepts ? [args.concepts] : [])
      for (const c of extra) pushConcept(c)

      const createdIds = []
      for (const concept of concepts) {
        const kn = await api('/knowledge', {
          method: 'POST',
          body: { concept, summary: args.claim, sources: [evidenceId], workspace_id: ws },
        })
        createdIds.push(kn.knowledge.id)
      }

      // 3) 挂到**已有**知识点：knowledge_ids（列表/单值）+ knowledge_id（单 id 老写法）
      const targets = normalizeIds(args.knowledge_ids).concat(normalizeIds(args.knowledge_id))
      const linkIds = [...new Set(targets)].filter((id) => !createdIds.includes(id))
      let linkedIds = []
      if (linkIds.length) {
        const link = await api(`/evidence/${encodeURIComponent(evidenceId)}/sources`, {
          method: 'POST',
          body: { knowledge_ids: linkIds, workspace_id: ws },
        })
        linkedIds = (link.linked || []).concat(link.relinked || [])
        result.already_linked = link.already || []
      }

      const allIds = createdIds.concat(linkedIds)
      if (allIds.length) {
        result.knowledge_ids = allIds     // P5：这条 evidence 挂上的全部知识点
        result.knowledge_id = allIds[0]   // 老字段：单个知识点调用方读它，保持兼容
      }
      return result
    },
  })))
}
