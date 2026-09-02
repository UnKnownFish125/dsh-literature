__ModuleLoader__.load({
  id: 'dsh-literature',
  factory: (require) => {
/**
 * dsh-literatum Client 插件：文献/证据/知识三合一 UI + 插件配置页。
 * - conversation 面板入口：文献库列表/检索/图谱概览
 * - 设置 → 插件 → 插件配置：literatum 配置卡片（读 /config-schema + /config）
 * 全部经 /lit-api 同源代理访问 literatum server。
 */
const React = require('react')

const API = '/lit-api/v1/literatum'

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

// ── 文献库面板（conversation.view 侧栏/浮层）──────────────────────
function PanelView({ onBack }) {
  const [docs, setDocs] = React.useState([])
  const [graph, setGraph] = React.useState(null)
  const [query, setQuery] = React.useState('')
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState('')

  async function load() {
    setLoading(true)
    setError('')
    try {
      const q = query ? `?q=${encodeURIComponent(query)}` : ''
      const [d, g] = await Promise.all([
        api(`/documents${q}`),
        api('/graph').catch(() => ({ graph: { nodes: [], edges: [] } })),
      ])
      setDocs((d && d.documents) || [])
      setGraph(g && g.graph)
    } catch (e) {
      setError(String((e && e.message) || e))
    } finally {
      setLoading(false)
    }
  }

  React.useEffect(() => { load() }, [])

  const header = React.createElement('div', { style: { display: 'flex', gap: 8, alignItems: 'center', padding: 8 } }, [
    React.createElement('h3', { key: 't', style: { margin: 0, fontSize: 14 } }, '📚 文献库'),
    React.createElement('input', {
      key: 'q', value: query, placeholder: '检索标题/作者',
      style: { flex: 1, padding: '4px 8px', border: '1px solid #ccc', borderRadius: 4 },
      onChange: (e) => setQuery(e.target.value),
    }),
    React.createElement('button', { key: 's', onClick: load, style: { padding: '4px 10px' } }, '检索'),
    onBack ? React.createElement('button', { key: 'b', onClick: onBack, style: { padding: '4px 10px' } }, '返回') : null,
  ])

  const children = [header]
  if (loading) children.push(React.createElement('div', { key: 'l' }, '加载中…'))
  if (error) children.push(React.createElement('div', { key: 'e', style: { color: 'red', padding: 8 } }, error))
  children.push(React.createElement('ul', {
    key: 'list', style: { listStyle: 'none', margin: 0, padding: 8, maxHeight: 300, overflow: 'auto' },
  }, (docs || []).map((d) => React.createElement('li', {
    key: d.id, style: { padding: '6px 0', borderBottom: '1px solid #eee' },
  }, [
    React.createElement('div', { key: 't', style: { fontWeight: 600 } }, d.title || '(无题录)'),
    React.createElement('div', { key: 'm', style: { fontSize: 12, color: '#666' } },
      `${(d.authors || []).join('、')}${d.year ? ' · ' + d.year : ''}${d.doi ? ' · DOI:' + d.doi : ''}`),
  ]))))
  if (graph) {
    const { nodes = [], edges = [] } = graph
    children.push(React.createElement('div', { key: 'g', style: { padding: 8, fontSize: 12, color: '#555' } },
      `概念网络：${nodes.length} 节点 / ${edges.length} 边`))
    children.push(React.createElement('div', { key: 'ge', style: { padding: '0 8px 8px', fontSize: 12 } },
      (edges || []).map((e) => React.createElement('div', { key: `${e.source}-${e.target}` },
        `${e.source_concept || e.source} ${e.relation || '—'} ${e.target_concept || e.target}`))))
  }
  return React.createElement('div', null, children)
}

// ── 配置页（设置 → 插件 → 插件配置）──────────────────────────────
function ConfigView() {
  const [schema, setSchema] = React.useState(null)
  const [values, setValues] = React.useState({})
  const [msg, setMsg] = React.useState('')

  React.useEffect(() => {
    Promise.all([api('/config-schema'), api('/config')]).then(([s, c]) => {
      if (s && s.schema) setSchema(s.schema)
      if (c && c.config) setValues(c.config)
    }).catch((e) => setMsg('加载配置失败: ' + String((e && e.message) || e)))
  }, [])

  if (!schema) return React.createElement('div', null, '加载配置…')

  const groups = Object.keys(schema)
  const rows = []
  for (const gname of groups) {
    const g = schema[gname]
    rows.push(React.createElement('h4', { key: 'h' + gname, style: { margin: '12px 0 4px' } },
      g.description || gname))
    for (const key of Object.keys((g.items || {}))) {
      const item = g.items[key]
      const full = `${gname}.${key}`
      const val = values[full] !== undefined ? values[full] : item.default
      rows.push(React.createElement('div', { key: full, style: { marginBottom: 8 } }, [
        React.createElement('label', { key: 'l', style: { display: 'block', fontSize: 12, fontWeight: 600 } },
          `${item.description || key}${item.readonly ? '（只读）' : ''}`),
        React.createElement('input', {
          key: 'i', value: val === undefined || val === null ? '' : String(val),
          readOnly: !!item.readonly,
          style: { width: '100%', padding: '4px 8px', border: '1px solid #ccc', borderRadius: 4 },
          onChange: (e) => {
            let next = e.target.value
            if (item.type === 'number') next = Number(next)
            setValues((v) => ({ ...v, [full]: next }))
          },
        }),
        item.hint ? React.createElement('div', { key: 'hint', style: { fontSize: 11, color: '#888' } }, item.hint) : null,
      ]))
    }
  }

  async function save() {
    try {
      await api('/config', { method: 'POST', body: values })
      setMsg('已保存')
    } catch (e) {
      setMsg('保存失败: ' + String((e && e.message) || e))
    }
  }

  return React.createElement('div', null, [
    React.createElement('h3', { key: 't' }, 'literatum 文献库配置'),
    ...rows,
    React.createElement('div', { key: 'actions', style: { marginTop: 12 } }, [
      React.createElement('button', { key: 's', onClick: save }, '保存'),
      msg ? React.createElement('span', { key: 'm', style: { marginLeft: 8, fontSize: 12 } }, msg) : null,
    ]),
  ])
}

function apply(ctx) {
  const slots = ctx.get('slots')
  if (slots === undefined) return

  // 文献库面板：conversation.view tab 入口
  slots.inject('conversation.view', function () {
    return slots.register(
      { name: 'conversation.view', id: 'literatum', order: 60, label: '📚 文献库' },
      function () {
        return React.createElement(PanelView, {})
      },
    )
  }, { key: 'literatum' })

  // 插件配置卡片：设置 → 插件 → 插件配置页
  slots.inject('settings.plugin.item', function* () {
    yield slots.register(
      { name: 'settings.plugin.item', id: 'literatum', key: 'literatum', order: 60, label: 'literatum 文献库' },
      function () {
        return React.createElement(ConfigView, {})
      },
    )
  }, { key: 'literatum' })
}

const name = 'dsh-literatum'
const inject = ['settings']
return { name, apply }
  }
})
