// Run with Electron against a disposable Portal; all upstream credentials are fake.
const { app, BrowserWindow } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { createInterface } = require('node:readline');

const root = path.resolve(__dirname, '..');
const temporary = fs.mkdtempSync(path.join(root, 'test-results', 'profile-editor-'));
app.setPath('userData', temporary);
app.disableHardwareAcceleration();
if (process.platform === 'linux') app.commandLine.appendSwitch('ozone-platform', 'x11');
app.on('window-all-closed', () => {});
let window, server;
const js = (code) => window.webContents.executeJavaScript(code);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function wait(code) {
  for (let attempt = 0; attempt < 200; attempt++) {
    if (await js(code)) return;
    await sleep(25);
  }
  throw new Error('UI timeout: ' + code);
}
const secret = 'document.querySelector("#fields input[name=apiKey]")';
async function newDoubao() {
  await js(`document.getElementById('new').click();
    document.getElementById('provider').value='doubao_realtime';
    document.getElementById('provider').dispatchEvent(new Event('change'));`);
}
async function run() {
  await app.whenReady();
  server = spawn(
    process.env.OPENASRPORTAL_TEST_PYTHON || 'python3',
    ['tests/serve_management_ui.py'],
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
      throw new Error('Fixture exited: ' + code);
    })
  ]);
  window = new BrowserWindow({
    show: false,
    webPreferences: { nodeIntegration: false, contextIsolation: true }
  });
  await window.loadURL(ready.url + '/admin');
  await require('./language_ui.cjs').language(window, 'zh-CN');
  await js(`document.getElementById('admin-key').value='test-admin-password';
    document.getElementById('connect').click();`);
  await wait('!document.getElementById("workspace").hidden');
  // Observe actual requests, while still sending them to the real management API.
  await js(`window.profileWrites=[];window.profileProbes=[];
    const originalFetch=window.fetch;
    window.fetch=(url, options)=>{
      if (url.endsWith('/test')) window.profileProbes.push(options.body);
      else if (url.includes('/profiles') && options?.body)
        window.profileWrites.push(JSON.parse(options.body));
      return originalFetch(url, options);
    };undefined;`);
  for (const [id, key] of [
    ['doubao-1', 'key-1'],
    ['doubao-2', 'key-2']
  ]) {
    await newDoubao();
    assert.equal(await js(`${secret}.value`), '');
    assert.equal(await js(`${secret}.required`), true);
    assert.equal(await js(`${secret}.autocomplete`), 'new-password');
    assert.equal(await js('document.getElementById("form").autocomplete'), 'off');
    // Reusing an existing ID in a new draft must not allow probing with its saved key.
    await js(`document.getElementById('profile-id').value='doubao-1';
      document.getElementById('profile-title').value='豆包测试';
      document.getElementById('test').click();
      document.getElementById('form').requestSubmit();`);
    await sleep(100);
    assert.equal(await js('window.profileProbes.length'), 0);
    assert.equal(await js('window.profileWrites.length'), id === 'doubao-1' ? 0 : 1);
    assert.equal(await js(`${secret}.validity.valueMissing`), true);
    await js(`document.getElementById('profile-id').value=${JSON.stringify(id)};
      ${secret}.value=${JSON.stringify(key)};
      document.getElementById('form').requestSubmit();`);
    await wait(`document.querySelector('#profiles article[data-id="${id}"]') !== null`);
  }
  assert.deepEqual(await js('window.profileWrites.map(value=>value.configuration.apiKey)'), [
    'key-1',
    'key-2'
  ]);
  const endpoints = await js('window.profileWrites.map(value=>value.configuration.endpoint)');
  assert.equal(endpoints[0], endpoints[1]);
  await js(`Array.from(document.querySelectorAll('#profiles article[data-id="doubao-2"] button'))
    .find(button=>button.textContent==='修改').click();`);
  assert.equal(await js(`${secret}.value`), '');
  assert.equal(await js(`${secret}.required`), false);
  await js(`document.getElementById('profile-title').value='删除';
    document.getElementById('form').requestSubmit();`);
  await wait(`document.querySelector('#profiles article[data-id="doubao-2"] h3')
    .textContent.includes('删除')`);
  await require('./language_ui.cjs').language(window, 'en');
  assert.equal(
    await js(
      'document.querySelector(\'#profiles article[data-id="doubao-2"] h3 [translate="no"]\').textContent'
    ),
    '删除',
    'User profile title must not be translated'
  );
  await require('./language_ui.cjs').language(window, 'zh-CN');
  assert.equal(await js('window.profileWrites.at(-1).configuration.apiKey'), undefined);
  // Cancelled input and provider changes must not leak into another editor.
  await newDoubao();
  await js(`${secret}.value='cancelled-key';document.getElementById('cancel').click();`);
  await newDoubao();
  assert.equal(await js(`${secret}.value`), '');
  await js(`${secret}.value='discarded-key';
    document.getElementById('provider').value='bailian_qwen_asr';
    document.getElementById('provider').dispatchEvent(new Event('change'));`);
  assert.equal(await js(`${secret}.value`), '');
  assert.equal(await js(`${secret}.required`), true);
  console.log(
    'PASS Portal profile editor: same endpoint, independent keys, empty new keys, validation, edit/cancel/provider reset'
  );
}
run()
  .then(() => finish(0))
  .catch((error) => {
    console.error(error);
    finish(1);
  });
async function finish(code) {
  if (window) window.destroy();
  if (server && server.exitCode === null) {
    const exited = once(server, 'exit');
    server.kill('SIGINT');
    await exited;
  }
  // Chromium still holds profile files while Electron is running on Windows.
  if (process.platform !== 'win32') fs.rmSync(temporary, { recursive: true, force: true });
  app.exit(code);
}
