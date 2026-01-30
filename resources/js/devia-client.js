/**
 * DevIA – client invisibile fino al trigger vocale "ehi DevIa".
 * Apre la sessione (user, conversation_id) e chat testuale.
 */
(function () {
  'use strict';

  if (!window.DevIA || !window.DevIA.baseUrl) return;

  var baseUrl = window.DevIA.baseUrl.replace(/\/$/, '');
  var voiceTrigger = (window.DevIA.voiceTrigger || 'ehi devia').toLowerCase().trim();
  var rootId = 'devia-root';

  var state = {
    sessionOpen: false,
    user: null,
    conversationId: null,
    recognition: null,
  };

  function getRoot() {
    return document.getElementById(rootId);
  }

  function normalizeTrigger(t) {
    return t.toLowerCase().replace(/\s+/g, ' ').trim();
  }

  function checkTranscript(transcript) {
    var normalized = normalizeTrigger(transcript);
    return normalized.indexOf(voiceTrigger) !== -1;
  }

  function startVoiceListening() {
    var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return;

    var recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = false;
    recognition.lang = 'it-IT';

    recognition.onresult = function (event) {
      if (state.sessionOpen) return;
      for (var i = event.resultIndex; i < event.results.length; i++) {
        var transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal && checkTranscript(transcript)) {
          openSession();
          break;
        }
      }
    };

    recognition.onerror = function () {
      // Silently ignore; mic might be denied or unavailable
    };

    try {
      recognition.start();
      state.recognition = recognition;
    } catch (e) {}
  }

  function openSession() {
    if (state.sessionOpen) return;
    state.sessionOpen = true;

    var root = getRoot();
    if (!root) return;

    root.setAttribute('aria-hidden', 'false');
    root.style.pointerEvents = 'auto';
    root.style.opacity = '1';
    root.style.width = 'auto';
    root.style.height = 'auto';
    root.style.overflow = 'visible';

    fetch(baseUrl + '/devia/session', { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.ok && data.user) {
          state.user = data.user;
          state.conversationId = data.conversation_id || null;
        }
        renderChat(root);
      })
      .catch(function () {
        state.user = { id: 'guest', name: 'Guest' };
        state.conversationId = null;
        renderChat(root);
      });
  }

  function renderChat(container) {
    container.innerHTML = [
      '<div class="devia-panel" style="',
      'position:fixed;bottom:24px;right:24px;width:380px;max-width:calc(100vw - 48px);',
      'max-height:480px;background:#fff;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,0.12);',
      'display:flex;flex-direction:column;font-family:system-ui,-apple-system,sans-serif;',
      'border:1px solid #e5e7eb;">',
      '<div class="devia-header" style="padding:12px 16px;border-bottom:1px solid #e5e7eb;font-weight:600;color:#111;">',
      'DevIA – Sessione attiva',
      '</div>',
      '<div class="devia-messages" style="flex:1;overflow-y:auto;padding:12px;min-height:120px;max-height:320px;"></div>',
      '<div class="devia-input-wrap" style="padding:12px;border-top:1px solid #e5e7eb;">',
      '<textarea class="devia-input" placeholder="Scrivi qui..." rows="2" style="',
      'width:100%;padding:10px 12px;border:1px solid #e5e7eb;border-radius:8px;resize:none;font-size:14px;box-sizing:border-box;"></textarea>',
      '<button type="button" class="devia-send" style="margin-top:8px;padding:8px 16px;background:#2563eb;color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:14px;">Invia</button>',
      '</div>',
      '</div>'
    ].join('');

    var messagesEl = container.querySelector('.devia-messages');
    var inputEl = container.querySelector('.devia-input');
    var sendBtn = container.querySelector('.devia-send');

    function appendMessage(text, isUser) {
      var div = document.createElement('div');
      div.style.marginBottom = '8px';
      div.style.padding = '8px 12px';
      div.style.borderRadius = '8px';
      div.style.fontSize = '14px';
      div.style.wordBreak = 'break-word';
      if (isUser) {
        div.style.background = '#eff6ff';
        div.style.marginLeft = '24px';
      } else {
        div.style.background = '#f3f4f6';
        div.style.marginRight = '24px';
      }
      div.textContent = text;
      messagesEl.appendChild(div);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function setLoading(loading) {
      var loadingEl = container.querySelector('.devia-loading');
      if (loading && !loadingEl) {
        loadingEl = document.createElement('div');
        loadingEl.className = 'devia-loading';
        loadingEl.style.cssText = 'padding:8px 12px;font-size:13px;color:#6b7280;';
        loadingEl.textContent = 'DevIA sta rispondendo...';
        messagesEl.appendChild(loadingEl);
        messagesEl.scrollTop = messagesEl.scrollHeight;
      } else if (!loading && loadingEl) {
        loadingEl.remove();
      }
    }

    function sendMessage() {
      var message = (inputEl.value || '').trim();
      if (!message) return;

      inputEl.value = '';
      appendMessage(message, true);
      setLoading(true);

      var body = {
        message: message,
        conversation_id: state.conversationId,
      };

      var headers = { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' };
      if (window.DevIA && window.DevIA.csrfToken) {
        headers['X-CSRF-TOKEN'] = window.DevIA.csrfToken;
      }
      fetch(baseUrl + '/devia/chat', {
        method: 'POST',
        headers: headers,
        credentials: 'same-origin',
        body: JSON.stringify(body),
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          setLoading(false);
          if (data.conversation_id) state.conversationId = data.conversation_id;
          var reply = (data && data.message) ? data.message : 'Nessuna risposta.';
          appendMessage(reply, false);
        })
        .catch(function () {
          setLoading(false);
          appendMessage('Errore di connessione. Riprova.', false);
        });
    }

    sendBtn.addEventListener('click', sendMessage);
    inputEl.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startVoiceListening);
  } else {
    startVoiceListening();
  }
})();
