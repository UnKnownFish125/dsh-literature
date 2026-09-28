/** dsh-literature Host 插件：/lit-api 前缀全量代理到 literature server（默认 6260），
 *  附加 Bearer token（同 deepmemory/livetaskboard readToken 模式）。
 *  注册 literature 配置命名空间（设置 → 插件 → 插件配置页的发现契约）。 */
import http from 'node:http'
import fs from 'node:fs'
// 注：0.1.2-rc.1 起 @deepseek-ai/dsh-settings 不再导出 settingsNamespace/installSettingsSection。
// SettingsProvider.register(ns, schema) 两版均接受字符串 ns（0.1.2 内部自行 parseSettingsNamespace 校验），
// 故直接传命名空间字符串即可兼容 0.1.1-rc.2 与 0.1.2-rc.1。

export const name = 'dsh-literature'
export const inject = ['webServer']

const TARGET_HOST = 'localhost'
const TARGET_PORT = Number(process.env.LITERATUM_SERVER_PORT || 6260)
const PREFIX = '/lit-api'
const TOKEN_FILES = [
  process.env.LITERATUM_API_TOKEN_FILE,
  process.env.DSH_HOME ? `${process.env.DSH_HOME}/.dsh-literature-api-token` : '',
  process.env.HOME ? `${process.env.HOME}/.dsh-literature-api-token` : '',
].filter((path, index, paths) => path && paths.indexOf(path) === index)

function readToken() {
  for (const path of TOKEN_FILES) {
    try {
      const token = fs.readFileSync(path, 'utf8').trim()
      if (token) return token
    } catch {}
  }
  return ''
}

export function apply(ctx) {
  // 0.1.7 起不再有 ctx.settings.register：设置页表单由 Loader entry 的 Config schema 派生，
  // 而 literature 的配置实际由 literature server 持有（经 /lit-api 读写），不由 DSH settings
  // 提供。配置卡片改由客户端的 plugins.item 槽位自行注册。

  ctx.webServer.register({
    kind: 'prefix',
    path: PREFIX,
    handler: (req, res) => {
      let rel = req.url ?? ''
      if (rel.startsWith(PREFIX)) rel = rel.slice(PREFIX.length)
      if (!rel.startsWith('/')) rel = '/' + rel
      const upstreamPath = rel || '/v1/health'
      const headers = { ...req.headers }
      delete headers.origin
      delete headers.authorization
      const token = readToken()
      if (token) headers.authorization = `Bearer ${token}`
      headers.host = `${TARGET_HOST}:${TARGET_PORT}`
      const upstream = http.request(
        {
          host: TARGET_HOST,
          port: TARGET_PORT,
          path: upstreamPath,
          method: req.method ?? 'GET',
          headers,
          timeout: 30000,
        },
        (upRes) => {
          res.writeHead(upRes.statusCode ?? 502, upRes.headers)
          upRes.pipe(res)
        },
      )
      upstream.on('timeout', () => upstream.destroy(new Error('literature request timeout')))
      upstream.on('error', (error) => {
        try {
          res.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' })
          res.end(JSON.stringify({ error: String((error && error.message) || error) }))
        } catch {}
      })
      req.pipe(upstream)
    },
  })
}
