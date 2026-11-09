const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

async function language(window, value) {
  await window.webContents.executeJavaScript(`import('/admin/i18n.mjs').then(() => {
    const control = document.querySelector('[data-language-select]');
    control.value = '${value}';
    control.dispatchEvent(new Event('change'));
    return new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  })`);
}

async function verifyLanguages(window) {
  const js = (code) => window.webContents.executeJavaScript(code);
  await js(`document.getElementById('key-title').value='删除';`);
  await language(window, 'en');
  assert.equal(await js('document.getElementById("key-title").value'), '删除');
  for (const page of ['overview', 'upstream', 'downstream', 'usage', 'public', 'access']) {
    await js(`document.querySelector('[data-page="${page}"]').click()`);
    await language(window, 'en');
    const untranslated = await js(`(() => {
      const result=[];
      const walker=document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      while(walker.nextNode()) {
        const node=walker.currentNode, parent=node.parentElement;
        if (!parent || parent.closest('script,style,textarea,[translate="no"],[data-user-content]') || !parent.getClientRects().length) continue;
        if (/[\u3400-\u9fff]/.test(node.data)) result.push(node.data.trim());
      }
      return result;
    })()`);
    assert.deepEqual(untranslated, [], page + ': untranslated visible text');
  }
  await js(`document.querySelector('[data-page="overview"]').click()`);
  await language(window, 'en');
  fs.writeFileSync(
    path.join(__dirname, '../test-results/admin-english.png'),
    (await window.webContents.capturePage()).toPNG()
  );
  const size = window.getContentSize();
  window.setContentSize(390, 844);
  await language(window, 'en');
  assert.equal(
    await js('document.documentElement.scrollWidth <= innerWidth'),
    true,
    'English mobile width'
  );
  fs.writeFileSync(
    path.join(__dirname, '../test-results/admin-english-mobile.png'),
    (await window.webContents.capturePage()).toPNG()
  );
  window.setContentSize(...size);
  await language(window, 'zh-CN');
  assert.equal(await js('document.getElementById("key-title").value'), '删除');
  await language(window, 'en');
  await window.loadURL(await js('location.href'));
  assert.equal(
    await js('import("/admin/i18n.mjs").then(() => document.documentElement.lang)'),
    'en',
    'Remember language after reload'
  );
  await language(window, 'zh-CN');
  await js(`document.getElementById('key-title').value='';`);
}

module.exports = { language, verifyLanguages };
