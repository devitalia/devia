<!doctype html>
<html lang="it">
<head>
    <meta charset="utf-8">
    <title>Kira – Assistente</title>
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: transparent;
        }
        #kira-shell {
            position: fixed;
            bottom: 16px;
            right: 16px;
            width: 340px;
            max-width: 100vw;
            max-height: 460px;
            display: flex;
            flex-direction: column;
            border-radius: 12px;
            background: #ffffff;
            box-shadow: 0 10px 30px rgba(15, 23, 42, 0.25);
            border: 1px solid #e5e7eb;
            overflow: hidden;
        }
        #kira-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 12px;
            background: #1e40af;
            color: #f9fafb;
            font-size: 14px;
            font-weight: 600;
        }
        #kira-header button {
            border: none;
            background: transparent;
            color: inherit;
            cursor: pointer;
            font-size: 18px;
            line-height: 1;
            padding: 2px 4px;
        }
        #kira-messages {
            flex: 1;
            overflow-y: auto;
            padding: 10px 10px 6px;
            background: #f3f4f6;
        }
        .kira-msg {
            margin-bottom: 6px;
            padding: 6px 9px;
            border-radius: 8px;
            font-size: 13px;
            line-height: 1.35;
            word-break: break-word;
        }
        .kira-msg-user {
            background: #dbeafe;
            margin-left: 40px;
        }
        .kira-msg-bot {
            background: #ffffff;
            margin-right: 40px;
        }
        .kira-msg-audio-btn {
            border: none;
            background: transparent;
            cursor: pointer;
            font-size: 14px;
            margin-left: 4px;
        }
        #kira-input-wrap {
            border-top: 1px solid #e5e7eb;
            padding: 8px;
            background: #ffffff;
        }
        #kira-input-row {
            display: flex;
            gap: 6px;
        }
        #kira-input {
            flex: 1;
            border-radius: 8px;
            border: 1px solid #d1d5db;
            padding: 6px 8px;
            font-size: 13px;
            resize: none;
            min-height: 34px;
            max-height: 80px;
        }
        #kira-send {
            border-radius: 8px;
            border: none;
            padding: 6px 10px;
            font-size: 13px;
            background: #2563eb;
            color: #ffffff;
            cursor: pointer;
        }
        #kira-send:disabled {
            opacity: .7;
            cursor: default;
        }
        #kira-icon {
            position: fixed;
            bottom: 20px;
            right: 20px;
            width: 56px;
            height: 56px;
            border-radius: 999px;
            background: #1e40af;
            color: #ffffff;
            display: none;
            align-items: center;
            justify-content: center;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.35);
            cursor: pointer;
            font-size: 24px;
        }
        .kira-minimized {
            display: none;
        }
        @media (max-width: 640px) {
            #kira-shell {
                bottom: 8px;
                right: 8px;
                width: calc(100vw - 16px);
                max-height: calc(100vh - 16px);
            }
        }
    </style>
</head>
<body>
<div id="kira-shell">
    <div id="kira-header">
        <span>Kira – Assistente</span>
        <button type="button" id="kira-minimize" title="Minimizza">—</button>
    </div>
    <div id="kira-messages"></div>
    <div id="kira-input-wrap">
        <form id="kira-form">
            <div id="kira-input-row">
                <textarea id="kira-input" placeholder="Scrivi a Kira..." rows="1"></textarea>
                <button type="submit" id="kira-send">Invia</button>
            </div>
        </form>
    </div>
    <audio id="kira-tts-player"></audio>
</div>
<div id="kira-icon" title="Apri Kira">💬</div>

<script>
(function () {
  'use strict';

  var API_BASE = {{ json_encode(rtrim(url('/devia'), '/')) }};
  var CSRF = {{ json_encode(csrf_token()) }};

  var STORAGE_MESSAGES = 'kira.shell.messages';
  var STORAGE_CONV = 'kira.shell.conversation_id';
  var STORAGE_LAST_AUDIO = 'kira.shell.last_audio_id';
  var STORAGE_MINIMIZED = 'kira.shell.minimized';

  var shell = document.getElementById('kira-shell');
  var icon = document.getElementById('kira-icon');
  var minimizeBtn = document.getElementById('kira-minimize');
  var messagesEl = document.getElementById('kira-messages');
  var form = document.getElementById('kira-form');
  var input = document.getElementById('kira-input');
  var sendBtn = document.getElementById('kira-send');
  var player = document.getElementById('kira-tts-player');

  var messages = [];
  var conversationId = null;
  var lastAudioId = null;

  function loadState() {
    try {
      var savedMessages = sessionStorage.getItem(STORAGE_MESSAGES);
      if (savedMessages) {
        messages = JSON.parse(savedMessages) || [];
      }
    } catch (e) {
      messages = [];
    }
    try {
      var cid = sessionStorage.getItem(STORAGE_CONV);
      if (cid) conversationId = cid;
    } catch (e2) {}
    try {
      var la = sessionStorage.getItem(STORAGE_LAST_AUDIO);
      if (la) lastAudioId = la;
    } catch (e3) {}
    try {
      var minimized = sessionStorage.getItem(STORAGE_MINIMIZED) === '1';
      if (minimized) {
        shell.classList.add('kira-minimized');
        icon.style.display = 'flex';
      }
    } catch (e4) {}
  }

  function saveState() {
    try {
      sessionStorage.setItem(STORAGE_MESSAGES, JSON.stringify(messages || []));
    } catch (e) {}
    try {
      if (conversationId) {
        sessionStorage.setItem(STORAGE_CONV, conversationId);
      }
    } catch (e2) {}
    try {
      if (lastAudioId) {
        sessionStorage.setItem(STORAGE_LAST_AUDIO, lastAudioId);
      }
    } catch (e3) {}
  }

  function renderMessages() {
    messagesEl.innerHTML = '';
    for (var i = 0; i < messages.length; i++) {
      var m = messages[i];
      var div = document.createElement('div');
      div.className = 'kira-msg ' + (m.role === 'user' ? 'kira-msg-user' : 'kira-msg-bot');
      var span = document.createElement('span');
      span.textContent = m.text || '';
      div.appendChild(span);
      if (m.role === 'assistant' && m.audioUrl) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.textContent = '🔊';
        btn.title = 'Riascolta risposta';
        btn.className = 'kira-msg-audio-btn';
        (function (url, id) {
          btn.addEventListener('click', function (e) {
            e.preventDefault();
            e.stopPropagation();
            playAudio(url, id);
          });
        })(m.audioUrl, m.audioId);
        div.appendChild(btn);
      }
      messagesEl.appendChild(div);
    }
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function playAudio(url, audioId) {
    if (!url) return;
    if (audioId && audioId === lastAudioId) {
      return;
    }
    lastAudioId = audioId || String(Date.now());
    saveState();
    try {
      player.pause();
      player.currentTime = 0;
      player.src = url;
      player.play().catch(function () {});
    } catch (e) {}
  }

  function appendMessage(role, text, audioUrl, audioId) {
    messages.push({
      role: role,
      text: text,
      audioUrl: audioUrl || null,
      audioId: audioId || null
    });
    saveState();
    renderMessages();
  }

  function sendMessage(raw) {
    var text = (typeof raw === 'string' ? raw : (input.value || '')).trim();
    if (!text) return;
    if (typeof raw !== 'string') {
      input.value = '';
    }
    appendMessage('user', text, null, null);
    setSending(true);

    var body = {
      message: text,
      conversation_id: conversationId
    };

    fetch(API_BASE + '/chat', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRF-TOKEN': CSRF
      },
      body: JSON.stringify(body)
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        setSending(false);
        if (data && data.conversation_id) {
          conversationId = data.conversation_id;
          saveState();
        }
        var reply = (data && data.message) ? data.message : 'Nessuna risposta.';
        var audioUrl = null;
        var audioId = null;
        if (data && data.audio && data.audio.base64 && data.audio.mime) {
          audioUrl = 'data:' + data.audio.mime + ';base64,' + data.audio.base64;
          audioId = String(Date.now());
        }
        appendMessage('assistant', reply, audioUrl, audioId);
        if (audioUrl) {
          playAudio(audioUrl, audioId);
        }
      })
      .catch(function () {
        setSending(false);
        appendMessage('assistant', 'Errore di connessione. Riprova.', null, null);
      });
  }

  function setSending(sending) {
    try {
      sendBtn.disabled = !!sending;
    } catch (e) {}
  }

  minimizeBtn.addEventListener('click', function (e) {
    e.preventDefault();
    shell.classList.add('kira-minimized');
    icon.style.display = 'flex';
    try { sessionStorage.setItem(STORAGE_MINIMIZED, '1'); } catch (err) {}
  });

  icon.addEventListener('click', function (e) {
    e.preventDefault();
    shell.classList.remove('kira-minimized');
    icon.style.display = 'none';
    try { sessionStorage.setItem(STORAGE_MINIMIZED, '0'); } catch (err) {}
  });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    sendMessage();
  });

  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  loadState();
  renderMessages();
})();
</script>
</body>
</html>

