(function() {
  'use strict';

  var messagesEl = document.getElementById('aiChatMessages');
  var textarea = document.querySelector('.ai-composer textarea');
  var sendBtn = document.querySelector('.ai-composer button');
  var sessionId = '';
  var isStreaming = false;
  var eventTrace = [];
  var messages = [];

  function hideWelcome() {
    var w = messagesEl.querySelector('.ai-welcome');
    if (w) w.remove();
  }

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function createMessageEl(role) {
    var div = document.createElement('div');
    div.className = 'ai-message ' + role;
    var bubble = document.createElement('div');
    bubble.className = 'bubble';
    div.appendChild(bubble);
    messagesEl.appendChild(div);
    return bubble;
  }

  function toolIcon(name) {
    if (name.indexOf('youtube') !== -1) return '▶';
    if (name.indexOf('search_web') !== -1 || name.indexOf('search') !== -1) return '🌐';
    return '⚙';
  }

  function addToolEvent(toolName, summary) {
    var div = document.createElement('div');
    div.className = 'ai-tool-event';
    div.innerHTML = '<span class="tool-icon">' + toolIcon(toolName) + '</span>' +
      '<span class="tool-label">' + escapeHtml(toolName) + '</span>' +
      '<span class="tool-summary">' + escapeHtml(summary) + '</span>';
    messagesEl.appendChild(div);
    scrollToBottom();
    return div;
  }

  function showError(message) {
    var div = document.createElement('div');
    div.className = 'ai-error';
    div.textContent = '⚠ ' + message;
    messagesEl.appendChild(div);
    scrollToBottom();
  }

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  function setInputEnabled(enabled) {
    textarea.disabled = !enabled;
    sendBtn.disabled = !enabled;
    if (enabled) {
      textarea.focus();
    }
  }

  function formatDialog() {
    var lines = [];
    for (var i = 0; i < messages.length; i++) {
      var m = messages[i];
      lines.push('[' + m.role + ']');
      lines.push(m.content);
      lines.push('');
    }
    return lines.join('\n').trim();
  }

  function formatTrace() {
    return JSON.stringify({
      session_id: sessionId,
      exported_at: new Date().toISOString(),
      message_count: messages.length,
      event_count: eventTrace.length,
      messages: messages,
      events: eventTrace
    }, null, 2);
  }

  window.copyDialog = function() {
    var text = formatDialog();
    if (!text) return;
    navigator.clipboard.writeText(text).then(function() {
      flashButton('copyDialogBtn', '✓ Скопировано');
    });
  };

  window.copyTrace = function() {
    var text = formatTrace();
    if (!text) return;
    navigator.clipboard.writeText(text).then(function() {
      flashButton('copyTraceBtn', '✓ Скопировано');
    });
  };

  function flashButton(id, msg) {
    var btn = document.getElementById(id);
    if (!btn) return;
    var orig = btn.textContent;
    btn.textContent = msg;
    setTimeout(function() { btn.textContent = orig; }, 2000);
  }

  async function sendMessage(text) {
    if (!text.trim() || isStreaming) return;

    isStreaming = true;
    hideWelcome();

    messages.push({role: 'user', content: text});
    var userBubble = createMessageEl('user');
    userBubble.textContent = text;
    scrollToBottom();

    var asstBubble = createMessageEl('assistant');
    asstBubble.classList.add('streaming');
    scrollToBottom();

    setInputEnabled(false);

    var fullResponse = '';
    var lastMessageDone = false;

    try {
      var resp = await fetch('/api/agent/chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          message: text,
          session_id: sessionId
        })
      });

      if (!resp.ok) throw new Error('HTTP ' + resp.status);

      var reader = resp.body.getReader();
      var decoder = new TextDecoder();
      var sseBuffer = '';
      var eventType = '';
      var eventData = '';

      while (true) {
        var readResult = await reader.read();
        if (readResult.done) break;

        sseBuffer += decoder.decode(readResult.value, {stream: true});

        while (sseBuffer.length > 0) {
          var lineIdx = sseBuffer.indexOf('\n');
          if (lineIdx === -1) break;

          var line = sseBuffer.slice(0, lineIdx);
          sseBuffer = sseBuffer.slice(lineIdx + 1);

          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim();
            eventData = '';
          } else if (line.startsWith('data: ')) {
            eventData = line.slice(6).trim();
            handleOneEvent(eventType, eventData);
          } else if (line === '' && eventType) {
            eventType = '';
            eventData = '';
          }
        }
      }
    } catch (err) {
      if (!lastMessageDone) {
        asstBubble.textContent = '❌ Ошибка соединения: ' + err.message;
      }
    } finally {
      isStreaming = false;
      asstBubble.classList.remove('streaming');
      setInputEnabled(true);
      scrollToBottom();
    }

    if (fullResponse.trim() && !lastMessageDone) {
      asstBubble.textContent = fullResponse;
    }

    function handleOneEvent(evType, rawData) {
      var data;
      try {
        data = JSON.parse(rawData);
      } catch(e) {
        return;
      }

      var type = data.type || evType;
      var traceEntry = {type: type, data: data, ts: Date.now()};
      eventTrace.push(traceEntry);

      switch (type) {
        case 'session':
          sessionId = data.session_id || '';
          break;

        case 'token':
          if (data.content) {
            asstBubble.textContent += data.content;
            fullResponse += data.content;
            scrollToBottom();
          }
          break;

        case 'tool_start':
          addToolEvent(data.tool_name || 'инструмент', '…');
          break;

        case 'tool_result':
          var summary = data.result_summary || 'выполнено';
          if (data.duration_ms) {
            summary += ' (' + data.duration_ms + 'ms)';
          }
          addToolEvent(data.tool_name || 'инструмент', summary);
          break;

        case 'message_start':
          break;

        case 'message_done':
          if (data.content) {
            asstBubble.textContent = data.content;
            fullResponse = data.content;
            lastMessageDone = true;
            scrollToBottom();
          }
          break;

        case 'error':
          showError(data.message || 'Неизвестная ошибка');
          break;

        case 'done':
          isStreaming = false;
          break;
      }
    }
  }

  function sendCurrentMessage() {
    var text = textarea.value.trim();
    if (text) {
      messages = [];
      eventTrace = [];
      textarea.value = '';
      textarea.style.height = 'auto';
      sendMessage(text);
    }
  }

  textarea.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendCurrentMessage();
    }
  });

  sendBtn.addEventListener('click', sendCurrentMessage);

  textarea.addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 80) + 'px';
  });

  window.aiSendQuick = function(el) {
    var text = el.textContent.replace(/^[^\s]+\s/, '').trim();
    sendMessage(text);
  };
})();
