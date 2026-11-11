const API = '/api';
const EMOTIONS = [
  { type: 'happy', emoji: '😊', label: '开心', tone: 'positive' },
  { type: 'confused', emoji: '😕', label: '困惑', tone: 'concern' },
  { type: 'bored', emoji: '😐', label: '无聊', tone: 'concern' },
  { type: 'sad', emoji: '😔', label: '低落', tone: 'concern' },
  { type: 'focused', emoji: '🤔', label: '专注', tone: 'focus' },
  { type: 'excited', emoji: '🤩', label: '兴奋', tone: 'positive' },
];

const state = {
  token: localStorage.getItem('emotionToken'),
  user: JSON.parse(localStorage.getItem('emotionUser') || 'null'),
  register: false,
  sessions: [],
  users: [],
  courses: [],
  adminSessions: [],
  pollTimer: null,
  dashboardSocket: null,
  dashboardSocketSession: null,
  dashboardSocketTarget: null,
  adminBootstrapAvailable: false,
  activeAdminTab: 'overview',
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[character]));
}

function setMessage(element, message, tone = '') {
  if (!element) return;
  element.textContent = message;
  element.classList.remove('success', 'error');
  if (tone) element.classList.add(tone);
}

let toastTimer;
function toast(message) {
  const node = $('#toast');
  node.textContent = message;
  node.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove('visible'), 2800);
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.token) headers.set('Authorization', `Bearer ${state.token}`);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await fetch(`${API}${path}`, { ...options, headers });
  if (response.status === 401 && state.token) {
    signOut(false);
    showAuth('登录状态已过期，请重新登录。');
  }
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    const body = await response.json();
    if (!response.ok) throw new Error(body.message || `请求失败 (${response.status})`);
    return body.data;
  }
  if (!response.ok) throw new Error(`请求失败 (${response.status})`);
  return response;
}

function formatDate(value, options = {}) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return escapeHtml(value);
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', ...options }).format(date);
}

function dateFilterBoundary(value, endOfDay = false) {
  if (!value) return '';
  const date = new Date(`${value}T${endOfDay ? '23:59:59.999' : '00:00:00'}`);
  return Number.isNaN(date.getTime()) ? '' : date.toISOString();
}

function roleLabel(role) {
  return ({ student: '学生', teacher: '教师', admin: '管理员' })[role] || role;
}

function emotion(type) {
  return EMOTIONS.find((item) => item.type === type) || { emoji: '🙂', label: type || '未知', tone: '' };
}

function showAuth(message = '') {
  stopPolling();
  closeDashboardSocket();
  setAuthMode(false);
  $$('.app-view').forEach((view) => { view.hidden = true; });
  $('#authView').hidden = false;
  $('#mainNav').innerHTML = '';
  $('#logoutButton').hidden = true;
  $('#changePasswordButton').hidden = true;
  $('#openLoginButton').hidden = true;
  $('#accountName').textContent = '';
  $('#authError').hidden = !message;
  $('#authError').textContent = message;
}

function setAuthMode(register) {
  state.register = register;
  $('#authTitle').textContent = register ? '创建课堂账号' : '登录课堂空间';
  $('#authSubtitle').textContent = register ? '选择身份并填写注册信息' : '使用老师或学生账号继续';
  $('#authSubmit').textContent = register ? '注册并进入' : '登录';
  $('#switchAuthMode').textContent = register ? '已有账号？返回登录' : '还没有账号？创建账号';
  $('#registerFields').hidden = !register;
  $('#authPassword').autocomplete = register ? 'new-password' : 'current-password';
  $('#authError').hidden = true;
  updateRegistrationRole();
  if (register) loadRegistrationOptions();
}

async function loadRegistrationOptions() {
  try {
    const options = await api('/auth/registration-options');
    state.adminBootstrapAvailable = options.admin_bootstrap_available;
    updateRegistrationRole();
  } catch { state.adminBootstrapAvailable = false; updateRegistrationRole(); }
}

function updateRegistrationRole() {
  const role = $('#authRole').value;
  const privileged = state.register && role !== 'student';
  $('#registrationCodeField').hidden = !privileged;
  $('#authRegistrationCode').required = privileged;
  $('#registrationCodeLabel').textContent = role === 'admin' && state.adminBootstrapAvailable ? '邀请码或首次初始化密钥' : '注册邀请码';
  $('#registrationHint').textContent = role === 'student' ? '学生可直接注册，课表由管理员安排。'
    : role === 'admin' && state.adminBootstrapAvailable ? '当前尚无管理员，可使用部署时设置的初始化密钥创建首个管理员。'
      : '请向管理员获取与你的注册身份对应的一次性邀请码。';
}

function showView(name) {
  $$('.app-view').forEach((view) => { view.hidden = true; });
  $('#authView').hidden = true;
  const view = $(`#${name}View`);
  if (view) view.hidden = false;
  $$('#mainNav button').forEach((button) => button.classList.toggle('active', button.dataset.view === name));
}

function renderNavigation() {
  const navItems = state.user.role === 'student'
    ? [['student', '课堂打卡'], ['history', '我的历史']]
    : state.user.role === 'teacher' ? [['teacher', '情绪看板']] : [['admin', '系统管理']];
  $('#mainNav').innerHTML = navItems.map(([view, label]) => `<button data-view="${view}">${label}</button>`).join('');
  $$('#mainNav button').forEach((button) => button.addEventListener('click', () => navigate(button.dataset.view)));
  $('#accountName').textContent = `${state.user.full_name} · ${roleLabel(state.user.role)}`;
  $('#changePasswordButton').hidden = false;
  $('#logoutButton').hidden = false;
  $('#openLoginButton').hidden = true;
}

async function navigate(name) {
  showView(name);
  if (name === 'student') await loadStudentHome();
  if (name === 'history') await loadFullHistory();
  if (name === 'teacher') {
    await loadTeacherSessions();
    await loadTeacherDashboard();
  }
  if (name === 'admin') {
    await loadAdmin();
  }
}

function signOut(showMessage = true) {
  stopPolling();
  closeDashboardSocket();
  state.token = null;
  state.user = null;
  localStorage.removeItem('emotionToken');
  localStorage.removeItem('emotionUser');
  $('#invitationCode').value = '';
  $('#invitationResult').hidden = true;
  if (showMessage) toast('已安全退出');
  showAuth();
  $('#openLoginButton').hidden = false;
}

async function restoreSession() {
  if (!state.token || !state.user) {
    showAuth();
    $('#openLoginButton').hidden = false;
    return;
  }
  try {
    state.user = await api('/users/me');
    localStorage.setItem('emotionUser', JSON.stringify(state.user));
    renderNavigation();
    await navigate(state.user.role === 'student' ? 'student' : state.user.role === 'teacher' ? 'teacher' : 'admin');
  } catch {
    signOut(false);
    $('#openLoginButton').hidden = false;
  }
}

async function submitAuth(event) {
  event.preventDefault();
  const button = $('#authSubmit');
  const errorNode = $('#authError');
  button.disabled = true;
  button.textContent = state.register ? '正在创建…' : '正在登录…';
  errorNode.hidden = true;
  const payload = {
    username: $('#authUsername').value.trim(),
    password: $('#authPassword').value,
  };
  if (state.register) {
    payload.full_name = $('#authFullName').value.trim();
    payload.email = $('#authEmail').value.trim();
    payload.role = $('#authRole').value;
    if (payload.role !== 'student') payload.registration_code = $('#authRegistrationCode').value.trim();
  }
  try {
    const result = await api(`/auth/${state.register ? 'register' : 'login'}`, { method: 'POST', body: JSON.stringify(payload) });
    state.token = result.access_token;
    state.user = result.user;
    $('#authRegistrationCode').value = '';
    $('#authPassword').value = '';
    localStorage.setItem('emotionToken', state.token);
    localStorage.setItem('emotionUser', JSON.stringify(state.user));
    renderNavigation();
    await navigate(state.user.role === 'student' ? 'student' : state.user.role === 'teacher' ? 'teacher' : 'admin');
  } catch (error) {
    errorNode.textContent = error.message;
    errorNode.hidden = false;
  } finally {
    button.disabled = false;
    button.textContent = state.register ? '注册并进入' : '登录';
  }
}

async function changePassword(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $('#savePasswordButton');
  const message = $('#passwordMessage');
  const fields = Object.fromEntries(new FormData(form).entries());
  button.disabled = true;
  message.hidden = true;
  try {
    await api('/auth/password', { method: 'PUT', body: JSON.stringify(fields) });
    $('#changePasswordDialog').close();
    form.reset();
    signOut(false);
    $('#openLoginButton').hidden = true;
    $('#authError').hidden = false;
    $('#authError').textContent = '密码已修改，请使用新密码重新登录。';
  } catch (error) {
    message.textContent = error.message;
    message.hidden = false;
  } finally {
    button.disabled = false;
  }
}

function buildEmotionButtons(container, sessionId = '') {
  container.innerHTML = EMOTIONS.map((item) => `
    <button class="emotion-choice" type="button" data-emoji="${item.type}" ${sessionId ? '' : 'disabled'} aria-label="记录${item.label}">
      <span aria-hidden="true">${item.emoji}</span><b>${item.label}</b>
    </button>`).join('');
  $$('[data-emoji]', container).forEach((button) => button.addEventListener('click', () => submitEmoji(button.dataset.emoji)));
}

async function loadStudentHome() {
  $('#studentDate').textContent = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'full' }).format(new Date());
  buildEmotionButtons($('#emotionChoices'));
  try {
    state.sessions = await api('/sessions');
    const select = $('#studentSessionSelect');
    const previous = select.value;
    const active = state.sessions.filter((session) => session.status === 'active' && session.is_scheduled);
    select.innerHTML = '<option value="">请选择已安排的课堂</option>' + state.sessions.map((session) => {
      const label = `${session.course_name} · ${session.class_name} · ${formatDate(session.starts_at)}`;
      return `<option value="${session.id}">${escapeHtml(label)}</option>`;
    }).join('');
    if (active.length) select.value = String(active[0].id);
    else if (state.sessions.some((session) => String(session.id) === previous)) select.value = previous;
    updateSelectedSession();
    await refreshStudentHistory();
  } catch (error) {
    setMessage($('#checkinMessage'), error.message, 'error');
  }
}

function updateSelectedSession() {
  const sessionId = $('#studentSessionSelect').value;
  const session = state.sessions.find((item) => String(item.id) === sessionId);
  const available = Boolean(session && session.status === 'active' && session.is_scheduled);
  $$('.emotion-choice').forEach((button) => { button.disabled = !available; });
  const badge = $('#activeSessionBadge');
  badge.textContent = available ? '课堂进行中' : session ? '暂未开放' : '选择课堂';
  badge.classList.toggle('active', available);
  $('#sessionInfo').textContent = session
    ? `${session.course_name} · ${session.class_name} · ${session.room || '未填写教室'} · ${formatDate(session.starts_at)}`
    : '选择已安排的课堂后即可记录。';
  setMessage($('#checkinMessage'), available ? '选择最贴近你此刻感受的表情' : '当前没有开放中的已安排课堂');
}

async function submitEmoji(type) {
  const sessionId = $('#studentSessionSelect').value;
  const buttons = $$('.emotion-choice');
  buttons.forEach((button) => { button.disabled = true; });
  try {
    await api('/emoji', { method: 'POST', body: JSON.stringify({ session_id: Number(sessionId), emoji_type: type, device_id: 'browser' }) });
    const selected = emotion(type);
    setMessage($('#checkinMessage'), `已记录 ${selected.emoji} ${selected.label}，谢谢你的反馈。`, 'success');
    await refreshStudentHistory();
  } catch (error) {
    setMessage($('#checkinMessage'), error.message, 'error');
  } finally {
    const session = state.sessions.find((item) => String(item.id) === $('#studentSessionSelect').value);
    buttons.forEach((button) => { button.disabled = !(session && session.status === 'active' && session.is_scheduled); });
  }
}

function recordRows(records, emptyText = '暂无记录') {
  if (!records.length) return `<div class="empty-state">${escapeHtml(emptyText)}</div>`;
  return records.map((item) => `
    <div class="record-row">
      <span class="record-emoji" aria-hidden="true">${item.emoji || emotion(item.emoji_type).emoji}</span>
      <span class="record-main"><strong>${escapeHtml(item.label || emotion(item.emoji_type).label)}${item.user_name ? ` · ${escapeHtml(item.user_name)}` : ''}</strong>
      <small>${escapeHtml(item.course_name || '')}${item.class_name ? ` · ${escapeHtml(item.class_name)}` : ''}</small></span>
      <span class="record-meta"><time>${formatDate(item.recorded_at)}</time><span class="source-tag ${item.source === 'AI' ? 'ai' : ''}">${item.source === 'AI' ? 'AI 汇总' : '手动'}</span></span>
    </div>`).join('');
}

async function refreshStudentHistory() {
  const records = await api('/emoji/history?limit=100');
  $('#studentRecentHistory').innerHTML = recordRows(records.slice(0, 5));
  const counts = {};
  records.forEach((item) => { counts[item.emoji_type] = (counts[item.emoji_type] || 0) + 1; });
  const top = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
  $('#studentRecordCount').textContent = records.length;
  $('#studentSummaryText').textContent = records.length ? '你的课堂反馈持续帮助课程变得更好。' : '记录一次感受后，这里会更新你的课堂概览。';
  $('#studentTopEmotion').innerHTML = top
    ? `<span>${emotion(top[0]).emoji}</span><b>最常记录：${emotion(top[0]).label}</b>`
    : '<span>—</span><b>等待第一条记录</b>';
}

async function loadFullHistory() {
  try {
    const records = await api('/emoji/history?limit=500');
    $('#fullHistory').innerHTML = recordRows(records, '还没有课堂记录。参加已安排的课堂后，可在这里查看情绪历史。');
  } catch (error) {
    $('#fullHistory').innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
  }
}

async function loadTeacherSessions() {
  try {
    state.sessions = await api('/teacher/sessions');
    const select = $('#teacherSessionSelect');
    const oldValue = select.value;
    select.innerHTML = state.sessions.map((item) => `<option value="${item.id}">${escapeHtml(item.course_name)} · ${escapeHtml(item.class_name)} · ${formatDate(item.starts_at)}</option>`).join('');
    if (state.sessions.some((item) => String(item.id) === oldValue)) select.value = oldValue;
    const courses = [...new Map(state.sessions.map((item) => [item.course_id, item.course_name])).entries()];
    $('#teacherCourseFilter').innerHTML = '<option value="">全部课程</option>' + courses.map(([id, name]) => `<option value="${id}">${escapeHtml(name)}</option>`).join('');
    const classes = [...new Set(state.sessions.map((item) => item.class_name))];
    $('#teacherClassFilter').innerHTML = '<option value="">全部班级</option>' + classes.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join('');
    if (!state.sessions.length) $('#teacherRecent').innerHTML = '<div class="empty-state">暂无你授课的课堂安排。</div>';
  } catch (error) {
    toast(error.message);
  }
}

function queryFilters(prefix) {
  const params = new URLSearchParams();
  const session = $(`#${prefix}SessionSelect`)?.value;
  const course = $(`#${prefix}CourseFilter`)?.value;
  const className = $(`#${prefix}ClassFilter`)?.value;
  const from = $(`#${prefix}FromFilter`)?.value;
  const to = $(`#${prefix}ToFilter`)?.value;
  if (session) params.set('session_id', session);
  if (course) params.set('course_id', course);
  if (className) params.set('class_name', className);
  if (from) params.set('from', dateFilterBoundary(from));
  if (to) params.set('to', dateFilterBoundary(to, true));
  return params;
}

async function loadTeacherDashboard() {
  if (!$('#teacherView') || $('#teacherView').hidden) return;
  const sessionId = $('#teacherSessionSelect').value;
  try {
    let realtime = null;
    if (sessionId) realtime = await api(`/admin/dashboard/realtime?sessionId=${encodeURIComponent(sessionId)}`);
    const params = queryFilters('teacher');
    if (params.has('session_id')) params.delete('session_id');
    const stats = await api(`/admin/statistics${params.size ? `?${params}` : ''}`);
    renderDistribution($('#emotionDistribution'), stats.emotions);
    $('#metricTotal').textContent = realtime?.total_last_hour ?? 0;
    const total = stats.total || 0;
    const counts = Object.fromEntries(stats.emotions.map((item) => [item.type, item.count]));
    $('#metricPositive').textContent = `${total ? Math.round(((counts.happy + counts.excited) / total) * 100) : 0}%`;
    $('#metricFocused').textContent = `${total ? Math.round(((counts.focused) / total) * 100) : 0}%`;
    const selected = state.sessions.find((item) => String(item.id) === sessionId);
    $('#metricStudents').textContent = selected?.student_count ?? '—';
    if (realtime) {
      renderTrend($('#trendChart'), realtime.trend);
      $('#chartEmpty').hidden = Boolean(realtime.total_last_hour);
      $('#teacherRecent').innerHTML = recordRows(realtime.recent);
      $('#lastUpdated').textContent = `更新于 ${formatDate(realtime.generated_at)}`;
    } else {
      renderTrend($('#trendChart'), []);
      $('#chartEmpty').hidden = false;
      $('#teacherRecent').innerHTML = recordRows([]);
      $('#lastUpdated').textContent = '暂无课堂';
    }
    connectDashboardSocket(sessionId);
    $('#sessionStatsTable').innerHTML = stats.by_session.map((item) => `<tr><td>${escapeHtml(item.course_name)}</td><td>${escapeHtml(item.class_name)}</td><td>${formatDate(item.starts_at)}</td><td>${item.total}</td></tr>`).join('') || '<tr><td colspan="4">暂无统计数据</td></tr>';
  } catch (error) {
    if (error.message !== '登录状态已过期，请重新登录。') toast(error.message);
  }
}

function closeDashboardSocket() {
  state.dashboardSocket?.close();
  state.dashboardSocket = null;
  state.dashboardSocketSession = null;
  state.dashboardSocketTarget = null;
}

function connectDashboardSocket(sessionId, target = 'teacher') {
  if (!sessionId || !window.WebSocket) {
    closeDashboardSocket();
    if (sessionId) startPolling(target === 'admin' ? loadAdminOverview : loadTeacherDashboard);
    return;
  }
  if (state.dashboardSocketSession === sessionId && state.dashboardSocketTarget === target && state.dashboardSocket
      && state.dashboardSocket.readyState <= WebSocket.OPEN) return;
  closeDashboardSocket();
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const socket = new WebSocket(`${protocol}//${window.location.host}/ws/dashboard`);
  state.dashboardSocket = socket;
  state.dashboardSocketSession = sessionId;
  state.dashboardSocketTarget = target;
  socket.addEventListener('open', () => {
    if (target === 'teacher') stopPolling();
    socket.send(JSON.stringify({ token: state.token, session_id: Number(sessionId) }));
  });
  socket.addEventListener('message', (event) => {
    try {
      const message = JSON.parse(event.data);
      if (message.error) {
        socket.close();
        return;
      }
      if (state.dashboardSocket !== socket) return;
      if (target === 'admin') renderAdminLiveUpdate(message.data);
      else renderLiveUpdate(message.data);
    } catch (error) {
      console.error('Invalid dashboard update', error);
    }
  });
  socket.addEventListener('close', () => {
    if (state.dashboardSocket !== socket || (target === 'teacher' ? $('#teacherView').hidden
      : $('#adminView').hidden || state.activeAdminTab !== 'overview')) return;
    state.dashboardSocket = null;
    state.dashboardSocketSession = null;
    state.dashboardSocketTarget = null;
    startPolling(target === 'admin' ? loadAdminOverview : loadTeacherDashboard);
  });
  socket.addEventListener('error', () => socket.close());
}

function renderLiveUpdate(realtime) {
  if (!realtime || $('#teacherView').hidden) return;
  renderTrend($('#trendChart'), realtime.trend);
  $('#chartEmpty').hidden = Boolean(realtime.total_last_hour);
  $('#metricTotal').textContent = realtime.total_last_hour;
  const total = realtime.total_last_hour || 0;
  const counts = Object.fromEntries(realtime.counts.map((item) => [item.type, item.count]));
  $('#metricPositive').textContent = `${total ? Math.round(((counts.happy + counts.excited) / total) * 100) : 0}%`;
  $('#metricFocused').textContent = `${total ? Math.round((counts.focused / total) * 100) : 0}%`;
  const session = state.sessions.find((item) => String(item.id) === String(realtime.session.id));
  $('#metricStudents').textContent = session?.student_count ?? '—';
  $('#teacherRecent').innerHTML = recordRows(realtime.recent);
  $('#lastUpdated').textContent = `更新于 ${formatDate(realtime.generated_at)}`;
}

function renderDistribution(container, items = []) {
  const max = Math.max(1, ...items.map((item) => item.count));
  container.innerHTML = items.map((item) => `
    <div class="distribution-item"><span class="dist-emoji">${item.emoji || emotion(item.type).emoji}</span><span class="dist-label">${escapeHtml(item.label || emotion(item.type).label)}</span>
      <span class="progress-track"><i style="width:${Math.max(item.count ? 4 : 0, (item.count / max) * 100)}%"></i></span><b class="dist-count">${item.count}</b></div>`).join('') || '<div class="empty-state">暂无记录</div>';
}

function renderTrend(canvas, points = [], labelMode = 'time') {
  if (!canvas) return;
  const box = canvas.getBoundingClientRect();
  if (!box.width) return;
  const ratio = window.devicePixelRatio || 1;
  const height = 230;
  canvas.width = Math.round(box.width * ratio);
  canvas.height = height * ratio;
  canvas.style.height = `${height}px`;
  const context = canvas.getContext('2d');
  context.scale(ratio, ratio);
  const width = box.width;
  const left = 31, right = 9, top = 17, bottom = 27;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const series = [
    { label: 'positive', color: '#65aa8a', keys: ['happy', 'excited'] },
    { label: 'focus', color: '#4caaa5', keys: ['focused'] },
    { label: 'concern', color: '#e39a73', keys: ['confused', 'bored', 'sad'] },
  ];
  const totalAt = points.map((point) => series.map((line) => line.keys.reduce((sum, key) => sum + (point[key] || 0), 0)));
  const max = Math.max(2, ...totalAt.flat());
  context.font = '10px "DM Sans", "Noto Sans SC", sans-serif';
  context.textBaseline = 'middle';
  for (let tick = 0; tick <= 3; tick += 1) {
    const y = top + (plotHeight * tick / 3);
    context.beginPath(); context.moveTo(left, y); context.lineTo(width - right, y);
    context.strokeStyle = '#edf1f1'; context.lineWidth = 1; context.stroke();
    context.fillStyle = '#9aa5a8'; context.textAlign = 'right';
    context.fillText(String(Math.round(max * (3 - tick) / 3)), left - 8, y);
  }
  const labelStep = Math.max(2, Math.ceil(points.length / Math.max(2, Math.floor(plotWidth / 62))));
  points.forEach((point, index) => {
    const x = left + (points.length <= 1 ? plotWidth / 2 : index * plotWidth / (points.length - 1));
    if (index % labelStep === 0 || index === points.length - 1) {
      context.fillStyle = '#9aa5a8'; context.textAlign = index === 0 ? 'left' : index === points.length - 1 ? 'right' : 'center';
      context.fillText(labelMode === 'day' ? point.day.slice(5) : formatDate(point.time, { month: undefined, day: undefined, hour: '2-digit', minute: '2-digit' }), x, height - 10);
    }
  });
  series.forEach((line, lineIndex) => {
    const values = points.map((_, index) => totalAt[index][lineIndex]);
    context.beginPath();
    values.forEach((value, index) => {
      const x = left + (values.length <= 1 ? plotWidth / 2 : index * plotWidth / (values.length - 1));
      const y = top + plotHeight - (value / max) * plotHeight;
      if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
    });
    context.strokeStyle = line.color; context.lineWidth = 2.4; context.lineJoin = 'round'; context.lineCap = 'round'; context.stroke();
    values.forEach((value, index) => {
      if (!value) return;
      const x = left + (values.length <= 1 ? plotWidth / 2 : index * plotWidth / (values.length - 1));
      const y = top + plotHeight - (value / max) * plotHeight;
      context.beginPath(); context.arc(x, y, 2.7, 0, Math.PI * 2); context.fillStyle = line.color; context.fill();
    });
  });
}

async function loadAdmin() {
  $$('.admin-tab').forEach((button) => button.classList.toggle('active', button.dataset.adminTab === state.activeAdminTab));
  $$('.admin-section').forEach((section) => { section.hidden = section.id !== `admin${state.activeAdminTab[0].toUpperCase()}${state.activeAdminTab.slice(1)}`; });
  try {
    [state.users, state.courses, state.adminSessions] = await Promise.all([
      api('/admin/users'), api('/admin/courses'), api('/admin/sessions'),
    ]);
    refreshAdminSelectors();
    $('#courseTeacher').innerHTML = state.users.filter((item) => item.role === 'teacher').map((item) => `<option value="${item.id}">${escapeHtml(item.full_name)} (${escapeHtml(item.username)})</option>`).join('');
    await loadAdminTab();
  } catch (error) {
    toast(error.message);
  }
}

function refreshAdminSelectors() {
  const sessionOptions = state.adminSessions.map((item) =>
    `<option value="${item.id}">${escapeHtml(item.course_name)} · ${escapeHtml(item.class_name)} · ${formatDate(item.starts_at)}</option>`).join('');
  [['rosterSessionSelect', '选择课堂'], ['adminRecordSession', '全部课堂'], ['adminLiveSessionSelect', '选择实时课堂']].forEach(([id, label]) => {
    const select = $(`#${id}`);
    const previous = select.value;
    select.innerHTML = `<option value="">${label}</option>${sessionOptions}`;
    if ([...select.options].some((option) => option.value === previous)) select.value = previous;
    if (id === 'adminLiveSessionSelect' && !select.value && state.adminSessions.length) {
      select.value = String((state.adminSessions.find((item) => item.status === 'active') || state.adminSessions[0]).id);
    }
  });
  [['scheduleCourse', ''], ['adminRecordCourse', '全部课程'], ['adminStatsCourseFilter', '全部课程']].forEach(([id, label]) => {
    const select = $(`#${id}`);
    const previous = select.value;
    select.innerHTML = `${label ? `<option value="">${label}</option>` : ''}${state.courses.map((course) =>
      `<option value="${course.id}">${escapeHtml(course.name)}${id === 'scheduleCourse' ? ` · ${escapeHtml(course.teacher_name)}` : ''}</option>`).join('')}`;
    if ([...select.options].some((option) => option.value === previous)) select.value = previous;
  });
  const classes = [...new Set(state.adminSessions.map((session) => session.class_name))];
  ['adminRecordClass', 'adminStatsClassFilter'].forEach((id) => {
    const classSelect = $(`#${id}`);
    const previousClass = classSelect.value;
    classSelect.innerHTML = `<option value="">全部班级</option>${classes.map((name) =>
      `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join('')}`;
    if ([...classSelect.options].some((option) => option.value === previousClass)) classSelect.value = previousClass;
  });
}

async function loadAdminTab() {
  stopPolling();
  closeDashboardSocket();
  if (state.activeAdminTab === 'overview') {
    startPolling(loadAdminOverview);
    return loadAdminOverview();
  }
  if (state.activeAdminTab === 'users') return renderUsers();
  if (state.activeAdminTab === 'schedule') return loadScheduleView();
  return loadAdminRecords();
}

async function loadAdminOverview() {
  if ($('#adminView').hidden || state.activeAdminTab !== 'overview') return;
  try {
    const params = queryFilters('adminStats');
    if (params.get('from') && params.get('to') && params.get('from') > params.get('to')) {
      throw new Error('统计开始日期不能晚于结束日期');
    }
    const stats = await api(`/admin/statistics?${params}`);
    if ($('#adminView').hidden || state.activeAdminTab !== 'overview' || queryFilters('adminStats').toString() !== params.toString()) return;
    $('#adminUserCount').textContent = state.users.length;
    $('#adminRecordCount').textContent = stats.total;
    $('#adminActiveCount').textContent = state.adminSessions.filter((item) => item.status === 'active').length;
    $('#adminCourseCount').textContent = state.courses.length;
    renderDistribution($('#adminDistribution'), stats.emotions);
    $('#adminStatsSummary').textContent = `当前筛选共 ${stats.total} 条反馈`;
    $('#adminDailyEmpty').hidden = Boolean(stats.total);
    const days = new Map();
    stats.daily_trend.forEach((item) => {
      if (!days.has(item.day)) days.set(item.day, { day: item.day });
      days.get(item.day)[item.emoji_type] = item.count;
    });
    renderTrend($('#adminDailyTrend'), [...days.values()], 'day');
    renderBreakdown($('#adminCourseBreakdown'), stats.by_course.map((item) => ({ label: item.course_name, count: item.total })));
    renderBreakdown($('#adminClassBreakdown'), stats.by_class.map((item) => ({ label: item.class_name, count: item.total })));
    await loadAdminLiveDashboard();
  } catch (error) {
    toast(error.message);
  }
}

function renderBreakdown(container, items) {
  const max = Math.max(1, ...items.map((item) => item.count));
  container.innerHTML = items.map((item) => `<div class="breakdown-item"><span>${escapeHtml(item.label)}</span><span class="progress-track"><i style="width:${item.count / max * 100}%"></i></span><b>${item.count}</b></div>`).join('')
    || '<div class="empty-state">当前筛选范围暂无反馈</div>';
}

async function loadAdminLiveDashboard() {
  if ($('#adminView').hidden || state.activeAdminTab !== 'overview') return;
  const sessionId = $('#adminLiveSessionSelect').value;
  if (!sessionId) {
    closeDashboardSocket();
    renderAdminLiveUpdate(null);
    return;
  }
  try {
    const realtime = await api(`/admin/dashboard/realtime?sessionId=${encodeURIComponent(sessionId)}`);
    if ($('#adminLiveSessionSelect').value !== sessionId || $('#adminView').hidden || state.activeAdminTab !== 'overview') return;
    renderAdminLiveUpdate(realtime);
    connectDashboardSocket(sessionId, 'admin');
  } catch (error) { toast(error.message); }
}

function renderAdminLiveUpdate(realtime) {
  if ($('#adminView').hidden || state.activeAdminTab !== 'overview') return;
  const total = realtime?.total_last_hour || 0;
  const counts = Object.fromEntries((realtime?.counts || []).map((item) => [item.type, item.count]));
  $('#adminLiveTotal').textContent = total;
  $('#adminLivePositive').textContent = `${total ? Math.round(((counts.happy || 0) + (counts.excited || 0)) / total * 100) : 0}%`;
  $('#adminLiveFocused').textContent = `${total ? Math.round((counts.focused || 0) / total * 100) : 0}%`;
  const session = state.adminSessions.find((item) => String(item.id) === String(realtime?.session.id));
  $('#adminLiveStudents').textContent = session?.student_count || 0;
  $('#adminLiveEmpty').hidden = Boolean(total);
  renderTrend($('#adminLiveTrend'), realtime?.trend || []);
  renderDistribution($('#adminLiveDistribution'), realtime?.counts || []);
  $('#adminRecent').innerHTML = recordRows(realtime?.recent || []);
  $('#adminLiveUpdated').textContent = realtime ? `更新于 ${formatDate(realtime.generated_at)} · 实时推送 / 10 秒轮询` : '暂无课堂';
}

async function createInvitation(event) {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button');
  button.disabled = true;
  $('#invitationResult').hidden = true;
  $('#invitationCode').value = '';
  try {
    const fields = Object.fromEntries(new FormData(event.currentTarget).entries());
    const invitation = await api('/admin/invitations', { method: 'POST', body: JSON.stringify({ role: fields.role, expires_in_hours: Number(fields.expires_in_hours) }) });
    $('#invitationCode').value = invitation.code;
    $('#invitationMessage').textContent = `${roleLabel(invitation.role)}邀请码 · ${formatDate(invitation.expires_at)} 前有效 · 仅可注册一次`;
    $('#invitationResult').hidden = false;
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; }
}

function renderUsers() {
  $('#usersTable').innerHTML = state.users.map((user) => `
    <tr><td>${escapeHtml(user.full_name)}</td><td>${escapeHtml(user.username)}</td>
      <td><select class="inline-select" data-role-user="${user.id}" aria-label="${escapeHtml(user.username)} 角色">
        ${['student', 'teacher', 'admin'].map((role) => `<option value="${role}" ${user.role === role ? 'selected' : ''}>${roleLabel(role)}</option>`).join('')}
      </select></td>
      <td><select class="inline-select" data-status-user="${user.id}" aria-label="${escapeHtml(user.username)} 状态">
        <option value="active" ${user.status === 'active' ? 'selected' : ''}>正常</option><option value="disabled" ${user.status === 'disabled' ? 'selected' : ''}>停用</option>
      </select></td><td>${formatDate(user.created_at, { year: 'numeric' })}</td><td><button class="button button-outline user-save" data-save-user="${user.id}">保存</button></td></tr>`).join('') || '<tr><td colspan="6">暂无用户</td></tr>';
  $$('[data-save-user]').forEach((button) => button.addEventListener('click', () => updateUser(button.dataset.saveUser)));
}

async function updateUser(userId) {
  const role = $(`[data-role-user="${userId}"]`).value;
  const status = $(`[data-status-user="${userId}"]`).value;
  try {
    const updated = await api(`/admin/users/${userId}`, { method: 'PUT', body: JSON.stringify({ role, status }) });
    state.users = state.users.map((user) => user.id === updated.id ? { ...user, ...updated } : user);
    renderUsers();
    toast('用户信息已更新');
  } catch (error) { toast(error.message); }
}

async function loadScheduleView() {
  const sessionId = $('#rosterSessionSelect').value;
  $('#adminSessionsTable').innerHTML = state.adminSessions.map((item) => `<tr><td>${escapeHtml(item.course_name)}</td><td>${escapeHtml(item.class_name)}</td><td>${escapeHtml(item.room || '—')}</td><td>${formatDate(item.starts_at)}</td><td>${escapeHtml(({ active: '进行中', scheduled: '待开始', ended: '已结束' })[item.status])}</td><td>${item.student_count}</td></tr>`).join('') || '<tr><td colspan="6">暂无课堂安排</td></tr>';
  $('#studentRoster').innerHTML = state.users.filter((user) => user.role === 'student' && user.status === 'active').map((user) => `
    <label class="roster-option"><input type="checkbox" value="${user.id}"><span>${escapeHtml(user.full_name)} · ${escapeHtml(user.username)}</span></label>`).join('') || '<span class="muted">暂无可安排的学生账号</span>';
  $('#rosterCount').textContent = `${state.users.filter((user) => user.role === 'student' && user.status === 'active').length} 名可选学生`;
  if (sessionId) {
    try {
      const assigned = await api(`/admin/sessions/${sessionId}/schedule`);
      const ids = new Set(assigned.map((item) => String(item.id)));
      $$(`#studentRoster input`).forEach((input) => { input.checked = ids.has(input.value); });
    } catch (error) { setMessage($('#scheduleMessage'), error.message, 'error'); }
  }
}

async function saveSchedule() {
  const sessionId = $('#rosterSessionSelect').value;
  const userIds = $$('#studentRoster input:checked').map((input) => Number(input.value));
  if (!sessionId) return setMessage($('#scheduleMessage'), '请先选择课堂', 'error');
  try {
    await api(`/admin/sessions/${sessionId}/schedule`, { method: 'POST', body: JSON.stringify({ user_ids: userIds }) });
    setMessage($('#scheduleMessage'), `已安排 ${userIds.length} 名学生`, 'success');
    state.adminSessions = await api('/admin/sessions');
    refreshAdminSelectors();
    await loadScheduleView();
  } catch (error) { setMessage($('#scheduleMessage'), error.message, 'error'); }
}

async function createCourse(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form).entries());
  payload.teacher_id = Number(payload.teacher_id);
  try {
    await api('/admin/courses', { method: 'POST', body: JSON.stringify(payload) });
    form.reset();
    setMessage($('#courseFormMessage'), '课程已创建', 'success');
    state.courses = await api('/admin/courses');
    refreshAdminSelectors();
  } catch (error) { setMessage($('#courseFormMessage'), error.message, 'error'); }
}

async function createSession(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form).entries());
  payload.course_id = Number(payload.course_id);
  for (const field of ['starts_at', 'ends_at']) payload[field] = new Date(payload[field]).toISOString();
  try {
    await api('/admin/sessions', { method: 'POST', body: JSON.stringify(payload) });
    form.reset();
    setMessage($('#sessionFormMessage'), '课堂已创建', 'success');
    state.adminSessions = await api('/admin/sessions');
    refreshAdminSelectors();
    await loadScheduleView();
  } catch (error) { setMessage($('#sessionFormMessage'), error.message, 'error'); }
}

async function loadAdminRecords() {
  const params = new URLSearchParams({ limit: '500' });
  if ($('#adminRecordCourse').value) params.set('course_id', $('#adminRecordCourse').value);
  if ($('#adminRecordClass').value) params.set('class_name', $('#adminRecordClass').value);
  if ($('#adminRecordSession').value) params.set('session_id', $('#adminRecordSession').value);
  if ($('#adminRecordSource').value) params.set('source', $('#adminRecordSource').value);
  if ($('#adminRecordFrom').value) params.set('from', dateFilterBoundary($('#adminRecordFrom').value));
  if ($('#adminRecordTo').value) params.set('to', dateFilterBoundary($('#adminRecordTo').value, true));
  try {
    const records = await api(`/emoji/history?${params}`);
    $('#adminRecordsTable').innerHTML = records.map((record) => `<tr><td>${escapeHtml(record.user_name)}</td><td>${escapeHtml(record.course_name)} / ${escapeHtml(record.class_name)}</td><td>${record.emoji} ${escapeHtml(record.label)}</td><td>${formatDate(record.recorded_at)}</td><td><span class="source-tag ${record.source === 'AI' ? 'ai' : ''}">${record.source === 'AI' ? 'AI' : '手动'}</span></td><td>${record.confidence == null ? '—' : `${Math.round(record.confidence * 100)}%`}</td></tr>`).join('') || '<tr><td colspan="6">没有符合条件的记录</td></tr>';
    $('#exportCsvButton').dataset.exportQuery = params.toString();
  } catch (error) { toast(error.message); }
}

async function downloadCsv() {
  const query = $('#exportCsvButton').dataset.exportQuery || '';
  try {
    const result = await api(`/admin/emoji/export${query ? `?${query}` : ''}`);
    const disposition = result.headers.get('Content-Disposition') || '';
    const filename = disposition.match(/filename=([^;]+)/i)?.[1]?.replaceAll('"', '') || 'emoji-records.csv';
    const objectUrl = URL.createObjectURL(await result.blob());
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = filename;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    toast('CSV 已导出');
  } catch (error) { toast(error.message); }
}

function startPolling(callback) {
  stopPolling();
  state.pollTimer = setInterval(() => callback().catch(() => {}), 10000);
}
function stopPolling() { if (state.pollTimer) clearInterval(state.pollTimer); state.pollTimer = null; }

async function pingBackend() {
  const status = $('#connectionStatus');
  try {
    await fetch('/health');
    status.classList.remove('offline');
    status.innerHTML = '<i></i>服务在线';
  } catch {
    status.classList.add('offline');
    status.innerHTML = '<i></i>连接失败';
  }
}

$('#authForm').addEventListener('submit', submitAuth);
$('#switchAuthMode').addEventListener('click', () => setAuthMode(!state.register));
$('#authRole').addEventListener('change', () => { $('#authRegistrationCode').value = ''; updateRegistrationRole(); });
$('#invitationForm').addEventListener('submit', createInvitation);
$('#adminApplyStatsFilter').addEventListener('click', loadAdminOverview);
$('#adminLiveSessionSelect').addEventListener('change', loadAdminLiveDashboard);
$('#logoutButton').addEventListener('click', () => signOut());
$('#changePasswordButton').addEventListener('click', () => {
  $('#passwordMessage').hidden = true;
  $('#changePasswordDialog').showModal();
});
$('#closePasswordDialog').addEventListener('click', () => $('#changePasswordDialog').close());
$('#passwordForm').addEventListener('submit', changePassword);
$('#openLoginButton').addEventListener('click', () => { window.scrollTo({ top: 0, behavior: 'smooth' }); $('#authUsername').focus(); });
$('#studentSessionSelect').addEventListener('change', updateSelectedSession);
$('#teacherSessionSelect').addEventListener('change', loadTeacherDashboard);
$('#teacherApplyFilter').addEventListener('click', loadTeacherDashboard);
$('#rosterSessionSelect').addEventListener('change', loadScheduleView);
$('#saveScheduleButton').addEventListener('click', saveSchedule);
$('#courseForm').addEventListener('submit', createCourse);
$('#sessionForm').addEventListener('submit', createSession);
$('#adminRecordSearch').addEventListener('click', loadAdminRecords);
$('#exportCsvButton').addEventListener('click', downloadCsv);
$$('[data-view]').forEach((button) => {
  if (!button.closest('#mainNav')) button.addEventListener('click', () => navigate(button.dataset.view));
});
$$('.admin-tab').forEach((button) => button.addEventListener('click', async () => {
  state.activeAdminTab = button.dataset.adminTab;
  $$('.admin-tab').forEach((tab) => tab.classList.toggle('active', tab === button));
  $$('.admin-section').forEach((section) => { section.hidden = section.id !== `admin${state.activeAdminTab[0].toUpperCase()}${state.activeAdminTab.slice(1)}`; });
  await loadAdminTab();
}));

window.addEventListener('resize', () => {
  if (state.user?.role === 'teacher' && !$('#teacherView').hidden) loadTeacherDashboard();
  if (state.user?.role === 'admin' && !$('#adminView').hidden && state.activeAdminTab === 'overview') loadAdminOverview();
});

pingBackend();
restoreSession();
