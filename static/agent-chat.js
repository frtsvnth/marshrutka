(function () {
  'use strict';

  if (typeof marked === 'undefined') {
    setTimeout(function () { window.dispatchEvent(new Event('agentChatReady')); }, 100);
  }

  var els = {};
  var state = {
    sessionId: '',
    messages: [],
    eventTrace: [],
    isStreaming: false,
    draft: '',
    isOpen: true,
  };

  var STORAGE_KEY = 'marshrutka_agent_state';

  function init() {
    els.panel = document.getElementById('aiPanel');
    els.messages = document.getElementById('aiChatMessages');
    els.textarea = document.querySelector('.ai-composer textarea');
    els.sendBtn = document.querySelector('.send-btn');
    els.voiceBtn = document.querySelector('.voice-btn');
    els.copyDialogBtn = document.getElementById('copyDialogBtn');
    els.copyTraceBtn = document.getElementById('copyTraceBtn');
    els.downloadTraceBtn = document.getElementById('downloadTraceBtn');

    if (!els.messages) return;
    restoreState();
    setupListeners();
    setTimeout(restoreFromServer, 200);
  }

  function restoreState() {
    try {
      var saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        var s = JSON.parse(saved);
        state.messages = s.messages || [];
        state.eventTrace = s.eventTrace || [];
        state.sessionId = s.sessionId || '';
        state.draft = s.draft || '';
        if (els.textarea) {
          els.textarea.value = state.draft;
          autoResize(els.textarea);
        }
        state.isOpen = s.isOpen !== false;
      }
    } catch (e) {}
    if (state.messages.length > 0) {
      renderAllMessages();
    }
    if (state.isOpen && els.panel) {
      els.panel.classList.remove('Hidden');
    } else if (els.panel) {
      els.panel.classList.add('Hidden');
    }
  }

  function persistState() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        sessionId: state.sessionId,
        messages: state.messages,
        eventTrace: state.eventTrace,
        draft: els.textarea ? els.textarea.value : '',
        isOpen: state.isOpen,
      }));
    } catch (e) {}
  }

  function restoreFromServer() {
    if (!state.sessionId) return;
    fetch('/api/agent/state/load?session_id=' + encodeURIComponent(state.sessionId))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.messages && data.messages.length > 0) {
          state.messages = data.messages;
          state.eventTrace = data.eventTrace || [];
          renderAllMessages();
          persistState();
        }
      })
      .catch(function () {});
  }

  function saveToServer() {
    if (!state.sessionId) return;
    var body = JSON.stringify({
      session_id: state.sessionId,
      messages: state.messages.slice(-50),
      eventTrace: state.eventTrace.slice(-200),
      draft: els.textarea ? els.textarea.value : '',
    });
    navigator.sendBeacon('/api/agent/state/save', new Blob([body], { type: 'application/json' }));
  }

  function renderAllMessages() {
    var container = els.messages;
    if (!container) return;
    hideWelcome();
    var existing = container.querySelectorAll('.ai-message, .ai-tool-event, .ai-error');
    for (var i = 0; i < existing.length; i++) {
      existing[i].remove();
    }
    for (var i = 0; i < state.messages.length; i++) {
      var m = state.messages[i];
      if (m.type === 'tool_event') {
        addToolEventDOM(m.toolName, m.summary);
      } else if (m.type === 'error') {
        showErrorDOM(m.content);
      } else {
        addMessageDOM(m.role, m.content, false);
      }
    }
    scrollToBottom();
  }

  function hideWelcome() {
    var w = els.messages.querySelector('.ai-welcome');
    if (w) { w.style.display = 'none'; }
  }

  function showWelcome() {
    var w = els.messages.querySelector('.ai-welcome');
    if (w) { w.style.display = ''; }
  }

  function scrollToBottom() {
    els.messages.scrollTop = els.messages.scrollHeight;
  }

  function addMessageDOM(role, content, isStreaming) {
    var div = document.createElement('div');
    div.className = 'ai-message ' + role;
    var bubble = document.createElement('div');
    bubble.className = 'bubble';
    if (isStreaming) bubble.classList.add('streaming');
    div.appendChild(bubble);
    if (els.messages) {
      els.messages.appendChild(div);
    }
    if (content) {
      setBubbleContent(bubble, content);
    }
    scrollToBottom();
    return bubble;
  }

  function setBubbleContent(bubble, content) {
    if (typeof marked !== 'undefined') {
      var html = marked.parse(content, { breaks: true, gfm: true });
      bubble.innerHTML = html;
    } else {
      bubble.textContent = content;
    }
  }

  function toolIcon(name) {
    if (name.indexOf('youtube') !== -1) return '\u25B6';
    if (name.indexOf('search_web') !== -1 || name.indexOf('search') !== -1) return '\uD83C\uDF10';
    if (name.indexOf('fetch_url') !== -1 || name.indexOf('research') !== -1) return '\uD83D\uDD0D';
    if (name.indexOf('file') !== -1 || name.indexOf('patch') !== -1) return '\uD83D\uDCC4';
    if (name.indexOf('analyze') !== -1) return '\uD83D\uDCCA';
    if (name.indexOf('remember') !== -1 || name.indexOf('memory') !== -1) return '\uD83E\uDDE0';
    return '\u2699';
  }

  function addToolEventDOM(toolName, summary) {
    var div = document.createElement('div');
    div.className = 'ai-tool-event';
    div.innerHTML =
      '<span class="tool-icon">' + toolIcon(toolName) + '</span>' +
      '<span class="tool-label">' + escapeHtml(toolName) + '</span>' +
      '<span class="tool-summary">' + escapeHtml(summary) + '</span>';
    if (els.messages) els.messages.appendChild(div);
    scrollToBottom();
    return div;
  }

  function showErrorDOM(message) {
    var div = document.createElement('div');
    div.className = 'ai-error';
    div.textContent = '\u26A0 ' + message;
    if (els.messages) els.messages.appendChild(div);
    scrollToBottom();
  }

  function escapeHtml(str) {
    var d = document.createElement('div');
    d.appendChild(document.createTextNode(str));
    return d.innerHTML;
  }

  function setInputEnabled(enabled) {
    if (els.textarea) els.textarea.disabled = !enabled;
    if (els.sendBtn) els.sendBtn.disabled = !enabled;
    if (els.voiceBtn) els.voiceBtn.disabled = !enabled;
    if (enabled && els.textarea) { els.textarea.focus(); }
  }

  function formatDialog() {
    var lines = [];
    for (var i = 0; i < state.messages.length; i++) {
      var m = state.messages[i];
      if (m.type === 'tool_event' || m.type === 'error') continue;
      lines.push('[' + m.role + ']');
      lines.push(m.content);
      lines.push('');
    }
    return lines.join('\n').trim();
  }

  function formatTrace() {
    return JSON.stringify({
      session_id: state.sessionId,
      exported_at: new Date().toISOString(),
      message_count: state.messages.length,
      event_count: state.eventTrace.length,
      messages: state.messages,
      events: state.eventTrace,
    }, null, 2);
  }

  function showTranscriptModal(title, content) {
    var existing = document.querySelector('.ai-transcript-overlay');
    if (existing) existing.remove();
    var overlay = document.createElement('div');
    overlay.className = 'ai-transcript-overlay open';
    overlay.innerHTML =
      '<div class="ai-transcript-card">' +
      '  <div class="ai-transcript-header">' +
      '    <span class="ai-transcript-title">' + escapeHtml(title) + '</span>' +
      '    <button class="ai-transcript-close" onclick="this.closest(\'.ai-transcript-overlay\').remove()">\u2715</button>' +
      '  </div>' +
      '  <div class="ai-transcript-body"><pre>' + escapeHtml(content) + '</pre></div>' +
      '  <div class="ai-transcript-actions">' +
      '    <button onclick="var p=this.closest(\'.ai-transcript-overlay\').querySelector(\'pre\');navigator.clipboard.writeText(p.textContent);this.textContent=\'\u2713 Copied\';setTimeout(function(){this.textContent=\'\uD83D\uDCCB Copy\'}.bind(this),1500)">\uD83D\uDCCB Copy</button>' +
      '  </div>' +
      '</div>';
    document.body.appendChild(overlay);
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) overlay.remove();
    });
  }

  window.copyDialog = function () {
    var text = formatDialog();
    if (!text) return;
    showTranscriptModal('Dialog Transcript', text);
  };

  window.copyTrace = function () {
    var text = formatTrace();
    if (!text) return;
    showTranscriptModal('Debug Trace', text);
  };

  window.downloadTrace = function () {
    var text = formatTrace();
    if (!text) return;
    var blob = new Blob([text], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = 'marshal-trace-' + (state.sessionId || 'unknown') + '.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  window.clearChat = function () {
    state.messages = [];
    state.eventTrace = [];
    state.draft = '';
    if (els.textarea) els.textarea.value = '';
    persistState();
    var container = els.messages;
    if (container) {
      var items = container.querySelectorAll('.ai-message, .ai-tool-event, .ai-error');
      for (var i = 0; i < items.length; i++) items[i].remove();
      var w = container.querySelector('.ai-welcome');
      if (w) w.style.display = '';
    }
  };

  function addToolEvent(toolName, summary) {
    state.messages.push({ type: 'tool_event', role: 'tool', toolName: toolName, summary: summary });
    addToolEventDOM(toolName, summary);
    persistState();
  }

  function showError(message) {
    state.messages.push({ type: 'error', role: 'error', content: message });
    showErrorDOM(message);
    persistState();
  }

  async function sendMessage(text) {
    if (!text.trim() || state.isStreaming) return;
    state.isStreaming = true;
    hideWelcome();
    state.messages.push({ role: 'user', content: text });
    var userBubble = addMessageDOM('user', text, false);
    var asstBubble = addMessageDOM('assistant', '', true);
    setInputEnabled(false);
    persistState();
    var fullResponse = '';
    var lastMessageDone = false;
    try {
      var resp = await fetch('/api/agent/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: state.sessionId }),
      });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      var reader = resp.body.getReader();
      var decoder = new TextDecoder();
      var buffer = '';
      var eventType = '';
      while (true) {
        var readResult = await reader.read();
        if (readResult.done) break;
        buffer += decoder.decode(readResult.value, { stream: true });
        while (buffer.length > 0) {
          var idx = buffer.indexOf('\n');
          if (idx === -1) break;
          var line = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 1);
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith('data: ')) {
            handleOneEvent(eventType, line.slice(6).trim());
          }
        }
      }
    } catch (err) {
      if (!lastMessageDone) {
        asstBubble.textContent = '\u274C Connection error: ' + err.message;
      }
    } finally {
      state.isStreaming = false;
      asstBubble.classList.remove('streaming');
      setInputEnabled(true);
      scrollToBottom();
      persistState();
      saveToServer();
    }
    if (fullResponse.trim() && !lastMessageDone) {
      setBubbleContent(asstBubble, fullResponse);
    }

    function handleOneEvent(evType, rawData) {
      var data;
      try { data = JSON.parse(rawData); } catch (e) { return; }
      var type = data.type || evType;
      state.eventTrace.push({ type: type, data: data, ts: Date.now() });
      switch (type) {
        case 'session':
          state.sessionId = data.session_id || '';
          persistState();
          break;
        case 'token':
          if (data.content) {
            asstBubble.textContent += data.content;
            fullResponse += data.content;
            scrollToBottom();
          }
          break;
        case 'tool_start':
          addToolEvent(data.tool_name || 'tool', '\u2026');
          break;
        case 'tool_result':
          var summary = data.result_summary || 'done';
          if (data.duration_ms) summary += ' (' + data.duration_ms + 'ms)';
          addToolEvent(data.tool_name || 'tool', summary);
          break;
        case 'message_start':
          break;
        case 'message_done':
          if (data.content) {
            setBubbleContent(asstBubble, data.content);
            fullResponse = data.content;
            lastMessageDone = true;
            scrollToBottom();
          }
          break;
        case 'error':
          showError(data.message || 'Unknown error');
          break;
        case 'done':
          break;
      }
    }
  }

  function sendCurrentMessage() {
    var text = els.textarea.value.trim();
    if (text) {
      els.textarea.value = '';
      els.textarea.style.height = 'auto';
      state.draft = '';
      persistState();
      sendMessage(text);
    }
  }

  function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 80) + 'px';
  }

  function setupListeners() {
    if (els.textarea) {
      els.textarea.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          sendCurrentMessage();
        }
      });
      els.textarea.addEventListener('input', function () {
        autoResize(this);
        state.draft = this.value;
        persistState();
      });
    }
    if (els.sendBtn) {
      els.sendBtn.addEventListener('click', sendCurrentMessage);
    }
    if (els.voiceBtn) {
      els.voiceBtn.addEventListener('click', startVoiceRecording);
    }
    if (els.copyDialogBtn) {
      els.copyDialogBtn.addEventListener('click', window.copyDialog);
    }
    if (els.copyTraceBtn) {
      els.copyTraceBtn.addEventListener('click', window.copyTrace);
    }
    if (els.downloadTraceBtn) {
      els.downloadTraceBtn.addEventListener('click', window.downloadTrace);
    }
  }

  var mediaRecorder = null;
  var audioChunks = [];

  function startVoiceRecording() {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
      mediaRecorder.stop();
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showError('Voice recording not supported in this browser');
      return;
    }
    navigator.mediaDevices.getUserMedia({ audio: true })
      .then(function (stream) {
        audioChunks = [];
        mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
        mediaRecorder.ondataavailable = function (e) {
          if (e.data.size > 0) audioChunks.push(e.data);
        };
        mediaRecorder.onstop = function () {
          var tracks = stream.getTracks();
          for (var i = 0; i < tracks.length; i++) tracks[i].stop();
          var blob = new Blob(audioChunks, { type: 'audio/webm' });
          uploadAudio(blob);
        };
        mediaRecorder.start();
        if (els.voiceBtn) els.voiceBtn.classList.add('recording');
      })
      .catch(function () {
        showError('Microphone access denied');
      });
  }

  async function uploadAudio(blob) {
    if (els.voiceBtn) els.voiceBtn.classList.remove('recording');
    setInputEnabled(false);
    var msg = '[Transcribing audio\u2026]';
    var dummyBubble = addMessageDOM('assistant', msg);
    try {
      var formData = new FormData();
      formData.append('file', blob, 'recording.webm');
      var resp = await fetch('/api/agent/transcribe', { method: 'POST', body: formData });
      var result = await resp.json();
      if (result.error) {
        showError('Recognition error: ' + result.error);
        dummyBubble.remove();
        setInputEnabled(true);
        return;
      }
      var text = result.text || '';
      if (text) {
        dummyBubble.remove();
        sendMessage(text);
      }
    } catch (err) {
      showError('Voice upload failed');
      dummyBubble.remove();
    }
    setInputEnabled(true);
  }

  window.aiSendQuick = function (el) {
    var text = el.textContent.replace(/^[^\s]+\s/, '').trim();
    sendMessage(text);
  };

  window.toggleAiPanel = function () {
    if (!els.panel) return;
    els.panel.classList.toggle('Hidden');
    state.isOpen = !els.panel.classList.contains('Hidden');
    persistState();
    var btn = document.getElementById('aiToggleBtn');
    if (btn) {
      btn.textContent = state.isOpen ? '\u25C0' : '\u25B6';
    }
  };

  window.clearChatHistory = function () {
    if (state.sessionId) {
      fetch('/api/agent/history?session_id=' + encodeURIComponent(state.sessionId), { method: 'DELETE' }).catch(function () {});
    }
    window.clearChat();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.addEventListener('beforeunload', function () {
    persistState();
    saveToServer();
  });
})();
