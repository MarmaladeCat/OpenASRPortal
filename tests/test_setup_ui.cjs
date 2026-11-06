// Real first-run UI and password login; isolated fake provider, no installed service.
const { app, BrowserWindow } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { createInterface } = require('node:readline');
const root = path.resolve(__dirname, '..');
const results = path.join(root, 'test-results', 'database-auth-ui');
fs.mkdirSync(results, { recursive: true });
app.setPath('userData', fs.mkdtempSync(path.join(root, 'test-results', 'setup-ui-browser-')));
app.disableHardwareAcceleration();
if (process.platform === 'linux') app.commandLine.appendSwitch('ozone-platform', 'x11');
app.on('window-all-closed', () => {});
let window, server;
const js = (code) => window.webContents.executeJavaScript(code);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function wait(code) {
  for (let attempt = 0; attempt < 300; attempt++) {
    if (await js(code)) return;
    await sleep(30);
  }
  throw new Error('UI timeout: ' + code);
}
async function run() {
  await app.whenReady();
  server = spawn(
    process.env.OPENASRPORTAL_TEST_PYTHON || 'python3',
    ['tests/serve_management_ui.py', '--fresh'],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, 'src'), PYTHONDONTWRITEBYTECODE: '1' }
    }
  );
  server.stderr.pipe(process.stderr);
  const lines = createInterface({ input: server.stdout });
  const ready = await Promise.race([
    once(lines, 'line').then(([line]) => JSON.parse(line)),
    once(server, 'exit').then(([code]) => {
      throw new Error('Fixture exited ' + code);
    })
  ]);
  const response = await fetch(ready.url + '/v1/local-input/pairings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ clientId: 'f'.repeat(32) })
  });
  assert.equal(response.status, 201);
  const pairing = await response.json();
  window = new BrowserWindow({
    show: false,
    width: 1000,
    height: 900,
    webPreferences: { nodeIntegration: false, contextIsolation: true }
  });
  const errors = [];
  window.webContents.on('console-message', (_event, level, message) => {
    if (level >= 3) errors.push(message);
  });
  await window.loadURL(ready.url + '/admin');
  await require('./language_ui.cjs').language(window, 'zh-CN');
  assert.equal(new URL(window.webContents.getURL()).pathname, '/admin/setup');
  await wait('document.getElementById("setup-status").textContent.includes("请设置")');
  assert.equal(await js('document.getElementById("setup-pair-code")'), null);
  await window.setContentSize(390, 900);
  await sleep(150);
  assert.equal(await js('document.documentElement.scrollWidth <= innerWidth'), true);
  fs.writeFileSync(
    path.join(results, 'first-run-mobile.png'),
    (await window.webContents.capturePage()).toPNG()
  );
  window.setContentSize(1000, 900);
  await sleep(150);
  fs.writeFileSync(
    path.join(results, 'first-run-password.png'),
    (await window.webContents.capturePage()).toPNG()
  );
  await js(`document.getElementById('setup-password').value='User defined password 2026!';
    document.getElementById('setup-confirm').value='Different password 2026!';
    document.getElementById('setup-form').requestSubmit()`);
  await wait('document.getElementById("setup-status").textContent.includes("不一致")');
  await require('./language_ui.cjs').language(window, 'en');
  assert.equal(
    await js('document.getElementById("setup-status").textContent'),
    'The passwords do not match.'
  );
  assert.equal(
    await js('document.getElementById("setup-password").value'),
    'User defined password 2026!'
  );
  fs.writeFileSync(
    path.join(results, 'first-run-english.png'),
    (await window.webContents.capturePage()).toPNG()
  );
  await require('./language_ui.cjs').language(window, 'zh-CN');
  await js(`document.getElementById('setup-confirm').value='User defined password 2026!';
    document.getElementById('setup-form').requestSubmit()`);
  await wait(
    'location.pathname==="/admin" && !!document.getElementById("workspace") && !document.getElementById("workspace").hidden'
  );
  const claim = await fetch(ready.url + '/v1/local-input/pairings/' + pairing.id + '/claim', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ claimToken: pairing.claimToken })
  });
  assert.equal((await claim.json()).state, 'pending');
  fs.writeFileSync(
    path.join(results, 'paired-management.png'),
    (await window.webContents.capturePage()).toPNG()
  );
  const oldToken = await js('sessionStorage.getItem("openasrportal-admin-session")');
  await require('./language_ui.cjs').verifyLanguages(window);
  await js('document.getElementById("logout").click()');
  await wait('!document.getElementById("login").hidden');
  assert.equal(
    (
      await fetch(ready.url + '/v1/admin/contract', {
        headers: { Authorization: 'Bearer ' + oldToken }
      })
    ).status,
    401
  );
  await js(
    `(() => {
      const originalFetch = window.fetch.bind(window);
      window.fetch = (...args) => {
        if (args[0] === '/v1/admin/asr-keys') {
          window.fetch = originalFetch;
          return new Promise(resolve => {
            window.releaseLoginRefresh = () => resolve(new Response(
              JSON.stringify({error: {message: '测试：识别 Key 列表暂不可用'}}),
              {status: 503, headers: {'Content-Type': 'application/json'}}
            ));
          });
        }
        return originalFetch(...args);
      };
      document.getElementById('admin-key').value='User defined password 2026!';
      document.getElementById('connect').click();
    })()`
  );
  await wait(
    '!document.getElementById("workspace").hidden && typeof window.releaseLoginRefresh === "function"'
  );
  // Successful authentication must clear the password before slower workspace requests finish.
  assert.equal(await js('document.getElementById("admin-key").value'), '');
  await js('window.releaseLoginRefresh(); delete window.releaseLoginRefresh');
  await wait('document.getElementById("status").textContent.includes("识别 Key 列表暂不可用")');
  assert.equal(await js('document.getElementById("admin-key").value'), '');
  assert.equal(errors.length, 0, errors.join('\n'));
  console.log(
    'PASS standalone first-run password page, mobile width, confirmation, no automatic Input grant, login/logout and password clearing before slow/failed workspace requests'
  );
}
run()
  .then(() => finish(0))
  .catch((error) => {
    console.error(error);
    finish(1);
  });
async function finish(code) {
  if (window && !window.isDestroyed()) window.destroy();
  if (server && server.exitCode === null && server.signalCode === null) {
    const exited = once(server, 'exit');
    server.kill('SIGINT');
    await Promise.race([exited, sleep(3000)]);
    if (server.exitCode === null && server.signalCode === null) {
      server.kill('SIGKILL');
      await exited;
    }
  }
  app.exit(code);
}
