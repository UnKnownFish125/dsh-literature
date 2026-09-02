// dsh-literatum agent 工具载体（plan-v3.1 §4.2 冻结）：
// kb_query / kb_browse / kb_constraints / kb_contracts / kb_graph
// 经 DSH 同源代理 /lit-api 访问 literatum kb-server（Host 插件附加 Bearer token）。
// kb_* 工具唯一归属 literatum（M4：deepmemory 插件侧维持 memory_recall/save/briefing，避免双注册）。
// 挂载：.agent-presets/_literatum-plugin/plugin-v1.js

import { defineTool } from '/usr/local/node/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-tools/lib/index.js'

export const name = 'dsh-literatum'

const API = '/lit-api/v1/literature'

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
    name: 'kb_query',
    description: 'Query the deepmemory knowledge base semantically. Returns relevant memories with content/type/library/importance. Pass library to scope to bias/core/eco/project/runtime.',
    parameters: {
      query: { type: 'string', required: true, description: 'Concise search keywords.' },
      library: { type: 'string', description: 'bias | core | eco | project | runtime. Empty = all.' },
      k: { type: 'integer', description: 'Max results.', default: 5 },
      workspace_id: { type: 'string', description: 'Workspace id.', default: '' },
    },
    output: { schema: outSchema, render: textRender },
    async execute(args) {
      const body = { query: String(args.query || ''), k: args.k || 5 }
      if (args.library) body.library = args.library
      if (args.workspace_id) body.workspace_id = args.workspace_id
      const data = await api('/kb/query', { method: 'POST', body })
      return { ok: true, count: data.count, results: data.results }
    },
  })))

  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'kb_browse',
    description: 'Browse the knowledge base library catalog: per-library counts and status. Use before querying to decide which library (bias/core/eco/project/runtime) has content.',
    parameters: {
      library: { type: 'string', description: 'Optional single library.', default: '' },
    },
    output: { schema: outSchema, render: textRender },
    async execute(args) {
      const q = args.library ? `?library=${encodeURIComponent(args.library)}` : ''
      const data = await api(`/kb/browse${q}`)
      return { ok: true, libraries: data.libraries }
    },
  })))

  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'kb_constraints',
    description: 'Fetch total behavior constraints (bias library): hard rules like test-machine-first, never touch production, absolute-path discipline. Call before acting on the system.',
    parameters: {
      k: { type: 'integer', description: 'Max constraints.', default: 12 },
    },
    output: { schema: outSchema, render: textRender },
    async execute(args) {
      const data = await api(`/kb/constraints?k=${args.k || 12}`)
      return { ok: true, count: data.count, constraints: data.constraints, note: data.note }
    },
  })))

  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'kb_contracts',
    description: 'Query deepmemory core design/contract knowledge: interface contracts, architecture decisions, plans (for derived-plugin development reference).',
    parameters: {
      topic: { type: 'string', description: 'Optional topic filter (e.g. 分库, 注入).', default: '' },
      k: { type: 'integer', description: 'Max results.', default: 10 },
    },
    output: { schema: outSchema, render: textRender },
    async execute(args) {
      const q = args.topic ? `?topic=${encodeURIComponent(args.topic)}&k=${args.k || 10}` : `?k=${args.k || 10}`
      const data = await api(`/kb/contracts${q}`)
      return { ok: true, count: data.count, contracts: data.contracts }
    },
  })))

  ctx.effect(() => ctx.tools.register(defineTool({
    name: 'kb_graph',
    description: 'Fetch the knowledge graph (entities and relations) from deepmemory.',
    parameters: {},
    output: { schema: outSchema, render: textRender },
    async execute() {
      const data = await api('/kb/graph')
      return { ok: true, graph: data.graph }
    },
  })))
}
