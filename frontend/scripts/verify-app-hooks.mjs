export function onLaunch(callback) {
  globalThis.__M0AppLifecycle.launch.push(callback)
}

export function onShow(callback) {
  globalThis.__M0AppLifecycle.show.push(callback)
}

export function onHide(callback) {
  globalThis.__M0AppLifecycle.hide.push(callback)
}
