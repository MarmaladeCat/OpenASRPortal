import './i18n.mjs';
const byId = (id) => document.getElementById(id);
const destination = '/admin';

async function request(path, body) {
  const response = await fetch('/v1/admin/auth/' + path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    redirect: 'error'
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || '首次设置失败，请稍后重试');
  return data;
}
async function state() {
  const status = await request('status');
  if (status.initialized) {
    location.replace(destination);
    return null;
  }
  return status;
}
byId('setup-form').onsubmit = async (event) => {
  event.preventDefault();
  const password = byId('setup-password').value;
  const confirmPassword = byId('setup-confirm').value;
  if (password !== confirmPassword) {
    byId('setup-status').textContent = '两次输入的密码不一致。';
    return;
  }
  byId('setup-submit').disabled = true;
  try {
    const status = await state();
    if (!status) return;
    const result = await request('setup', {
      password,
      confirmPassword,
      setupChallenge: status.setupChallenge
    });
    byId('setup-password').value = '';
    byId('setup-confirm').value = '';
    sessionStorage.setItem('openasrportal-admin-session', result.token);
    location.replace(destination);
  } catch (error) {
    byId('setup-status').textContent = error.message;
  } finally {
    byId('setup-submit').disabled = false;
  }
};
state()
  .then((status) => {
    if (status) byId('setup-status').textContent = '请设置只有你知道的管理密码。';
  })
  .catch((error) => {
    byId('setup-status').textContent = error.message;
  });
