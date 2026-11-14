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
    ['tests/serve_management_ui.py', '--usage-fixture'],
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
  assert.equal(
    await js('document.getElementById("proxy-password").value'),
    'fictional-proxy-password'
  );
  assert.equal(
    await js('document.getElementById("proxy-save").textContent'),
    'Save proxy settings'
  );
  await js(`document.getElementById('proxy-form').requestSubmit();`);
  await wait('document.getElementById("proxy-password").value === ""');
  assert.equal(await js('document.getElementById("proxy-update-auth").checked'), false);
  await js(`document.getElementById('refresh').click();`);
  await wait('!document.getElementById("workspace").hidden');
  await wait(
    'document.getElementById("proxy-auth-status").textContent === "Proxy authentication saved"'
  );
  assert.equal(
    await js('document.getElementById("proxy-url").value'),
    'https://proxy.example:8443'
  );
  await js(`document.getElementById('proxy-url').value='http://127.0.0.1:1';
    document.getElementById('proxy-url').dispatchEvent(new Event('input', {bubbles:true}));
    document.getElementById('proxy-test').click();`);
  await wait('document.getElementById("proxy-result").dataset.state === "error"');
  assert.ok(
    await js('document.getElementById("proxy-result").textContent.includes("Proxy unavailable")')
  );
  await js(`document.getElementById('proxy-url').value='https://proxy.example:8443';
    document.getElementById('proxy-url').dispatchEvent(new Event('input', {bubbles:true}));`);
  assert.equal(await js('document.getElementById("proxy-result").dataset.state'), '');
  await require('./language_ui.cjs').language(window, 'zh-CN');
  // Observe actual requests, while still sending them to the real management API.
  await js(`window.profileWrites=[];window.profileProbes=[];
    const originalFetch=window.fetch;
    window.fetch=async (url, options)=>{
      if (url.endsWith('/test')) window.profileProbes.push(options.body);
      else if (url.includes('/profiles') && options?.body)
        window.profileWrites.push(JSON.parse(options.body));
      const response=await originalFetch(url, options);
      if (window.holdNextKeyRead && url === '/v1/admin/asr-keys' && options.method === 'GET') {
        window.holdNextKeyRead=false;
        await new Promise(resolve=>{window.releaseKeyRead=resolve;});
      }
      return response;
    };undefined;`);
  for (const [id, key] of [
    ['doubao-1', 'key-1'],
    ['doubao-2', 'key-2']
  ]) {
    await newDoubao();
    const silence = 'document.querySelector("#fields [name=silenceMs]")';
    assert.deepEqual(await js(`[${silence}.min, ${silence}.max, ${silence}.value]`),
      ['300', '5000', '5000']);
    await js(`${silence}.value='6000'`);
    assert.equal(await js(`${silence}.validity.rangeOverflow`), true);
    await js(`${silence}.value='200'`);
    assert.equal(await js(`${silence}.validity.rangeUnderflow`), true);
    await js(`${silence}.value='1200'`);
    await require('./language_ui.cjs').language(window, 'en');
    assert.ok(await js('document.getElementById("fields").textContent.includes("within 300–5000 ms")'));
    assert.equal(await js(`${silence}.value`), '1200');
    await require('./language_ui.cjs').language(window, 'zh-CN');
    assert.ok(await js('document.getElementById("fields").textContent.includes("允许 300–5000 毫秒")'));
    await js(`${silence}.value='5000'`);
    assert.equal(await js('document.querySelector("#fields [name=useProxy]").checked'), false);
    if (id === 'doubao-1')
      await js('document.querySelector("#fields [name=useProxy]").checked = true');
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
  assert.deepEqual(await js('window.profileWrites.map(value=>value.configuration.useProxy)'), [
    true,
    false
  ]);
  assert.equal(endpoints[0], endpoints[1]);
  const firstCard = 'document.querySelector(\'#profiles article[data-id="doubao-1"]\')';
  await js(`window.quotaToggle=${firstCard}.querySelector('.actions input[role=switch]');
    window.quotaToggle.click();`);
  await wait(`${firstCard}.querySelector('h3').textContent.includes('手动停用')`);
  await wait('!window.quotaToggle.disabled');
  assert.equal(await js(`${firstCard}.querySelector('.actions input[role=switch]').checked`), false);
  // Let the new card be usable while the toggle's unrelated key refresh is pending.
  // A late toggle completion must not erase the newer probe result.
  await js(`window.holdNextKeyRead=true;
    window.quotaToggle=${firstCard}.querySelector('.actions input[role=switch]');
    window.quotaToggle.click();`);
  await wait(`${firstCard}.querySelector('h3').textContent.includes('启用')`);
  await wait('typeof window.releaseKeyRead === "function"');
  assert.equal(await js(`${firstCard}.querySelector('[name=endpoint]').readOnly`), true);
  assert.equal(await js(`${firstCard}.querySelector('[name=useProxy]').disabled`), true);
  await js(`${firstCard}.querySelector('.profile-edit').click();
    ${firstCard}.querySelector('[name=useProxy]').click();
    [...${firstCard}.querySelectorAll('button')].find(button=>button.textContent==='测试上游连接').click();`);
  await wait(`${firstCard}.querySelector('.probe-result').dataset.state === 'success'`);
  await js('window.releaseKeyRead();');
  await wait('!window.quotaToggle.disabled');
  assert.equal(
    await js(`${firstCard}.querySelector('.probe-result').dataset.state`),
    'success',
    'Finishing an older quota refresh must retain the newer probe feedback'
  );
  assert.equal(await js('JSON.parse(window.profileProbes.at(-1)).configuration.useProxy'), false);
  assert.ok(
    await js(`${firstCard}.querySelector('.probe-result').textContent.includes('直接连接')`)
  );
  await js(
    `[...${firstCard}.querySelectorAll('button')].find(button=>button.textContent==='取消').click();`
  );
  assert.equal(await js(`${firstCard}.querySelector('[name=useProxy]').checked`), true);
  await js(
    `[...${firstCard}.querySelectorAll('button')].find(button=>button.textContent==='测试上游连接').click();`
  );
  await wait(`${firstCard}.querySelector('.probe-result').dataset.state === 'success'`);
  assert.equal(await js('JSON.parse(window.profileProbes.at(-1)).configuration.useProxy'), true);
  assert.ok(
    await js(`${firstCard}.querySelector('.probe-result').textContent.includes('通过 Proxy')`)
  );
  await js(`Array.from(document.querySelectorAll('#profiles article[data-id="doubao-2"] button'))
    .find(button=>button.textContent==='修改').click();`);
  const editing = 'document.querySelector("#profiles .editing form")';
  const inlineSecret = `${editing}.querySelector('[name=apiKey]')`;
  assert.equal(await js(`${inlineSecret}.value`), '');
  assert.equal(await js(`${inlineSecret}.required`), false);
  await js(`${editing}.querySelector('input[maxlength="200"]').value='删除';
    ${editing}.requestSubmit();`);
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
  assert.deepEqual(await js(`(()=>{const field=document.querySelector('#fields [name=silenceMs]');
    return [field.min, field.max, field.value];})()`), ['200', '6000', '6000']);
  assert.equal(
    await js('document.querySelector("#fields input[name=model]").value'),
    'qwen-audio-3.1-asr-flash-streaming'
  );
  assert.equal(
    await js('document.querySelector("#fields [name=previewIntervalMs]") === null'),
    true
  );
  assert.ok(
    (await js('document.querySelector("#fields input[name=endpoint]").value')).startsWith('wss://')
  );
  await js(`document.getElementById('provider').value='boson_realtime';
    document.getElementById('provider').dispatchEvent(new Event('change'));`);
  assert.equal(await js(`${secret}.value`), '');
  assert.equal(
    await js('document.querySelector("#fields input[name=model]").value'),
    'higgs-stt-3.1'
  );
  assert.equal(await js('document.querySelector("#fields input[name=endpoint]").readOnly'), true);
  await js(`document.getElementById('profile-id').value='boson-1';
    document.getElementById('profile-title').value='Boson 测试';
    ${secret}.value='fictional-boson-key';
    document.querySelector('#fields [name=language]').value='zh';`);
  await require('./language_ui.cjs').language(window, 'en');
  assert.equal(await js('document.querySelector("#fields [name=language]").value'), 'zh');
  assert.ok(
    await js(
      'document.getElementById("fields").textContent.includes("without word-by-word previews")'
    )
  );
  await js(`document.getElementById('form').requestSubmit();`);
  await wait(`document.querySelector('#profiles article[data-id="boson-1"]') !== null`);
  assert.equal(await js('window.profileWrites.at(-1).provider'), 'boson_realtime');
  await js(`Array.from(document.querySelectorAll('#profiles article[data-id="boson-1"] button'))
    .find(button=>button.textContent==='Edit').click();`);
  assert.equal(await js(`${inlineSecret}.value`), '');
  assert.equal(await js(`${inlineSecret}.required`), false);
  await js(`${editing}.requestSubmit();`);
  await wait('document.querySelector("#profiles .editing") === null');
  assert.equal(await js('window.profileWrites.at(-1).configuration.apiKey'), undefined);
  await js(`document.getElementById('new').click();
    document.getElementById('provider').value='soniox_realtime';
    document.getElementById('provider').dispatchEvent(new Event('change'));`);
  assert.equal(await js('document.querySelector("#fields input[name=model]").value'), 'stt-rt-v6');
  assert.equal(await js('document.querySelector("#fields [name=language]").value'), 'zh,en');
  assert.equal(await js(`${secret}.value`), '');
  await js(`document.getElementById('profile-id').value='soniox-1';
    document.getElementById('profile-title').value='Soniox 测试';
    ${secret}.value='fictional-soniox-key';
    document.querySelector('#fields [name=language]').value='zh';`);
  await require('./language_ui.cjs').language(window, 'zh-CN');
  assert.equal(await js('document.querySelector("#fields [name=language]").value'), 'zh');
  await require('./language_ui.cjs').language(window, 'en');
  assert.ok(
    await js('document.getElementById("fields").textContent.includes("Maximum endpoint delay")')
  );
  await js(`document.getElementById('form').requestSubmit();`);
  await wait(`document.querySelector('#profiles article[data-id="soniox-1"]') !== null`);
  assert.equal(await js('window.profileWrites.at(-1).provider'), 'soniox_realtime');
  for (const [provider, id, mode, expected] of [
    ['openai_file', 'file-json', 'json', 'Recognition after stopping'],
    ['openai_file', 'file-sse', 'sse', 'Incremental text after stopping'],
    ['openai_realtime', 'live', 'gpt-live-transcribe', 'Preview during recording'],
    ['openai_realtime', 'commit', 'gpt-transcribe', 'Incremental text after commit']
  ]) {
    await js(`document.getElementById('new').click();
      document.getElementById('provider').value=${JSON.stringify(provider)};
      document.getElementById('provider').dispatchEvent(new Event('change'));
      document.getElementById('profile-id').value=${JSON.stringify(id)};
      document.getElementById('profile-title').value='用户提示🙂';
      ${secret}.value='fictional-openai-key';
      document.querySelector('#fields [name=languages]').value='zh,en';
      document.querySelector('#fields [name=prompt]').value='保留用户内容🙂';
      document.querySelector('#fields [name=${provider === 'openai_file' ? 'responseMode' : 'model'}]').value=${JSON.stringify(mode)};`);
    assert.equal(await js('document.querySelector("#fields [name=endpoint]").readOnly'), true);
    await require('./language_ui.cjs').language(window, 'zh-CN');
    await require('./language_ui.cjs').language(window, 'en');
    assert.equal(await js('document.querySelector("#fields [name=prompt]").value'), '保留用户内容🙂');
    assert.equal(await js(`${secret}.value`), 'fictional-openai-key');
    if (id === 'commit') {
      await js(`document.querySelector('#fields [name=delay]').value='low';
        document.getElementById('form').requestSubmit();`);
      await wait(`document.getElementById('status').textContent.includes('Delay settings apply only')`);
      await js(`document.querySelector('#fields [name=delay]').value='';`);
    }
    await js(`document.getElementById('form').requestSubmit();`);
    const card = `document.querySelector('#profiles article[data-id="${id}"]')`;
    await wait(`${card} !== null`);
    await wait(`${card}.querySelector('.recognition-capability').textContent.includes(${JSON.stringify(expected)})`);
    assert.ok(await js(`${card}.querySelector('.recognition-capability').textContent.includes('Recording limit: 300 s')`));
    await js(`${card}.querySelector('.profile-edit').click();`);
    assert.equal(await js(`${inlineSecret}.value`), '');
    await js(`${editing}.requestSubmit();`);
    await wait('document.querySelector("#profiles .editing") === null');
    assert.equal(await js('window.profileWrites.at(-1).configuration.apiKey'), undefined);
  }
  await js(`document.getElementById('tab-usage').click();`);
  await wait(`document.getElementById('usage-summary').textContent.includes('Provider-reported duration')`);
  assert.ok(await js(`document.getElementById('usage-summary').textContent.includes('12.5')`));
  assert.ok(await js(`document.getElementById('usage-summary').textContent.includes('Scopes with unknown usage')`));
  await require('./language_ui.cjs').language(window, 'zh-CN');
  assert.ok(await js(`document.getElementById('usage-summary').textContent.includes('用量未知作用域')`));
  await js(`document.getElementById('tab-upstream').click();`);
  await require('./language_ui.cjs').language(window, 'zh-CN');
  window.setContentSize(1180, 900);
  assert.ok(
    await js(`${firstCard}.querySelector('.profile-form').textContent.includes('配置 ID')`)
  );
  assert.ok(
    await js(`${firstCard}.querySelector('.profile-form').textContent.includes('测试上游连接')`)
  );
  await js(`document.getElementById('admin-body').scrollTop=0;`);
  fs.writeFileSync(
    path.join(root, 'test-results/upstream-panels-zh.png'),
    (await window.webContents.capturePage()).toPNG()
  );
  await require('./language_ui.cjs').language(window, 'en');
  fs.writeFileSync(
    path.join(root, 'test-results/upstream-panels-en.png'),
    (await window.webContents.capturePage()).toPNG()
  );
  window.setContentSize(390, 844);
  assert.equal(await js('document.documentElement.scrollWidth <= innerWidth'), true);
  await js(`window.reloadMarker=true;document.getElementById('refresh').click();`);
  await wait('!document.getElementById("workspace").hidden && window.reloadMarker === undefined');
  assert.equal(
    await js('document.getElementById("tab-upstream").getAttribute("aria-selected")'),
    'true'
  );
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
