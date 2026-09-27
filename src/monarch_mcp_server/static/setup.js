'use strict';
const $ = id => document.getElementById(id);
const form = $('login-form');
function status(message, error = false) {
  $('status').textContent = message;
  $('status').classList.toggle('error', error);
  $('status').hidden = false;
}
function methodChanged() {
  const token = $('method').value === 'token';
  $('password-fields').hidden = token;
  $('token-fields').hidden = !token;
  for (const id of ['email', 'password']) { $(id).disabled = token; $(id).required = !token; }
  $('token').disabled = !token; $('token').required = token;
  $('mfa').disabled = token;
  $('mfa').required = !token && !$('mfa-fields').hidden;
  $('status').hidden = true;
}
$('method').addEventListener('change', methodChanged);
$('another').addEventListener('click', () => {
  $('success').hidden = true; form.hidden = false; $('mfa-fields').hidden = true;
  methodChanged(); $('api-key').focus();
});
form.addEventListener('submit', async event => {
  event.preventDefault();
  const tokenMode = $('method').value === 'token';
  const payload = tokenMode ? {token: $('token').value.trim()} : {email: $('email').value.trim(), password: $('password').value};
  if (!tokenMode && $('mfa').value.trim()) payload.mfa_code = $('mfa').value.trim();
  const key = $('api-key').value.trim();
  $('fields').disabled = true;
  $('submit').textContent = 'Connecting…';
  status('Checking your login with Monarch…');
  try {
    const response = await fetch(tokenMode ? '/auth/token' : '/auth/login', {
      method: 'POST', headers: {'Authorization': `Bearer ${key}`, 'Content-Type': 'application/json'},
      body: JSON.stringify(payload), cache: 'no-store', credentials: 'omit', signal: AbortSignal.timeout(55000)
    });
    const data = await response.json();
    if (response.status === 202 && data.status === 'mfa_required') {
      $('mfa-fields').hidden = false; $('mfa').required = true;
      status('Enter your verification code below, then connect again.');
    } else if (response.ok && data.status === 'authenticated') {
      for (const id of ['password', 'token', 'mfa', 'api-key']) $(id).value = '';
      $('status').hidden = true; form.hidden = true; $('success').hidden = false;
    } else {
      const messages = {401:'The setup access key is incorrect. Check the key saved on Media.', 400:'Check that all required fields are filled in.', 429:'Too many attempts. Wait one minute and try again.', 502:'Monarch could not validate this login. Check your credentials or try a browser session token. Your previous session was not replaced.', 503:'Media could not save the session or reach Monarch. Please try again.', 504:'Monarch took too long to respond. Please try again.'};
      status(messages[response.status] || 'Sign-in could not be completed. Please try again.', true);
    }
  } catch (_) { status('Could not reach the setup service. Check your connection and try again.', true); }
  finally {
    $('fields').disabled = false; $('submit').textContent = 'Connect account →';
    if (!$('mfa-fields').hidden && !form.hidden) $('mfa').focus();
  }
});
