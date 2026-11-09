// 纯浏览器管理页：只调用 Management v1，提供商表单来自协议描述。
import { PersonalHotwords, wordIdentity } from './personal-hotwords.mjs';
import { userOption, userText } from './i18n.mjs';

const byId = (id) => document.getElementById(id);
let credential = sessionStorage.getItem('openasrportal-admin-session') || '',
  descriptor,
  profiles = [],
  current = null,
  defaultId = '',
  asrKeys = [];
const fields = new Map();
let proxyDirty = false;
function showProxy(value) {
  if (proxyDirty) return;
  byId('proxy-url').value = value?.url || '';
  byId('proxy-auth-status').textContent = value?.hasCredentials ? '已保存代理认证' : '未配置代理认证';
  byId('proxy-update-auth').checked = false;
  for (const id of ['proxy-username', 'proxy-password']) {
    byId(id).value = '';
    byId(id).disabled = true;
  }
}
let keyHotwordId = null,
  keyHotwordData,
  keyDictionaryCatalog,
  keyHotwordBusy = false,
  keyHotwordDirty = false;
let keyRecommendationWords = [],
  keyRecommendationPage = 0;
function keyHotwordsChanged(message = '个人表已编辑，保存此 Key 的热词设置后同步到客户端。') {
  keyHotwordDirty = true;
  renderKeyRecommendations();
  byId('key-hotwords-selection').textContent =
    '有未保存的修改；保存后更新 Portal 状态，下一轮录音生效。';
  status(message);
}
const keyPersonalTable = new PersonalHotwords('key-hotwords', {
  changed: keyHotwordsChanged,
  report: (message) => status(message, true),
  run: async (operation) => {
    if (!keyHotwordId || keyHotwordBusy) return;
    keyHotwordWorking(true);
    try {
      await operation();
    } catch (error) {
      status(error.message, true);
    } finally {
      keyHotwordWorking(false);
    }
  }
});
const usageTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
let usageBusy = false;
let usageAutoPeriod = true;
let publicCurrent = null,
  publicDirty = false,
  publicBusy = false,
  publicWords = [],
  publicPage = 0;

function seconds(value) {
  if (value === null || value === undefined) return '不限';
  if (value < 60) return value.toLocaleString(undefined, { maximumFractionDigits: 2 }) + ' 秒';
  const minutes = Math.floor(value / 60),
    remainder = Math.floor(value % 60);
  return minutes < 60
    ? `${minutes} 分 ${remainder} 秒`
    : `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分`;
}
function tokens(usage) {
  if (usage.tokens === null) return '未上报';
  const count = (usage.reportedTokens || 0).toLocaleString();
  return usage.unreportedRequests ? `${count}（${usage.unreportedRequests} 次未上报）` : count;
}
function quotaControls(scope, identity, quota, tokenSupported = true, revoked = false) {
  if (!quota) return null;
  const section = document.createElement('div');
  section.className = 'quota-controls';
  const usage = document.createElement('p');
  usage.className = 'quota-usage';
  usage.textContent = `累计${scope === 'profile' ? '上游请求音频' : '提交音频'}：${seconds(quota.usedSeconds)} · Token：${tokens(quota)} · 请求 ${quota.requests} 次`;
  const balance = document.createElement('p');
  balance.className = 'quota-balance';
  balance.textContent = `剩余：${seconds(quota.remainingSeconds)} · ${quota.remainingTokens === null ? 'Token 不限' : quota.remainingTokens.toLocaleString() + ' Token'}${quota.reservedSeconds ? ` · 当前音频预留 ${seconds(quota.reservedSeconds)}` : ''}`;
  if (quota.tokenBlocked) balance.textContent += ' · Token 未上报，计量已暂停';
  const form = document.createElement('form');
  form.className = 'quota-form';
  const field = (name, text, value, supported) => {
    const label = document.createElement('label');
    label.textContent = text;
    const input = document.createElement('input');
    input.type = 'number';
    input.name = name;
    input.min = '0';
    input.step = name === 'remainingTokens' ? '1' : 'any';
    input.placeholder = supported ? '留空表示不限额' : '此上游不提供 Token';
    input.value = value === null ? '' : String(value);
    input.dataset.original = input.value;
    input.disabled = revoked || !supported;
    input.setAttribute('aria-label', text);
    label.append(input);
    form.append(label);
    return input;
  };
  const duration = field(
    'remainingMinutes',
    '新的剩余时长（分钟）',
    quota.remainingSeconds === null ? null : quota.remainingSeconds / 60,
    true
  );
  const token = field('remainingTokens', '新的剩余 Token', quota.remainingTokens, tokenSupported);
  const button = document.createElement('button');
  button.type = 'submit';
  button.className = 'quota-save';
  button.textContent = '保存剩余额度';
  button.disabled = revoked;
  form.append(button);
  const hint = document.createElement('small');
  hint.textContent = '修改的是剩余额度，不是追加额度。留空为不限，0 为用尽；只保存改动的字段。';
  form.onsubmit = (event) => {
    event.preventDefault();
    action(async () => {
      const patch = {};
      if (duration.value !== duration.dataset.original)
        patch.remainingSeconds = duration.value === '' ? null : Number(duration.value) * 60;
      if (!token.disabled && token.value !== token.dataset.original) {
        if (token.value !== '' && !Number.isSafeInteger(Number(token.value)))
          throw new Error('Token 请输入可精确表示的非负整数');
        patch.remainingTokens = token.value === '' ? null : Number(token.value);
      }
      if (!Object.keys(patch).length) {
        status('没有修改剩余额度。');
        return;
      }
      button.disabled = true;
      try {
        const path =
          scope === 'key'
            ? `/v1/admin/asr-keys/${encodeURIComponent(identity)}/quota`
            : `/v1/admin/profiles/${encodeURIComponent(identity)}/quota`;
        await request(path, 'PATCH', patch);
        await refresh();
        status('剩余额度已更新，正在进行的会话也会使用新的限额。');
      } finally {
        button.disabled = revoked;
      }
    })();
  };
  section.append(usage, balance, form, hint);
  return section;
}

function fillUsageFilters() {
  for (const [id, items, title] of [
    ['usage-key', asrKeys, '全部 Key'],
    ['usage-profile', profiles, '全部上游']
  ]) {
    const select = byId(id),
      selected = select.value;
    select.replaceChildren(
      new Option(title, ''),
      ...items.map((item) => userOption(item.title, item.id))
    );
    select.value = selected;
  }
}

function usageTable(containerId, rows, firstTitle, name) {
  const container = byId(containerId);
  container.replaceChildren();
  if (!rows.length) {
    container.textContent = '所选时间范围内没有用量。';
    return;
  }
  const table = document.createElement('table'),
    head = document.createElement('tr');
  for (const title of [firstTitle, '下游音频', '上游请求音频', 'Token', '请求次数']) {
    const cell = document.createElement('th');
    cell.textContent = title;
    head.append(cell);
  }
  const header = document.createElement('thead');
  header.append(head);
  table.append(header);
  const body = document.createElement('tbody');
  for (const row of rows) {
    const tr = document.createElement('tr');
    for (const value of [
      name(row),
      seconds(row.audioSeconds),
      seconds(row.upstreamAudioSeconds),
      tokens(row),
      row.requests.toLocaleString()
    ]) {
      const cell = document.createElement('td');
      cell.textContent = value;
      if (!tr.children.length) cell.translate = false;
      tr.append(cell);
    }
    body.append(tr);
  }
  table.append(body);
  container.append(table);
}

async function refreshUsage() {
  if (usageBusy || !credential) return;
  if (!descriptor?.usagePath) {
    byId('usage-period').textContent = '请更新 Portal 服务以启用用量统计。';
    return;
  }
  usageBusy = true;
  try {
    if (usageAutoPeriod) resetUsagePeriod();
    const start = new Date(byId('usage-from').value),
      end = new Date(byId('usage-to').value);
    if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || start >= end)
      throw new Error('请选择有效的起止时间。');
    const query = new URLSearchParams({
      from: start.toISOString(),
      to: end.toISOString(),
      bucket: byId('usage-bucket').value,
      timezone: usageTimezone
    });
    if (byId('usage-key').value) query.set('keyId', byId('usage-key').value);
    if (byId('usage-profile').value) query.set('profileId', byId('usage-profile').value);
    const usage = await request(descriptor.usagePath + '?' + query);
    byId('usage-period').textContent =
      `时区：${usage.timezone} · 开始统计于 ${new Date(usage.trackingStartedAt * 1000).toLocaleString()} · ${usage.total.unreportedRequests} 次请求未上报 Token`;
    byId('usage-summary').replaceChildren();
    for (const [label, value] of [
      ['下游提交音频', seconds(usage.total.audioSeconds)],
      ['上游请求音频', seconds(usage.total.upstreamAudioSeconds)],
      ['上游报告 Token', tokens(usage.total)],
      ['上游请求次数', usage.total.requests.toLocaleString()]
    ]) {
      const card = document.createElement('article'),
        title = document.createElement('span'),
        count = document.createElement('strong');
      title.textContent = label;
      count.textContent = value;
      card.append(title, count);
      byId('usage-summary').append(card);
    }
    const date = (row) =>
      new Date(row.start).toLocaleString(undefined, { timeZone: usage.timezone });
    usageTable('usage-timeline', usage.timeline, '时间', date);
    usageTable(
      'usage-keys',
      usage.keys,
      '客户端 Key',
      (row) => asrKeys.find((key) => key.id === row.id)?.title || row.id
    );
    usageTable(
      'usage-profiles',
      usage.profiles,
      '上游 ASR',
      (row) =>
        profiles.find((profile) => profile.id === row.id)?.title ||
        (row.id.startsWith('draft:') ? '未保存测试 · ' + row.id.slice(6) : row.id)
    );
    const chart = byId('usage-chart');
    chart.replaceChildren();
    const maximum = usage.timeline.reduce((largest, row) => Math.max(largest, row.audioSeconds), 1);
    for (const row of usage.timeline) {
      const column = document.createElement('div'),
        bar = document.createElement('span');
      column.className = 'usage-column';
      column.title = `${date(row)} · ${seconds(row.audioSeconds)}`;
      bar.style.height = Math.max(2, (row.audioSeconds / maximum) * 96) + 'px';
      column.append(bar);
      chart.append(column);
    }
  } finally {
    usageBusy = false;
  }
}
function concealKeys() {
  byId('new-key-value').value = '';
  byId('new-key').hidden = true;
  document.querySelectorAll('.key-value').forEach((input) => {
    input.value = '';
    input.hidden = true;
  });
  document.querySelectorAll('.key-view').forEach((button) => {
    button.textContent = '查看 Key';
  });
}
function showPage(page, focus = true) {
  if (page !== 'downstream') concealKeys();
  document.querySelectorAll('#admin-nav [role=tab]').forEach((tab) => {
    const active = tab.dataset.page === page;
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    byId('page-' + tab.dataset.page).hidden = !active;
    if (active && focus) tab.focus();
  });
  byId('admin-body').scrollTop = 0;
  if (page === 'usage' && credential) action(refreshUsage)();
  if (page === 'public' && credential) action(refreshPublicDictionaries)();
}
function disconnect() {
  proxyDirty = false;
  showProxy(null);
  credential = '';
  sessionStorage.removeItem('openasrportal-admin-session');
  keyHotwordId = null;
  keyHotwordData = null;
  keyDictionaryCatalog = null;
  keyHotwordDirty = false;
  keyRecommendationWords = [];
  keyRecommendationPage = 0;
  byId('key-dictionary-search').value = '';
  byId('key-hotwords').hidden = true;
  keyPersonalTable.load({ manualTerms: [], excludedTerms: [] });
  byId('key-dictionary-recommendations').replaceChildren();
  byId('key-hotwords-personal').replaceChildren();
  concealKeys();
  byId('login').hidden = false;
  byId('workspace').hidden = true;
  byId('editor').hidden = true;
  byId('logout').hidden = true;
  byId('connection-badge').textContent = '未连接';
  fields.clear();
  byId('fields').replaceChildren();
  publicCurrent = null;
  publicDirty = false;
  publicWords = [];
  byId('public-content').value = '';
  byId('public-editor').hidden = true;
  byId('public-list').replaceChildren();
  byId('public-words').replaceChildren();
}
async function copyKey(value, input) {
  try {
    if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable');
    await navigator.clipboard.writeText(value);
    status('ASR Key 已复制，可填写到识别客户端。');
    return;
  } catch {}
  // Remote HTTP pages may not have the async Clipboard API. Keep the user's
  // click-driven copy available through the legacy API, otherwise select text.
  const previous = document.activeElement;
  const temporary = document.createElement('textarea');
  temporary.value = value;
  temporary.setAttribute('aria-label', '待复制 ASR Key');
  document.body.append(temporary);
  temporary.select();
  const copied = document.execCommand('copy');
  temporary.remove();
  previous?.focus();
  if (copied) status('ASR Key 已复制。');
  else {
    input.hidden = false;
    input.value = value;
    input.focus();
    input.select();
    status('浏览器限制自动复制，Key 已选中，请按 Ctrl+C。');
  }
}
function status(message, error = false) {
  byId('status').textContent = message;
  byId('status').classList.toggle('error', error);
}
function action(fn) {
  return () =>
    Promise.resolve()
      .then(fn)
      .catch((error) => status(error.message, true));
}
async function request(path, method = 'GET', body, anonymous = false) {
  const response = await fetch(path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(anonymous ? {} : { Authorization: 'Bearer ' + credential })
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    redirect: 'error'
  });
  const value = await response.json();
  if (response.status === 401 && !anonymous) disconnect();
  if (!response.ok) throw new Error(value.error?.message || `HTTP ${response.status}`);
  return value;
}
async function refresh() {
  descriptor = await request('/v1/admin/contract');
  if (descriptor.protocol !== 'OpenASRPortal.Management' || descriptor.version !== 1)
    throw new Error('不支持的管理协议版本');
  const listing = await request(descriptor.profilesPath);
  profiles = listing.profiles;
  defaultId = listing.defaultProfileId;
  showProxy(listing.proxy);
  byId('login').hidden = true;
  byId('workspace').hidden = false;
  byId('logout').hidden = false;
  byId('connection-badge').textContent = '管理已连接';
  byId('service-origin').value = location.origin;
  const selectedProvider = byId('provider').value;
  byId('provider').replaceChildren(
    ...descriptor.providers.map((provider) => new Option(provider.title, provider.id))
  );
  if (selectedProvider) byId('provider').value = selectedProvider;
  render();
  byId('profile-count').textContent = String(profiles.length);
  status(`已连接 · ${profiles.length} 个上游识别档案`);
  await refreshKeys();
  fillUsageFilters();
  await refreshUsage();
}

async function refreshKeys() {
  asrKeys = (await request('/v1/admin/asr-keys')).keys;
  byId('key-count').textContent = String(asrKeys.filter((key) => !key.revoked).length);
  byId('keys').replaceChildren();
  for (const key of asrKeys) {
    const card = document.createElement('article');
    card.className = 'profile';
    card.dataset.id = key.id;
    const row = document.createElement('div');
    row.className = 'key-row';
    const title = document.createElement('h3');
    title.textContent = key.title;
    title.translate = false;
    const badge = document.createElement('span');
    badge.className = 'key-state' + (key.revoked ? ' revoked' : '');
    badge.textContent = key.revoked
      ? '已撤销'
      : key.quota?.tokenBlocked
        ? '计量暂停'
        : key.quota?.exhausted
          ? '额度已用尽'
          : '识别权限';
    row.append(title, badge);
    const detail = document.createElement('p');
    detail.textContent = `${key.prefix}… · ${key.revoked ? '已撤销' : '可用于识别'} · ${new Date(key.createdAt * 1000).toLocaleString()}`;
    const value = document.createElement('input');
    value.className = 'key-value';
    value.readOnly = true;
    value.hidden = true;
    value.spellcheck = false;
    value.setAttribute('aria-label', key.title + ' 的完整 ASR Key');
    const actions = document.createElement('div');
    actions.className = 'actions';
    const view = document.createElement('button');
    view.className = 'key-view';
    view.textContent = '查看 Key';
    view.disabled = !key.canReveal;
    view.title = key.revoked
      ? '已撤销'
      : key.canReveal
        ? '使用管理权限查看'
        : '旧版仅有哈希，需要原值恢复或重新派生';
    view.onclick = action(async () => {
      if (!value.hidden) {
        value.value = '';
        value.hidden = true;
        view.textContent = '查看 Key';
        return;
      }
      const result = await request(`/v1/admin/asr-keys/${encodeURIComponent(key.id)}/secret`);
      value.value = result.key;
      value.hidden = false;
      view.textContent = '隐藏 Key';
    });
    const copy = document.createElement('button');
    copy.className = 'key-copy';
    copy.textContent = '复制 Key';
    copy.disabled = !key.canReveal;
    copy.onclick = action(async () => {
      const result = await request(`/v1/admin/asr-keys/${encodeURIComponent(key.id)}/secret`);
      await copyKey(result.key, value);
    });
    const revoke = document.createElement('button');
    revoke.className = 'danger';
    revoke.textContent = key.revoked ? '已撤销' : '撤销此 Key';
    revoke.disabled = key.revoked;
    revoke.onclick = action(async () => {
      await request(`/v1/admin/asr-keys/${encodeURIComponent(key.id)}`, 'DELETE');
      await refreshKeys();
      status('Key 已撤销，属于该 Key 的识别会话已取消');
    });
    const vocabulary = document.createElement('button');
    vocabulary.className = 'key-hotwords-open';
    vocabulary.textContent = '管理用户热词表';
    vocabulary.disabled = key.revoked || !descriptor.keyHotwordsPath;
    vocabulary.onclick = action(() => openKeyHotwords(key));
    actions.append(view, copy, vocabulary, revoke);
    card.append(row, detail, value, actions);
    const quota = quotaControls('key', key.id, key.quota, true, key.revoked);
    if (quota) card.append(quota);
    byId('keys').append(card);
  }
  if (keyHotwordId && !asrKeys.some((key) => key.id === keyHotwordId && !key.revoked)) {
    keyHotwordId = null;
    keyHotwordData = null;
    keyHotwordDirty = false;
    byId('key-hotwords').hidden = true;
  }
}

const publicPath = () => descriptor.publicDictionariesPath;
function publicWorking(value) {
  publicBusy = value;
  document
    .querySelectorAll(
      '#page-public button, #page-public input, #page-public textarea, #page-public select'
    )
    .forEach((field) => (field.disabled = value));
  if (!value) renderPublicWords();
}
async function refreshPublicDictionaries() {
  if (publicBusy) return;
  publicWorking(true);
  try {
    const [listing, catalog] = await Promise.all([
      request(publicPath()),
      request(descriptor.hotwordCatalogPath)
    ]);
    byId('public-source').replaceChildren(
      new Option('选择联网来源', ''),
      ...catalog.sources
        .filter((source) => source.kind === 'external')
        .map((source) => userOption(source.title, source.id))
    );
    byId('public-list').replaceChildren();
    for (const dictionary of listing.dictionaries) {
      const card = document.createElement('article');
      card.className = 'profile';
      card.dataset.id = dictionary.id;
      const title = document.createElement('h3');
      title.append(
        userText(dictionary.title),
        ` · ${dictionary.wordCount} 词 · ${dictionary.enabled ? '已发布' : '未发布'}`
      );
      const detail = document.createElement('p');
      detail.append(
        dictionary.description ? userText(dictionary.description) : '无说明',
        ` · 版本 ${dictionary.revision} · `,
        dictionary.license ? userText(dictionary.license) : '未填写来源',
        ' · ' + new Date(dictionary.updatedAt * 1000).toLocaleString()
      );
      const view = document.createElement('button');
      view.className = 'public-open';
      view.textContent = '查看 / 修改';
      view.onclick = action(() => openPublicDictionary(dictionary.id));
      const download = document.createElement('button');
      download.className = 'public-download';
      download.textContent = '下载 JSON';
      download.onclick = action(async () => {
        const value = await request(publicPath() + '/' + encodeURIComponent(dictionary.id));
        const url = URL.createObjectURL(
          new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' })
        );
        const link = document.createElement('a');
        link.href = url;
        link.download = dictionary.id + '.json';
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      });
      const remove = document.createElement('button');
      remove.className = 'public-delete';
      remove.textContent = '删除';
      remove.onclick = action(async () => {
        if (publicDirty || publicBusy) {
          status('请先保存或取消当前公共表编辑。', true);
          return;
        }
        publicWorking(true);
        try {
          await request(publicPath() + '/' + encodeURIComponent(dictionary.id), 'DELETE', {
            revision: dictionary.revision
          });
          if (publicCurrent?.id === dictionary.id) byId('public-editor').hidden = true;
          status('公共表已删除；已保存的个人热词保留。');
        } finally {
          publicWorking(false);
        }
        await refreshPublicDictionaries();
      });
      const actions = document.createElement('div');
      actions.className = 'actions';
      actions.append(view, download, remove);
      card.append(title, detail, actions);
      byId('public-list').append(card);
    }
    if (!listing.dictionaries.length)
      byId('public-list').textContent = '暂无公共表，可新增或导入。';
  } finally {
    publicWorking(false);
  }
}
function wordsToTSV(words) {
  return (
    'text\tfrequency\tweight\n' +
    words.map((word) => `${word.text}\t${word.frequency || 0}\t${word.weight || 4}`).join('\n')
  );
}
function renderPublicWords() {
  const query = byId('public-search').value.normalize('NFKC').toLowerCase();
  const words = publicWords.filter((word) => word.text.toLowerCase().includes(query));
  const pages = Math.max(1, Math.ceil(words.length / 50));
  publicPage = Math.min(publicPage, pages - 1);
  byId('public-count').textContent = `${words.length} 词 · 第 ${publicPage + 1} / ${pages} 页`;
  byId('public-words').replaceChildren();
  for (const word of words.slice(publicPage * 50, (publicPage + 1) * 50)) {
    const row = document.createElement('p');
    row.append(userText(word.text), ` · 权重 ${word.weight} · 来源词频 ${word.frequency}`);
    byId('public-words').append(row);
  }
  byId('public-prev').disabled = publicBusy || publicPage === 0;
  byId('public-next').disabled = publicBusy || publicPage >= pages - 1;
}
function showPublicPreview(value) {
  publicWords = value.words;
  publicPage = 0;
  byId('public-search').value = '';
  byId('public-report').textContent = reportDictionary(value.report);
  renderPublicWords();
}
function populatePublicDictionary(value) {
  publicCurrent = value;
  publicDirty = false;
  byId('public-editor').hidden = false;
  byId('public-editor-title').textContent = value ? '查看 / 修改公共热词表' : '新增公共热词表';
  for (const name of ['id', 'title', 'description', 'homepage', 'license'])
    byId('public-' + name).value = value?.[name] || '';
  byId('public-enabled').checked = value?.enabled ?? true;
  byId('public-file').value = '';
  byId('public-format').value = value ? 'tsv' : 'auto';
  byId('public-content').value = value ? wordsToTSV(value.words) : '';
  publicWords = [];
  byId('public-report').textContent = '';
  if (value) showPublicPreview(value);
  else renderPublicWords();
  byId('public-editor').scrollIntoView({ behavior: 'smooth' });
}
async function openPublicDictionary(identity) {
  if (publicBusy || publicDirty) {
    status('请先保存或取消当前公共表编辑。', true);
    return;
  }
  publicWorking(true);
  try {
    populatePublicDictionary(await request(publicPath() + '/' + encodeURIComponent(identity)));
  } finally {
    publicWorking(false);
  }
}
byId('public-new').onclick = () => {
  if (publicBusy || publicDirty) {
    status('请先保存或取消当前公共表编辑。', true);
    return;
  }
  populatePublicDictionary(null);
};
byId('public-refresh').onclick = action(refreshPublicDictionaries);
byId('public-cancel').onclick = () => {
  publicDirty = false;
  publicCurrent = null;
  byId('public-editor').hidden = true;
};
document.querySelectorAll('#public-form input, #public-form textarea, #public-form select').forEach(
  (field) =>
    (field.oninput = () => {
      publicDirty = true;
    })
);
byId('public-preview').onclick = action(async () => {
  if (publicBusy) return;
  publicWorking(true);
  try {
    showPublicPreview(
      await request(publicPath(), 'POST', {
        preview: true,
        content: byId('public-content').value,
        format: byId('public-format').value
      })
    );
  } finally {
    publicWorking(false);
  }
});
byId('public-file').onchange = action(async () => {
  const file = byId('public-file').files[0];
  if (!file) return;
  if (file.size > 4 * 1024 * 1024) throw new Error('文件最多 4 MiB，请拆分大词库');
  publicWorking(true);
  try {
    byId('public-content').value = new TextDecoder('utf-8', { fatal: true }).decode(
      await file.arrayBuffer()
    );
    byId('public-format').value = 'auto';
    if (!byId('public-title').value) byId('public-title').value = file.name.slice(0, 100);
    publicDirty = true;
    showPublicPreview(
      await request(publicPath(), 'POST', {
        preview: true,
        content: byId('public-content').value,
        format: 'auto'
      })
    );
    status('文件已载入并解析，保存后发布到公共推荐目录。');
  } finally {
    publicWorking(false);
  }
});
byId('public-online').onclick = action(async () => {
  const sourceId = byId('public-source').value;
  if (!sourceId) throw new Error('请选择联网来源');
  if (publicBusy) return;
  publicWorking(true);
  try {
    const result = await request(publicPath(), 'POST', { sourceId, preview: true });
    byId('public-content').value = wordsToTSV(result.words);
    byId('public-format').value = 'tsv';
    for (const name of ['title', 'description', 'homepage', 'license'])
      if (!byId('public-' + name).value) byId('public-' + name).value = result.source[name] || '';
    publicDirty = true;
    showPublicPreview(result);
    status('联网词库已载入，可修改正文后保存为公共表。');
  } finally {
    publicWorking(false);
  }
});
byId('public-form').onsubmit = (event) => {
  event.preventDefault();
  if (publicBusy) return;
  action(async () => {
    publicWorking(true);
    try {
      const body = {
        content: byId('public-content').value,
        format: byId('public-format').value,
        enabled: byId('public-enabled').checked
      };
      for (const name of ['title', 'description', 'homepage', 'license'])
        body[name] = byId('public-' + name).value;
      if (publicCurrent) body.revision = publicCurrent.revision;
      const saved = await request(
        publicPath() + (publicCurrent ? '/' + encodeURIComponent(publicCurrent.id) : ''),
        publicCurrent ? 'PATCH' : 'POST',
        body
      );
      populatePublicDictionary(saved);
      status('公共热词表已保存，客户端刷新推荐目录即可下载。');
    } finally {
      publicWorking(false);
    }
    await refreshPublicDictionaries();
  })();
};
byId('public-search').oninput = () => {
  publicPage = 0;
  renderPublicWords();
};
byId('public-prev').onclick = () => {
  publicPage--;
  renderPublicWords();
};
byId('public-next').onclick = () => {
  publicPage++;
  renderPublicWords();
};
window.addEventListener('beforeunload', (event) => {
  if (publicDirty || keyHotwordDirty) {
    event.preventDefault();
    event.returnValue = '';
  }
});

function keyHotwordPath(identity = keyHotwordId) {
  return descriptor.keyHotwordsPath.replace('{id}', encodeURIComponent(identity));
}
async function openKeyHotwords(key) {
  if (keyHotwordBusy) return;
  if (keyHotwordDirty) {
    status('请先保存当前热词，或刷新以放弃编辑。', true);
    return;
  }
  keyHotwordId = key.id;
  byId('key-hotwords').hidden = true;
  keyHotwordWorking(true);
  try {
    const [value, catalog] = await Promise.all([
      request(keyHotwordPath(key.id)),
      request(descriptor.hotwordCatalogPath)
    ]);
    if (keyHotwordId !== key.id) return;
    keyDictionaryCatalog = catalog;
    keyRecommendationWords = [];
    keyRecommendationPage = 0;
    byId('key-dictionary-search').value = '';
    byId('key-hotwords-title').replaceChildren(userText(key.title), ' · 用户热词表');
    byId('key-hotwords').hidden = false;
    byId('key-dictionary-report').textContent = '';
    byId('key-dictionary-source-note').textContent = '';
    byId('key-dictionary-source').replaceChildren(
      new Option('选择公共推荐表', ''),
      ...catalog.sources
        .filter((source) => source.kind === 'portal-public')
        .map((source) => userOption(source.title, source.id))
    );
    renderKeyHotwords(value);
    byId('key-hotwords').scrollIntoView({ behavior: 'smooth' });
  } finally {
    keyHotwordWorking(false);
  }
}
function renderKeyRecommendations() {
  const query = wordIdentity(byId('key-dictionary-search').value);
  const words = keyRecommendationWords.filter((word) => wordIdentity(word.text).includes(query));
  const pages = Math.max(1, Math.ceil(words.length / 50));
  keyRecommendationPage = Math.min(keyRecommendationPage, pages - 1);
  const selected = new Set(keyPersonalTable.terms.map((term) => wordIdentity(term.text)));
  byId('key-dictionary-count').textContent =
    `${words.length} 个推荐词 · 第 ${keyRecommendationPage + 1} / ${pages} 页 · 状态以当前个人表编辑为准`;
  byId('key-dictionary-recommendations').replaceChildren();
  for (const term of words.slice(keyRecommendationPage * 50, (keyRecommendationPage + 1) * 50)) {
    const row = document.createElement('article');
    row.className = 'profile';
    row.dataset.word = term.text;
    const label = document.createElement('span');
    const enabled = selected.has(wordIdentity(term.text));
    label.append(
      userText(term.text),
      ` · 权重 ${term.weight || 4} · ${enabled ? '已在热词表中' : '候选词'}`
    );
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.textContent = enabled ? '已加入' : '加入热词表';
    toggle.disabled = keyHotwordBusy || enabled;
    toggle.onclick = () => {
      try {
        keyPersonalTable.add(term);
      } catch (error) {
        status(error.message, true);
      }
    };
    row.append(label, toggle);
    byId('key-dictionary-recommendations').append(row);
  }
  if (!words.length)
    byId('key-dictionary-recommendations').textContent = keyRecommendationWords.length
      ? '没有匹配的候选词。'
      : '选择公共推荐表，加载后在此查看候选词。';
  byId('key-dictionary-prev').disabled = keyHotwordBusy || keyRecommendationPage === 0;
  byId('key-dictionary-next').disabled = keyHotwordBusy || keyRecommendationPage >= pages - 1;
}
function showKeyRecommendations(result) {
  keyRecommendationWords = result.words;
  keyRecommendationPage = 0;
  byId('key-dictionary-search').value = '';
  renderKeyRecommendations();
}
byId('key-dictionary-search').oninput = () => {
  keyRecommendationPage = 0;
  renderKeyRecommendations();
};
byId('key-dictionary-prev').onclick = () => {
  keyRecommendationPage--;
  renderKeyRecommendations();
};
byId('key-dictionary-next').onclick = () => {
  keyRecommendationPage++;
  renderKeyRecommendations();
};
function keyHotwordWorking(value) {
  keyHotwordBusy = value;
  document
    .querySelectorAll(
      '#key-hotwords button, #key-hotwords input, #key-hotwords textarea, #key-hotwords select'
    )
    .forEach((control) => (control.disabled = value));
  keyPersonalTable.working(value);
  renderKeyRecommendations();
}
function renderKeyHotwords(value) {
  keyHotwordData = value;
  keyHotwordDirty = false;
  const settings = value.settings;
  byId('key-hotwords-enabled').checked = settings.enabled;
  keyPersonalTable.load(settings);
  const selection = value.selection;
  byId('key-hotwords-selection').textContent = selection
    ? `Portal 热词${settings.enabled ? '已开启' : '已关闭'} · 版本 ${value.revision} · 上游选用 ${selection.appliedCount} 个，未选用 ${selection.omitted.length} 个。${selection.capability.note}`
    : '尚无默认上游；词库仍可配置。';
  renderKeyRecommendations();
}
function reportDictionary(report) {
  return `有效 ${report.wordCount} 词，忽略 ${report.skipped} 行，去重 ${report.duplicates} 行。${report.warnings.join('；')} 样例：${report.sample.map((word) => word.text).join('、')}`;
}
async function loadKeyRecommendations(sourceId) {
  if (!keyHotwordId || keyHotwordBusy) return;
  const identity = keyHotwordId;
  keyHotwordWorking(true);
  try {
    const result = await request(keyHotwordPath(identity) + '/dictionaries', 'POST', {
      sourceId,
      preview: true
    });
    if (identity !== keyHotwordId) return;
    showKeyRecommendations(result);
    byId('key-dictionary-report').replaceChildren(
      userText(result.source.title),
      ` · ${reportDictionary(result.report)}`
    );
    status('推荐表已载入候选区，点击“加入热词表”后保存生效。');
  } catch (error) {
    status(error.message, true);
  } finally {
    keyHotwordWorking(false);
  }
}
byId('key-hotwords-refresh').onclick = action(async () => {
  if (!keyHotwordId || keyHotwordBusy) return;
  const identity = keyHotwordId;
  keyHotwordWorking(true);
  try {
    const [value, catalog] = await Promise.all([
      request(keyHotwordPath(identity)),
      request(descriptor.hotwordCatalogPath)
    ]);
    if (identity === keyHotwordId) {
      keyRecommendationWords = [];
      keyRecommendationPage = 0;
      byId('key-dictionary-search').value = '';
      byId('key-dictionary-report').textContent = '';
      const previous = byId('key-dictionary-source').value;
      keyDictionaryCatalog = catalog;
      byId('key-dictionary-source').replaceChildren(
        new Option('选择公共推荐表', ''),
        ...catalog.sources
          .filter((source) => source.kind === 'portal-public')
          .map((source) => userOption(source.title, source.id))
      );
      if (catalog.sources.some((source) => source.id === previous))
        byId('key-dictionary-source').value = previous;
      byId('key-dictionary-source').onchange();
      renderKeyHotwords(value);
    }
  } finally {
    keyHotwordWorking(false);
  }
});
byId('key-hotwords-close').onclick = () => {
  if (keyHotwordBusy) return;
  if (keyHotwordDirty) {
    status('请先保存热词设置，或刷新以放弃编辑。', true);
    return;
  }
  keyHotwordId = null;
  byId('key-hotwords').hidden = true;
};
byId('key-hotwords-enabled').onchange = () => keyHotwordsChanged();
byId('key-hotwords-form').onsubmit = (event) => {
  event.preventDefault();
  if (!keyHotwordId || keyHotwordBusy) return;
  const identity = keyHotwordId;
  keyHotwordWorking(true);
  action(async () => {
    try {
      const result = await request(keyHotwordPath(identity), 'PATCH', {
        revision: keyHotwordData.revision,
        settings: {
          enabled: byId('key-hotwords-enabled').checked,
          ...keyPersonalTable.patch()
        }
      });
      if (identity === keyHotwordId) {
        renderKeyHotwords(result);
        status('个人热词已保存，Input Settings 刷新即可同步。');
      }
    } finally {
      keyHotwordWorking(false);
    }
  })();
};
byId('key-dictionary-source').onchange = () => {
  const source = keyDictionaryCatalog?.sources.find(
    (row) => row.id === byId('key-dictionary-source').value
  );
  byId('key-dictionary-source-note').textContent = source
    ? `${source.description} · ${source.license}`
    : '';
  byId('key-dictionary-source-note').translate = false;
};
byId('key-dictionary-online').onclick = () => {
  const sourceId = byId('key-dictionary-source').value;
  if (!sourceId) {
    status('请选择公开词库', true);
    return;
  }
  loadKeyRecommendations(sourceId);
};
function render() {
  const list = byId('profiles');
  list.replaceChildren();
  if (!profiles.length) {
    list.textContent = '还没有 ASR 配置。点击“增加配置”后，桌面应用即可选择使用。';
    return;
  }
  for (const [position, profile] of profiles.entries()) {
    const card = document.createElement('article');
    card.className = 'profile';
    card.dataset.id = profile.id;
    const title = document.createElement('h3');
    title.append(userText(profile.title));
    if (profile.quota)
      title.replaceChildren(
        `${position + 1}. `,
        userText(profile.title),
        ` · ${profile.quota.enabled ? '启用' : profile.quota.disabledReason === 'manual' ? '手动停用' : '额度 / 计量停用'}`
      );
    const detail = document.createElement('p');
    detail.textContent = `${profile.id} · ${profile.provider} · ${profile.configuration.endpoint || ''}`;
    detail.translate = false;
    const actions = document.createElement('div');
    actions.className = 'actions';
    const button = (label, callback, className) => {
      const value = document.createElement('button');
      value.textContent = label;
      value.className = className || '';
      value.onclick = action(callback);
      actions.append(value);
      return value;
    };
    if (profile.id === defaultId) {
      const badge = document.createElement('span');
      badge.className = 'default';
      badge.textContent = '默认识别配置';
      actions.append(badge);
    } else {
      const makeDefault = button('设为默认', async () => {
        await request(descriptor.settingsPath, 'PATCH', { defaultProfileId: profile.id });
        await refresh();
      });
      makeDefault.disabled = profile.quota?.enabled === false;
    }
    if (profile.quota) {
      button(profile.quota.enabled ? '停用' : '启用', async () => {
        const result = await request(
          `/v1/admin/profiles/${encodeURIComponent(profile.id)}/quota`,
          'PATCH',
          { enabled: !profile.quota.enabled }
        );
        await refresh();
        status(
          result.enabled
            ? '上游已启用。'
            : result.exhausted || result.tokenBlocked
              ? '额度已用尽或无法计量，请先调整该上游的剩余配额。'
              : '上游已停用，默认配置已按顺序调整。'
        );
      });
      for (const [label, offset] of [
        ['上移', -1],
        ['下移', 1]
      ]) {
        const move = button(label, async () => {
          const order = profiles.map((value) => value.id);
          [order[position], order[position + offset]] = [order[position + offset], order[position]];
          await request(descriptor.settingsPath, 'PATCH', { profileOrder: order });
          await refresh();
        });
        move.disabled = position + offset < 0 || position + offset >= profiles.length;
      }
    }
    button('修改', () => edit(profile));
    button('测试', async () => {
      const result = await request(
        `/v1/admin/profiles/${encodeURIComponent(profile.id)}/test`,
        'POST'
      );
      status(result.ok ? `测试通过 · 请求总耗时 ${result.latencyMs} ms` : result.error, !result.ok);
    });
    button(
      '删除',
      async () => {
        await request(`/v1/admin/profiles/${encodeURIComponent(profile.id)}`, 'DELETE');
        if (current?.id === profile.id) byId('editor').hidden = true;
        await refresh();
      },
      'danger'
    );
    card.append(title, detail, actions);
    const quota = quotaControls(
      'profile',
      profile.id,
      profile.quota,
      profile.capabilities.tokenUsage
    );
    if (quota) card.append(quota);
    list.append(card);
  }
}
function edit(profile) {
  showPage('upstream', false);
  current = profile;
  byId('editor').hidden = false;
  byId('editor-title').textContent = profile ? '修改上游服务接入' : '增加上游服务接入';
  byId('profile-id').value = profile?.id || '';
  byId('profile-id').readOnly = !!profile;
  byId('profile-title').value = profile?.title || '';
  byId('provider').value = profile?.provider || descriptor.providers[0].id;
  renderFields(profile?.configuration || {});
  byId('editor').scrollIntoView({ behavior: 'smooth' });
}
function renderFields(configuration) {
  fields.clear();
  byId('fields').replaceChildren();
  const provider = descriptor.providers.find((value) => value.id === byId('provider').value);
  for (const definition of provider.fields) {
    const label = document.createElement('label');
    label.textContent = definition.label;
    const input = document.createElement(definition.type === 'select' ? 'select' : 'input');
    input.name = definition.key;
    if (definition.type === 'select')
      definition.options.forEach((option) => input.append(new Option(option.label, option.value)));
    else
      input.type =
        { secret: 'password', boolean: 'checkbox', number: 'number' }[definition.type] || 'text';
    const value = configuration[definition.key] ?? definition.default ?? '';
    if (definition.type === 'boolean') input.checked = !!value;
    else input.value = definition.type === 'secret' ? '' : String(value);
    input.required =
      !!definition.required && !(definition.type === 'secret' && configuration.hasApiKey);
    if (definition.type === 'secret') {
      // Upstream keys are newly supplied credentials, not this site's login password.
      // Prevent the browser from filling a previous provider or administrator key.
      input.autocomplete = 'new-password';
      input.spellcheck = false;
      input.autocapitalize = 'none';
      input.placeholder = configuration.hasApiKey ? '已保存，留空保持原值' : '填写 API Key';
    }
    if (definition.readOnly) input.readOnly = true;
    for (const key of ['min', 'max', 'step'])
      if (definition[key] !== undefined) input[key] = definition[key];
    label.append(input);
    if (definition.description) {
      const help = document.createElement('small');
      help.textContent = definition.description;
      label.append(help);
    }
    byId('fields').append(label);
    fields.set(definition.key, { input, definition });
  }
}
function body() {
  const configuration = {};
  for (const [key, { input, definition }] of fields) {
    if (definition.type === 'secret' && !input.value.trim()) continue;
    configuration[key] =
      definition.type === 'boolean'
        ? input.checked
        : definition.type === 'number' || definition.valueType === 'number'
          ? Number(input.value)
          : input.value.trim();
  }
  return {
    id: byId('profile-id').value.trim(),
    title: byId('profile-title').value.trim(),
    provider: byId('provider').value,
    configuration
  };
}
byId('connect').onclick = action(async () => {
  const result = await request(
    '/v1/admin/auth/login',
    'POST',
    { password: byId('admin-key').value },
    true
  );
  credential = result.token;
  sessionStorage.setItem('openasrportal-admin-session', credential);
  byId('admin-key').value = '';
  await refresh();
});
byId('admin-key').onkeydown = (event) => {
  if (event.key === 'Enter') byId('connect').click();
};
byId('refresh').onclick = action(refresh);
byId('new').onclick = () => edit(null);
byId('cancel').onclick = () => {
  byId('editor').hidden = true;
  fields.clear();
  byId('fields').replaceChildren();
};
byId('provider').onchange = () => renderFields({});
byId('test').onclick = action(async () => {
  // A new draft must supply its own key, even if its ID matches a saved profile.
  for (const { input } of fields.values()) if (!input.reportValidity()) return;
  const value = body();
  const result = await request(
    `/v1/admin/profiles/${encodeURIComponent(value.id || 'draft')}/test`,
    'POST',
    value
  );
  status(result.ok ? `测试通过 · 请求总耗时 ${result.latencyMs} ms` : result.error, !result.ok);
});
byId('form').onsubmit = (event) => {
  event.preventDefault();
  action(async () => {
    const value = body();
    await request(
      current ? `/v1/admin/profiles/${encodeURIComponent(current.id)}` : descriptor.profilesPath,
      current ? 'PATCH' : 'POST',
      value
    );
    byId('editor').hidden = true;
    fields.clear();
    byId('fields').replaceChildren();
    await refresh();
  })();
};
byId('proxy-form').oninput = () => { proxyDirty = true; };
byId('proxy-update-auth').onchange = () => {
  for (const id of ['proxy-username', 'proxy-password']) {
    byId(id).disabled = !byId('proxy-update-auth').checked;
    if (byId(id).disabled) byId(id).value = '';
  }
};
byId('proxy-form').onsubmit = (event) => {
  event.preventDefault();
  action(async () => {
    const proxy = { url: byId('proxy-url').value.trim() };
    if (byId('proxy-update-auth').checked) {
      proxy.username = byId('proxy-username').value;
      proxy.password = byId('proxy-password').value;
    }
    byId('proxy-save').disabled = true;
    try {
      const value = await request(descriptor.settingsPath, 'PATCH', { proxy });
      proxyDirty = false;
      showProxy(value.proxy);
      status('代理设置已保存，新连接生效。');
    } finally {
      byId('proxy-save').disabled = false;
    }
  })();
};
byId('key-form').onsubmit = (event) => {
  event.preventDefault();
  action(async () => {
    const value = await request('/v1/admin/asr-keys', 'POST', {
      title: byId('key-title').value.trim()
    });
    byId('new-key-value').value = value.key;
    byId('new-key').hidden = false;
    byId('key-title').value = '';
    await refreshKeys();
    status('ASR Key 已生成，可复制到客户端；以后可通过管理权限查看。');
  })();
};
byId('key-dismiss').onclick = () => {
  byId('new-key-value').value = '';
  byId('new-key').hidden = true;
};
byId('new-key-copy').onclick = action(() =>
  copyKey(byId('new-key-value').value, byId('new-key-value'))
);
byId('logout').onclick = action(async () => {
  await request('/v1/admin/auth/logout', 'POST', {});
  disconnect();
  status('已退出管理会话。');
});
byId('usage-form').onsubmit = (event) => {
  event.preventDefault();
  action(refreshUsage)();
};
const localTime = (date) =>
  new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
function resetUsagePeriod() {
  const end = new Date(Math.ceil(Date.now() / 60000) * 60000);
  byId('usage-to').value = localTime(end);
  byId('usage-from').value = localTime(new Date(end.getTime() - 7 * 86400000));
}
resetUsagePeriod();
for (const id of ['usage-from', 'usage-to'])
  byId(id).oninput = () => {
    usageAutoPeriod = false;
  };
byId('usage-recent').onclick = action(async () => {
  usageAutoPeriod = true;
  await refreshUsage();
});
const tabs = [...document.querySelectorAll('#admin-nav [role=tab]')];
tabs.forEach((tab, index) => {
  tab.onclick = () => showPage(tab.dataset.page);
  tab.onkeydown = (event) => {
    const offset = ['ArrowDown', 'ArrowRight'].includes(event.key)
      ? 1
      : ['ArrowUp', 'ArrowLeft'].includes(event.key)
        ? -1
        : 0;
    if (!offset && !['Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next =
      event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? tabs.length - 1
          : (index + offset + tabs.length) % tabs.length;
    showPage(tabs[next].dataset.page);
  };
});
const ticket = new URLSearchParams(location.hash.slice(1)).get('ticket');
if (ticket) {
  history.replaceState(null, '', location.pathname);
  action(async () => {
    credential = (await request('/v1/admin/ui-session', 'POST', { ticket }, true)).token;
    sessionStorage.setItem('openasrportal-admin-session', credential);
    await refresh();
  })();
} else if (credential) {
  action(refresh)();
}
