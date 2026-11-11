// The camera stays in the administrator's browser. Only sampled frames go to the server.
const aiMonitor = { stream: null, timer: null, controller: null, generation: 0, config: null, starting: false };

function aiPageVisible() {
  return state.user?.role === 'admin' && !$('#adminView').hidden && state.activeAdminTab === 'ai';
}

function resetAiResult() {
  $('#aiResultEmoji').textContent = '—';
  $('#aiResultLabel').textContent = '等待识别';
  $('#aiResultDescription').textContent = '开启摄像头后，这里会显示对应的 emoji 情绪。';
  $('#aiResultConfidence').textContent = '—';
  $('#aiResultSamples').textContent = '—';
  $('#aiConfidenceBar').style.width = '0%';
  $('#aiResultStatus').textContent = '等待采样';
  $('#aiResultStatus').className = 'source-tag';
  $('#aiSampleImage').removeAttribute('src');
  $('#aiSampleImage').hidden = true;
  $('#aiSampleTime').textContent = '尚未采样';
  $('#aiResultSaved').textContent = '达标结果自动保存为匿名 AI 记录';
}

function closeAiMonitor() {
  aiMonitor.generation += 1;
  clearTimeout(aiMonitor.timer);
  aiMonitor.controller?.abort();
  aiMonitor.controller = null;
  aiMonitor.stream?.getTracks().forEach((track) => track.stop());
  aiMonitor.stream = null;
  aiMonitor.starting = false;
  const video = $('#aiCameraVideo');
  video.srcObject = null;
  video.hidden = true;
  $('#aiVideoPlaceholder').hidden = false;
  $('#aiLiveIndicator').hidden = true;
  $('#aiStatusBadge').textContent = '摄像头未开启';
  $('#aiStatusBadge').classList.remove('active');
  $('#aiPreviewState').textContent = '等待开启';
  $('#aiStopButton').disabled = true;
  $('#aiSessionSelect').disabled = false;
  resetAiResult();
  updateAiSessionInfo();
}

function updateAiSessionInfo() {
  const session = state.adminSessions.find((item) => String(item.id) === $('#aiSessionSelect').value);
  const now = Date.now();
  const open = session && session.status === 'active' && new Date(session.starts_at).getTime() <= now
    && now <= new Date(session.ends_at).getTime();
  $('#aiSessionInfo').textContent = session
    ? `课次 ID：${session.id} · ${session.course_name} · ${session.class_name} · ${open ? '开放记录' : '当前未开放'}`
    : '请选择当前开放的课次';
  $('#aiStartButton').disabled = !open || !aiMonitor.config?.configured || Boolean(aiMonitor.stream) || aiMonitor.starting;
  return Boolean(open);
}

async function loadAiMonitor() {
  setMessage($('#aiCameraMessage'), '正在读取识别配置…');
  const generation = aiMonitor.generation;
  try {
    const config = await api('/admin/ai/status');
    if (!aiPageVisible() || generation !== aiMonitor.generation) return;
    aiMonitor.config = config;
    $('#aiModelInfo').textContent = `${config.model} · 置信度阈值 ${Math.round(config.threshold * 100)}% · 每次完成后 ${config.interval} 秒采样`;
    updateAiSessionInfo();
    setMessage($('#aiCameraMessage'), config.configured
      ? '选择开放课次后开启摄像头，首次使用请允许浏览器访问摄像头。'
      : '请先在服务端 .env 填写 AI_API_KEY、AI_BASE_URL 和 AI_MODEL，并重启后端。', config.configured ? '' : 'error');
  } catch (error) {
    if (aiPageVisible()) setMessage($('#aiCameraMessage'), error.message, 'error');
  }
}

async function refreshAiCameraOptions() {
  if (!navigator.mediaDevices?.enumerateDevices) return;
  const devices = (await navigator.mediaDevices.enumerateDevices()).filter((item) => item.kind === 'videoinput');
  const current = aiMonitor.stream?.getVideoTracks()[0]?.getSettings().deviceId || $('#aiCameraSelect').value;
  $('#aiCameraSelect').innerHTML = '<option value="">默认摄像头</option>' + devices.map((device, index) =>
    `<option value="${escapeHtml(device.deviceId)}">${escapeHtml(device.label || `摄像头 ${index + 1}`)}</option>`).join('');
  if (devices.some((item) => item.deviceId === current)) $('#aiCameraSelect').value = current;
}

async function startAiCamera() {
  if (aiMonitor.stream || aiMonitor.starting || !updateAiSessionInfo()) return;
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    setMessage($('#aiCameraMessage'), '浏览器无法访问摄像头，请通过 http://localhost、http://127.0.0.1 或 HTTPS 打开页面。', 'error');
    return;
  }
  const generation = ++aiMonitor.generation;
  aiMonitor.starting = true;
  $('#aiStartButton').disabled = true;
  $('#aiStopButton').disabled = false;
  $('#aiSessionSelect').disabled = true;
  setMessage($('#aiCameraMessage'), '正在请求摄像头权限…');
  try {
    const cameraId = $('#aiCameraSelect').value;
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 }, ...(cameraId ? { deviceId: { exact: cameraId } } : {}) }, audio: false,
    });
    if (generation !== aiMonitor.generation || !aiPageVisible()) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    aiMonitor.stream = stream;
    const video = $('#aiCameraVideo');
    video.srcObject = stream;
    video.hidden = false;
    await video.play();
    if (generation !== aiMonitor.generation) return;
    $('#aiVideoPlaceholder').hidden = true;
    $('#aiLiveIndicator').hidden = false;
    $('#aiStatusBadge').textContent = '摄像头已开启';
    $('#aiStatusBadge').classList.add('active');
    $('#aiPreviewState').textContent = '实时预览中';
    setMessage($('#aiCameraMessage'), '摄像头已开启，正在采样识别。', 'success');
    stream.getVideoTracks()[0]?.addEventListener('ended', () => {
      if (generation !== aiMonitor.generation) return;
      closeAiMonitor();
      setMessage($('#aiCameraMessage'), '摄像头已断开，请重新连接后开启。', 'error');
    });
    refreshAiCameraOptions().catch(() => {});
    sampleAiFrame(generation);
  } catch (error) {
    if (generation !== aiMonitor.generation) return;
    closeAiMonitor();
    const hints = {
      NotAllowedError: '摄像头权限被拒绝，请在浏览器地址栏的站点权限中允许摄像头。',
      NotFoundError: '没有找到摄像头，请连接设备后重试。',
      NotReadableError: '摄像头无法读取，请关闭正在使用它的视频会议或独立 AI 摄像头进程。',
      OverconstrainedError: '所选摄像头不可用，请切换到默认摄像头重试。',
    };
    setMessage($('#aiCameraMessage'), hints[error.name] || '无法开启摄像头，请检查浏览器权限与设备连接。', 'error');
  } finally {
    if (generation === aiMonitor.generation) aiMonitor.starting = false;
  }
}

async function sampleAiFrame(generation) {
  if (generation !== aiMonitor.generation || !aiMonitor.stream || !aiPageVisible()) return;
  const video = $('#aiCameraVideo');
  if (!video.videoWidth || !video.videoHeight) {
    aiMonitor.timer = setTimeout(() => sampleAiFrame(generation), 250);
    return;
  }
  const canvas = document.createElement('canvas');
  const scale = Math.min(640 / video.videoWidth, 480 / video.videoHeight, 1);
  canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
  canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
  canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
  const image = canvas.toDataURL('image/jpeg', 0.75);
  const capturedAt = new Date().toISOString();
  const started = performance.now();
  resetAiResult();
  $('#aiSampleImage').src = image;
  $('#aiSampleImage').hidden = false;
  $('#aiSampleTime').textContent = `采样于 ${formatDate(capturedAt, { second: '2-digit' })}`;
  $('#aiResultStatus').textContent = '识别中';
  $('#aiResultEmoji').textContent = '…';
  $('#aiResultLabel').textContent = '正在识别';
  $('#aiResultDescription').textContent = '正在分析本次采样画面，实时预览持续更新。';
  const controller = new AbortController();
  aiMonitor.controller = controller;
  const timeout = setTimeout(() => controller.abort(), 50000);
  try {
    const result = await api('/admin/ai/analyze', {
      method: 'POST', signal: controller.signal,
      body: JSON.stringify({ session_id: Number($('#aiSessionSelect').value), image }),
    });
    if (generation !== aiMonitor.generation || !aiPageVisible()) return;
    renderAiPrediction(result, (performance.now() - started) / 1000);
  } catch (error) {
    if (generation !== aiMonitor.generation || !aiPageVisible()) return;
    $('#aiResultEmoji').textContent = '—';
    $('#aiResultLabel').textContent = '识别暂不可用';
    $('#aiResultDescription').textContent = error.name === 'AbortError' ? '本次识别超时，稍后重新采样。' : error.message;
    $('#aiResultStatus').textContent = '识别失败';
    $('#aiResultSaved').textContent = '本次未保存识别结果';
    setMessage($('#aiCameraMessage'), $('#aiResultDescription').textContent, 'error');
  } finally {
    clearTimeout(timeout);
    if (generation === aiMonitor.generation && aiMonitor.stream && aiPageVisible()) {
      aiMonitor.controller = null;
      aiMonitor.timer = setTimeout(() => sampleAiFrame(generation), Math.max(1, aiMonitor.config?.interval || 5) * 1000);
    }
  }
}

function renderAiPrediction(result, seconds) {
  const reasons = {
    no_face_detected: ['未检测到人脸', '请正面面对摄像头，并调整距离与光线。'],
    low_confidence: ['置信度不足', '该结果低于保存阈值，仅供预览，本次未入库。'],
    no_supported_emotion: ['暂时无法判断', '当前画面没有可判断的主导情绪，本次未入库。'],
    invalid_model_output: ['模型结果无效', '模型没有返回有效的情绪与置信度，本次未入库。'],
  };
  const fallback = reasons[result.reason] || ['暂时无法判断', '本次未入库。'];
  $('#aiResultEmoji').textContent = result.emoji_type ? emotion(result.emoji_type).emoji : '—';
  $('#aiResultLabel').textContent = result.emoji_type ? emotion(result.emoji_type).label : fallback[0];
  $('#aiResultDescription').textContent = result.accepted
    ? `本次采样中的主导课堂感受 · 识别耗时 ${seconds.toFixed(1)} 秒`
    : fallback[1];
  $('#aiResultConfidence').textContent = result.confidence == null ? '—' : `${Math.round(result.confidence * 100)}%`;
  $('#aiResultSamples').textContent = result.samples ?? '—';
  $('#aiConfidenceBar').style.width = `${Math.max(0, Math.min(100, (result.confidence || 0) * 100))}%`;
  $('#aiResultStatus').textContent = result.accepted ? '已保存' : fallback[0];
  $('#aiResultStatus').className = `source-tag ${result.accepted ? 'ai' : ''}`;
  $('#aiResultSaved').textContent = result.accepted ? `匿名 AI 记录 #${result.id} · 已入库` : '本次未入库';
  setMessage($('#aiCameraMessage'), result.accepted ? '识别完成，结果已保存；等待下一次采样。' : fallback[1], result.accepted ? 'success' : '');
}

document.getElementById('aiStartButton').addEventListener('click', startAiCamera);
document.getElementById('aiStopButton').addEventListener('click', () => {
  closeAiMonitor();
  setMessage($('#aiCameraMessage'), '已停止摄像头与后续采样。');
});
document.getElementById('aiSessionSelect').addEventListener('change', () => {
  closeAiMonitor();
  setMessage($('#aiCameraMessage'), '课次已切换，开启摄像头后开始识别。');
});
document.getElementById('aiCameraSelect').addEventListener('change', () => {
  const wasRunning = Boolean(aiMonitor.stream);
  closeAiMonitor();
  if (wasRunning) startAiCamera();
});
window.addEventListener('pagehide', closeAiMonitor);
