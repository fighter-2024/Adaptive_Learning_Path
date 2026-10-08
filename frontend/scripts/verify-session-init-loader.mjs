import { readFile } from 'node:fs/promises'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { dirname, extname, resolve as resolvePath } from 'node:path'

const scriptDirectory = dirname(fileURLToPath(import.meta.url))
const sourceDirectory = resolvePath(scriptDirectory, '../src')
const sourceUrlPrefix = pathToFileURL(`${sourceDirectory}/`).href

const aliases = new Map([
  ['@/store/user', resolvePath(sourceDirectory, 'store/user.js')],
  ['@/utils/request', resolvePath(sourceDirectory, 'utils/request.js')]
])

export async function resolve(specifier, context, nextResolve) {
  const aliasTarget = aliases.get(specifier)
  if (aliasTarget) {
    return { url: pathToFileURL(aliasTarget).href, shortCircuit: true }
  }
  return nextResolve(specifier, context)
}

export async function load(url, context, nextLoad) {
  if (url.startsWith(sourceUrlPrefix) && extname(url) === '.js') {
    let source = await readFile(fileURLToPath(url), 'utf8')
    if (url.endsWith('/utils/request.js')) {
      source = source.replaceAll('import.meta.env.VITE_API_BASE_URL', 'globalThis.__VITE_API_BASE_URL')
    }
    return { format: 'module', source, shortCircuit: true }
  }
  return nextLoad(url, context)
}
