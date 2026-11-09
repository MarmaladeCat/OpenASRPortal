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
  await js(`document.getElementById('tab-proxy').click();
    document.getElementById('proxy-url').value='https://proxy.example:8443';
    document.getElementById('proxy-update-auth').click();
    document.getElementById('proxy-username').value='fictional-user';
    document.getElementById('proxy-password').value='fictional-proxy-password';`);
  await require('./language_ui.cjs').language(window, 'en');
  assert.equal(await js('document.getElementById("proxy-password").value'), 'fictional-proxy-password');
  assert.equal(await js('document.getElementById("proxy-save").textContent'), 'Save proxy settings');
  await js(`document.getElementById('proxy-form').requestSubmit();`);
  await wait('document.getElementById("proxy-password").value === ""');
  assert.equal(await js('document.getElementById("proxy-update-auth").checked'), false);
  await js(`document.getElementById('refresh').click();`);
  await wait('document.getElementById("proxy-auth-status").textContent === "Proxy authentication saved"');
  assert.equal(await js('document.getElementById("proxy-url").value'), 'https://proxy.example:8443');
  await require('./language_ui.cjs').language(window, 'zh-CN');
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
    assert.equal(await js('document.querySelector("#fields [name=useProxy]").checked'), false);
    if (id === 'doubao-1') await js('document.querySelector("#fields [name=useProxy]").checked = true');
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
  assert.deepEqual(await js('window.profileWrites.map(value=>value.configuration.useProxy)'), [true, false]);
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
  assert.equal(await js('document.querySelector("#fields input[name=model]").value'), 'qwen-audio-3.1-asr-flash-streaming');
  assert.equal(await js('document.querySelector("#fields [name=previewIntervalMs]") === null'), true);
  assert.ok((await js('document.querySelector("#fields input[name=endpoint]").value')).startsWith('wss://'));
  await js(`document.getElementById('provider').value='boson_realtime';
    document.getElementById('provider').dispatchEvent(new Event('change'));`);
  assert.equal(await js(`${secret}.value`), '');
  assert.equal(await js('document.querySelector("#fields input[name=model]").value'), 'higgs-stt-3.1');
  assert.equal(await js('document.querySelector("#fields input[name=endpoint]").readOnly'), true);
  await js(`document.getElementById('profile-id').value='boson-1';
    document.getElementById('profile-title').value='Boson 测试';
    ${secret}.value='fictional-boson-key';
    document.querySelector('#fields input[name=language]').value='zh';`);
  await require('./language_ui.cjs').language(window, 'en');
  assert.equal(await js('document.querySelector("#fields input[name=language]").value'), 'zh');
  assert.ok(await js('document.getElementById("fields").textContent.includes("without word-by-word previews")'));
  await js(`document.getElementById('form').requestSubmit();`);
  await wait(`document.querySelector('#profiles article[data-id="boson-1"]') !== null`);
  assert.equal(await js('window.profileWrites.at(-1).provider'), 'boson_realtime');
  await js(`Array.from(document.querySelectorAll('#profiles article[data-id="boson-1"] button'))
    .find(button=>button.textContent==='Edit').click();`);
  assert.equal(await js(`${secret}.value`), '');
  assert.equal(await js(`${secret}.required`), false);
  await js(`document.getElementById('form').requestSubmit();`);
  await wait('document.getElementById("editor").hidden');
  assert.equal(await js('window.profileWrites.at(-1).configuration.apiKey'), undefined);
  await js(`document.getElementById('new').click();
    document.getElementById('provider').value='soniox_realtime';
    document.getElementById('provider').dispatchEvent(new Event('change'));`);
  assert.equal(await js('document.querySelector("#fields input[name=model]").value'), 'stt-rt-v6');
  assert.equal(await js(`${secret}.value`), '');
  await js(`document.getElementById('profile-id').value='soniox-1';
    document.getElementById('profile-title').value='Soniox 测试';
    ${secret}.value='fictional-soniox-key';
    document.querySelector('#fields input[name=language]').value='zh';`);
  await require('./language_ui.cjs').language(window, 'zh-CN');
  assert.equal(await js('document.querySelector("#fields input[name=language]").value'), 'zh');
  await require('./language_ui.cjs').language(window, 'en');
  assert.ok(await js('document.getElementById("fields").textContent.includes("Maximum endpoint delay")'));
  await js(`document.getElementById('form').requestSubmit();`);
  await wait(`document.querySelector('#profiles article[data-id="soniox-1"]') !== null`);
  assert.equal(await js('window.profileWrites.at(-1).provider'), 'soniox_realtime');
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
