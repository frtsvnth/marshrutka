(function() {
  'use strict';

  var messagesEl = document.getElementById('aiChatMessages');
  var textarea = document.querySelector('.ai-composer textarea');
  var sendBtn = document.querySelector('.ai-composer button');
  var sessionId = '';
  var isStreaming = false;

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

  function addToolEvent(toolName, summary) {
    var div = document.createElement('div');
    div.className = 'ai-tool-event';
    div.innerHTML = '<span class="tool-icon">⚙</span>' +
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

  async function sendMessage(text) {
    if (!text.trim() || isStreaming) return;

    isStreaming = true;
    hideWelcome();

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
          addToolEvent(data.tool_name || 'инструмент', data.result_summary || 'выполнено');
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
