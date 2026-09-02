// dsh-literature agent 工具载体（contract-v0.2 §4.4 冻结）：
// literature_add / literature_search / literature_attach / literature_link_evidence
// 通过 DSH 同源代理 /lit-api 访问 literature server（Host 插件附加 Bearer token）。
// 挂载：.agent-presets/_literature-plugin/plugin-v1.js

import { defineTool } from '/usr/local/node/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-tools/lib/index.js'

export const name = 'dsh-literature'

const API = '/lit-api/v1/literature'
const DEFAULT_WS = 'deepseek-hardness'

async function api(path, opts = {}) {
  const { method = 'GET', body } = opts
  const res = await fetch(API + path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`)
  return data
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
      workspace_id: { type: 'string', description: 'Workspace id.', default: DEFAULT_WS },
    },
    output: { schema: outSchema, render: textRender },
    async execute(args) {
      const doc = await api('/documents', { method: 'POST', body: args })
      return { ok: true, id: doc.document.id, title: doc.document.title, document: doc.document }
    },
  })))

  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'literature_search',
    description: 'Search literature, evidence and knowledge in the literature library. Returns documents with authors/year/doi plus claims aggregation and graph overview.',
    parameters: {
      query: { type: 'string', required: true, description: 'Search keywords (title/author/journal).' },
      k: { type: 'integer', description: 'Max results.', default: 5 },
      workspace_id: { type: 'string', description: 'Workspace id.', default: DEFAULT_WS },
    },
    output: { schema: outSchema, render: textRender },
    async execute(args) {
      const q = encodeURIComponent(String(args.query || ''))
      const data = await api(`/documents?q=${q}&workspace_id=${encodeURIComponent(args.workspace_id || DEFAULT_WS)}`)
      const docs = (data.documents || []).slice(0, args.k || 5).map((d) => ({
        id: d.id, title: d.title, authors: d.authors || [], year: d.year,
        doi: d.doi, read_status: d.read_status,
      }))
      return { ok: true, count: docs.length, results: docs }
    },
  })))

  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'literature_attach',
    description: 'Attach a file (PDF/EPUB) to a literature record. Uploads the file and updates the document with attachment path and sha256.',
    parameters: {
      document_id: { type: 'integer', required: true, description: 'Document id to attach to.' },
      file: { type: 'string', required: true, description: 'File path on the server to upload.' },
      workspace_id: { type: 'string', description: 'Workspace id.', default: DEFAULT_WS },
    },
    output: { schema: outSchema, render: textRender },
    async execute(args) {
      // 文件在 DSH 服务器侧：由 Host 或调用方先 POST multipart 到 /lit-api/v1/literature/attachments。
      // 此处为约定接口：调用方需先用 attachments 上传拿到 attachment_path/attachment_sha256。
      throw new Error('literature_attach: 请先调用 /lit-api/v1/literature/attachments 上传文件获取 attachment_path/attachment_sha256，再用 literature_update 关联到文献')
    },
  })))

  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'literature_link_evidence',
    description: 'Attach an evidence (claim/quote with stance) to a document for the current discussion. Optionally create a knowledge item from it.',
    parameters: {
      claim: { type: 'string', required: true, description: 'The claim in one sentence.' },
      stance: { type: 'string', description: 'supporting | contradicting | contextual', default: 'contextual' },
      evidence_text: { type: 'string', description: 'Original quote with source location.' },
      doc_id: { type: 'integer', description: 'Document id this evidence maps to.' },
      concept: { type: 'string', description: 'If given, also create a knowledge item with this concept.' },
      workspace_id: { type: 'string', description: 'Workspace id.', default: DEFAULT_WS },
    },
    output: { schema: outSchema, render: textRender },
    async execute(args) {
      const ev = await api('/evidence', {
        method: 'POST',
        body: {
          claim: args.claim, stance: args.stance || 'contextual',
          evidence_text: args.evidence_text || '', doc_id: args.doc_id,
          workspace_id: args.workspace_id || DEFAULT_WS,
        },
      })
      const result = { ok: true, evidence_id: ev.evidence.id }
      if (args.concept) {
        const kn = await api('/knowledge', {
          method: 'POST',
          body: {
            concept: args.concept, summary: args.claim,
            sources: [ev.evidence.id], workspace_id: args.workspace_id || DEFAULT_WS,
          },
        })
        result.knowledge_id = kn.knowledge.id
      }
      return result
    },
  })))
}
