import { resolve as resolveProduction, load as loadProduction } from './verify-session-init-loader.mjs'
import { dirname, resolve as resolvePath } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const scriptDirectory = dirname(fileURLToPath(import.meta.url))
const hooksUrl = pathToFileURL(resolvePath(scriptDirectory, 'verify-app-hooks.mjs')).href

export async function resolve(specifier, context, nextResolve) {
  if (specifier === '@dcloudio/uni-app') {
    return { url: hooksUrl, shortCircuit: true }
  }
  return resolveProduction(specifier, context, nextResolve)
}

export async function load(url, context, nextLoad) {
  return loadProduction(url, context, nextLoad)
}
