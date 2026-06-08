(function () {
  'use strict';

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

  /* ── Init ── */
  function init() {
    els.panel = document.getElementById('aiPanel');
    els.messages = document.getElementById('aiChatMessages');
    els.textarea = document.querySelector('.ai-panel .ai-composer textarea');
    els.sendBtn = document.querySelector('.ai-composer .send-btn');
    els.voiceBtn = document.querySelector('.ai-composer .voice-btn');
    els.copyDialogBtn = document.getElementById('copyDialogBtn');
    els.copyTraceBtn = document.getElementById('copyTraceBtn');
    els.downloadTraceBtn = document.getElementById('downloadTraceBtn');

    if (!els.messages) return;
    restoreState();
    setupListeners();
  }

  /* ── localStorage persistence ── */
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
    } catch (e) { /* ignore */ }
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
    } catch (e) { /* ignore */ }
  }

  /* ── DOM rendering ── */
  function renderAllMessages() {
    var container = els.messages;
    if (!container) return;
    hideWelcome();
    var existing = container.querySelectorAll('.ai-message, .ai-tool-event, .ai-error, .ai-step');
    for (var i = 0; i < existing.length; i++) {
      existing[i].remove();
    }
    for (var i = 0; i < state.messages.length; i++) {
      var m = state.messages[i];
      if (m.type === 'tool_event') {
        addToolEventDOM(m.toolName, m.summary);
      } else if (m.type === 'step_start') {
        /* skip — rendered implicitly */
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
    if (w) w.style.display = 'none';
  }

  function showWelcome() {
    var w = els.messages.querySelector('.ai-welcome');
    if (w) w.style.display = '';
  }

  function scrollToBottom() {
    if (els.messages) {
      els.messages.scrollTop = els.messages.scrollHeight;
    }
  }

  function addMessageDOM(role, content, isStreaming) {
    var div = document.createElement('div');
    div.className = 'ai-message ' + role;
    var bubble = document.createElement('div');
    bubble.className = 'bubble';
    if (isStreaming) bubble.classList.add('streaming');
    div.appendChild(bubble);
    if (els.messages) els.messages.appendChild(div);
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

  /* ── Step container for tool-first rendering ── */
  var _currentStepEl = null;
  var _currentStepToolsEl = null;

  function beginStep() {
    _currentStepEl = document.createElement('div');
    _currentStepEl.className = 'ai-step';
    _currentStepToolsEl = document.createElement('div');
    _currentStepToolsEl.className = 'ai-step-tools';
    _currentStepEl.appendChild(_currentStepToolsEl);
    if (els.messages) els.messages.appendChild(_currentStepEl);
    scrollToBottom();
  }

  function addToolToStep(toolName, summary) {
    if (!_currentStepToolsEl) beginStep();
    var div = document.createElement('div');
    div.className = 'ai-tool-event';
    div.innerHTML =
      '<span class="tool-icon">' + toolIcon(toolName) + '</span>' +
      '<span class="tool-label">' + escapeHtml(toolName) + '</span>' +
      '<span class="tool-summary">' + escapeHtml(summary) + '</span>';
    _currentStepToolsEl.appendChild(div);
    scrollToBottom();
  }

  function finishStepWithContent(content) {
    if (_currentStepEl) {
      var div = document.createElement('div');
      div.className = 'ai-message assistant';
      var bubble = document.createElement('div');
      bubble.className = 'bubble';
      div.appendChild(bubble);
      _currentStepEl.appendChild(div);
      if (content) setBubbleContent(bubble, content);
      scrollToBottom();
    }
    _currentStepEl = null;
    _currentStepToolsEl = null;
  }

  function abortStep(fallbackContent) {
    if (_currentStepEl) {
      _currentStepEl.remove();
    }
    if (fallbackContent) {
      addMessageDOM('assistant', fallbackContent, false);
    }
    _currentStepEl = null;
    _currentStepToolsEl = null;
  }

  /* ── Tool icons ── */
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
    if (!_currentStepToolsEl) beginStep();
    var div = document.createElement('div');
    div.className = 'ai-tool-event';
    div.innerHTML =
      '<span class="tool-icon">' + toolIcon(toolName) + '</span>' +
      '<span class="tool-label">' + escapeHtml(toolName) + '</span>' +
      '<span class="tool-summary">' + escapeHtml(summary) + '</span>';
    if (_currentStepToolsEl) _currentStepToolsEl.appendChild(div);
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

  /* ── Input state ── */
  function setInputEnabled(enabled) {
    if (els.textarea) els.textarea.disabled = !enabled;
    if (els.sendBtn) els.sendBtn.disabled = !enabled;
    if (els.voiceBtn) els.voiceBtn.disabled = !enabled;
    if (enabled && els.textarea) els.textarea.focus();
  }

  /* ── Dialog / Trace formatting ── */
  function formatDialog() {
    var lines = [];
    for (var i = 0; i < state.messages.length; i++) {
      var m = state.messages[i];
      if (m.type === 'tool_event' || m.type === 'error' || m.type === 'step_start') continue;
      lines.push('[' + m.role + ']');
      lines.push(m.content || '');
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

  /* ── Toast ── */
  function showToast(msg) {
    var el = document.querySelector('.ai-toast');
    if (!el) {
      el = document.createElement('div');
      el.className = 'ai-toast';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(el._hideTimer);
    el._hideTimer = setTimeout(function () { el.classList.remove('show'); }, 1800);
  }

  /* ── Clipboard helpers ── */
  function copyToClipboard(text, label) {
    if (!text) { showToast('Nothing to copy'); return; }
    navigator.clipboard.writeText(text).then(function () {
      showToast(label || '\u2713 Copied');
    }).catch(function () {
      fallbackCopy(text, label);
    });
  }

  function fallbackCopy(text, label) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand('copy');
      showToast(label || '\u2713 Copied');
    } catch (e) {
      showToast('Copy failed');
    }
    document.body.removeChild(ta);
  }

  /* ── Button handlers ── */
  window.copyDialog = function () {
    copyToClipboard(formatDialog(), '\u2713 Dialog copied');
  };

  window.copyTrace = function () {
    copyToClipboard(formatTrace(), '\u2713 Trace copied');
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
      var items = container.querySelectorAll('.ai-message, .ai-tool-event, .ai-error, .ai-step');
      for (var i = 0; i < items.length; i++) items[i].remove();
      var w = container.querySelector('.ai-welcome');
      if (w) w.style.display = '';
    }
    abortStep();
  };

  window.clearChatHistory = function () {
    if (state.sessionId) {
      fetch('/api/agent/history?session_id=' + encodeURIComponent(state.sessionId), { method: 'DELETE' }).catch(function () {});
    }
    window.clearChat();
  };

  /* ── Tool event logging (replay-safe) ── */
  function addToolEvent(toolName, summary) {
    state.messages.push({ type: 'tool_event', role: 'tool', toolName: toolName, summary: summary });
    addToolToStep(toolName, summary);
    persistState();
  }

  function showError(message) {
    state.messages.push({ type: 'error', role: 'error', content: message });
    showErrorDOM(message);
    persistState();
  }

  /* ── Main send flow ── */
  async function sendMessage(text) {
    if (!text.trim() || state.isStreaming) return;
    state.isStreaming = true;
    hideWelcome();

    state.messages.push({ role: 'user', content: text });
    addMessageDOM('user', text, false);
    setInputEnabled(false);
    persistState();

    var fullResponse = '';
    var lastMessageDone = false;
    var stepHadTools = false;

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
        showError('Connection error: ' + err.message);
      }
    } finally {
      state.isStreaming = false;
      setInputEnabled(true);
      scrollToBottom();
      persistState();
    }

    if (fullResponse.trim() && !lastMessageDone && !stepHadTools) {
      state.messages.push({ role: 'assistant', content: fullResponse });
      addMessageDOM('assistant', fullResponse);
      persistState();
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
            fullResponse += data.content;
            scrollToBottom();
          }
          break;

        case 'tool_start':
          stepHadTools = true;
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
            fullResponse = data.content;
            lastMessageDone = true;
            if (stepHadTools) {
              finishStepWithContent(data.content);
            } else {
              addMessageDOM('assistant', data.content, false);
            }
            state.messages.push({ role: 'assistant', content: data.content });
            persistState();
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

  /* ── Send current message ── */
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

  /* ── Listeners ── */
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
      els.voiceBtn.addEventListener('click', function () {
        showToast('\uD83C\uDFA4 Voice mode coming soon');
      });
    }
    if (els.copyDialogBtn) {
      els.copyDialogBtn.addEventListener('click', function (e) {
        e.preventDefault();
        window.copyDialog();
      });
    }
    if (els.copyTraceBtn) {
      els.copyTraceBtn.addEventListener('click', function (e) {
        e.preventDefault();
        window.copyTrace();
      });
    }
    if (els.downloadTraceBtn) {
      els.downloadTraceBtn.addEventListener('click', window.downloadTrace);
    }
  }

  /* ── Quick chips ── */
  window.aiSendQuick = function (el) {
    var text = el.textContent.replace(/^[^\s]+\s/, '').trim();
    sendMessage(text);
  };

  /* ── Panel toggle ── */
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

  /* ── Boot ── */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.addEventListener('beforeunload', function () {
    persistState();
  });
})();
