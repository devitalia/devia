/**
 * Kira – floating in basso a destra, sempre visibile; click apre la chat.
 * Quando modifichi questo file, copialo anche in intranet/laravel/public/vendor/devia/devia-client.js
 */
(function () {
  'use strict';

  // Bump this when you change the JS to verificare facilmente se l'asset è aggiornato.
  var KIRA_CLIENT_VERSION = '2026-02-06-01';

  // Stato persistito a livello di tab: ci serve per ricordare se la sessione
  // Kira era aperta anche dopo un cambio pagina. Usiamo sessionStorage così
  // resta confinato alla singola scheda.
  var KIRA_STORAGE_KEY = 'devia.kira.state';
  var KIRA_AUDIO_PROMPT_KEY = 'devia.kira.audioExtPrompted';
  var KIRA_PENDING_AUDIO_KEY = 'devia.kira.pendingAudio';
  var KIRA_PENDING_REAPPLY_KEY = 'devia.kira.pendingReapplyMessage';

  if (!window.Kira || !window.Kira.baseUrl) return;

  var baseUrl = window.Kira.baseUrl.replace(/\/$/, '');
  var rootId = 'devia-root';
  var floatBtnId = 'devia-float-btn';
  var chatContainerId = 'devia-chat-container';

  var state = {
    sessionOpen: false,
    user: null,
    conversationId: null,
    blinkTimer: null,
    kiraResponding: false,
    micEnabled: true,
    formGuide: null, // { steps: [...], index: 0, active: true }
    pendingConfirm: null, // { text, hasCancel }
  };

  function loadPersistedState() {
    try {
      if (typeof sessionStorage === 'undefined') return {};
      var raw = sessionStorage.getItem(KIRA_STORAGE_KEY);
      if (!raw) return {};
      var parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch (e) {
      return {};
    }
  }

  function setMicEnabled(enabled) {
    state.micEnabled = !!enabled;
    // Ferma eventuali recognizer attivi se stiamo disabilitando.
    if (!state.micEnabled) {
      try {
        if (window.Kira && window.Kira._recognition) {
          window.Kira._recognition.stop();
        }
      } catch (e) {}
      try {
        if (window.Kira && window.Kira._globalRecognition) {
          window.Kira._globalRecognition.stop();
        }
      } catch (e2) {}
      return;
    }

    // Se abilitiamo il microfono:
    // - se la sessione è aperta, proviamo a (ri)avviare la dettatura locale
    // - altrimenti avviamo solo il listener globale del trigger vocale.
    try {
      if (state.sessionOpen) {
        if (window.Kira && window.Kira._recognition) {
          try { window.Kira._recognition.start(); } catch (e3) {}
        }
      } else {
        startGlobalTriggerListener();
      }
    } catch (e) {}
  }

  function persistState(patch) {
    try {
      if (typeof sessionStorage === 'undefined') return;
      var current = loadPersistedState();
      for (var k in patch) {
        if (Object.prototype.hasOwnProperty.call(patch, k)) {
          current[k] = patch[k];
        }
      }
      sessionStorage.setItem(KIRA_STORAGE_KEY, JSON.stringify(current));
    } catch (e) {
      // ignore
    }
  }

  function savePendingAudio(data) {
    try {
      if (typeof sessionStorage === 'undefined') return;
      sessionStorage.setItem(KIRA_PENDING_AUDIO_KEY, JSON.stringify(data || {}));
    } catch (e) {}
  }

  function consumePendingAudio() {
    try {
      if (typeof sessionStorage === 'undefined') return null;
      var raw = sessionStorage.getItem(KIRA_PENDING_AUDIO_KEY);
      if (!raw) return null;
      sessionStorage.removeItem(KIRA_PENDING_AUDIO_KEY);
      var parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') return null;
      return parsed;
    } catch (e) {
      return null;
    }
  }

  function savePendingReapplyMessage(message) {
    try {
      if (typeof sessionStorage === 'undefined' || !message) return;
      sessionStorage.setItem(KIRA_PENDING_REAPPLY_KEY, String(message).trim());
    } catch (e) {}
  }

  function getPendingReapplyMessage() {
    try {
      if (typeof sessionStorage === 'undefined') return null;
      var raw = sessionStorage.getItem(KIRA_PENDING_REAPPLY_KEY);
      if (!raw) return null;
      return String(raw).trim() || null;
    } catch (e) {
      return null;
    }
  }

  function clearPendingReapplyMessage() {
    try {
      if (typeof sessionStorage === 'undefined') return;
      sessionStorage.removeItem(KIRA_PENDING_REAPPLY_KEY);
    } catch (e) {}
  }

  function isChromeLikeDesktop() {
    if (typeof navigator === 'undefined') return false;
    var ua = navigator.userAgent || '';
    // Escludiamo mobile; cerchiamo Chrome/Chromium/Edge.
    var isMobile = /Android|iPhone|iPad|Mobile/i.test(ua);
    if (isMobile) return false;
    var isChrome = /Chrome\/\d+/.test(ua) || /Chromium\/\d+/.test(ua) || /Edg\/\d+/.test(ua);
    return isChrome;
  }

  function markAudioPromptShown() {
    try {
      if (typeof sessionStorage === 'undefined') return;
      sessionStorage.setItem(KIRA_AUDIO_PROMPT_KEY, '1');
    } catch (e) {}
  }

  function hasShownAudioPrompt() {
    try {
      if (typeof sessionStorage === 'undefined') return false;
      return sessionStorage.getItem(KIRA_AUDIO_PROMPT_KEY) === '1';
    } catch (e) {
      return false;
    }
  }

  function getRoot() {
    return document.getElementById(rootId);
  }

  function getFloatBtn() {
    return document.getElementById(floatBtnId);
  }

  function getChatContainer() {
    return document.getElementById(chatContainerId);
  }

  function showFloat() {
    var btn = getFloatBtn();
    if (!btn || state.sessionOpen) return;
    btn.style.opacity = '1';
    btn.style.pointerEvents = 'auto';
  }

  function hideFloat() {
    var btn = getFloatBtn();
    if (!btn) return;
    btn.style.opacity = '0';
    btn.style.pointerEvents = 'none';
  }

  function stopBlink() {
    if (state.blinkTimer) {
      clearInterval(state.blinkTimer);
      state.blinkTimer = null;
    }
    hideFloat();
  }

  function openSession() {
    if (state.sessionOpen) return;
    state.sessionOpen = true;
    persistState({ sessionOpen: true, conversationId: state.conversationId || null });
    stopBlink();

    // Ferma il listener globale del comando vocale (sessione aperta = ascolta solo la chat)
    if (window.Kira && window.Kira._globalRecognition) {
      try { window.Kira._globalRecognition.stop(); } catch (e) {}
    }

    var root = getRoot();
    var container = getChatContainer();
    if (!root || !container) return;

    root.style.pointerEvents = 'auto';

    fetch(baseUrl + '/devia/session', { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.ok && data.user) {
          state.user = data.user;
          state.conversationId = data.conversation_id || null;
          persistState({ conversationId: state.conversationId || null });
        }
        renderChat(container);
      })
      .catch(function () {
        state.user = { id: 'guest', name: 'Guest' };
        state.conversationId = null;
        persistState({ conversationId: null });
        renderChat(container);
      });
  }

  function closeSession() {
    state.sessionOpen = false;
    persistState({ sessionOpen: false });
    if (window.Kira && window.Kira._recognition) {
      try { window.Kira._recognition.stop(); } catch (e) {}
    }
    var container = getChatContainer();
    if (container) container.innerHTML = '';
    showFloat();
  }

  /**
   * Slug per id azione: "TIMBRA ENTRATA" → "timbra_entrata", "Apri Timbrature" → "apri_timbrature".
   */
  function slugForAction(text) {
    if (!text || typeof text !== 'string') return '';
    return text.trim().toLowerCase()
      .replace(/\s+/g, '_')
      .replace(/[^a-z0-9_]/g, '');
  }

  /**
   * Testo visibile "principale" di un elemento (button, link, input): textContent senza spazi multipli.
   * Viene usato come label completa.
   */
  function getActionLabel(el) {
    // Ordine di priorità:
    // 1) data-kira-label (se vuoi forzare una label "pulita" da Blade)
    // 2) data-title (spesso usato come descrizione breve dell'azione)
    // 3) aria-label
    // 4) textContent / value (fallback, ma può contenere testo aggregato)
    var text = el.getAttribute('data-kira-label')
      || el.getAttribute('data-title')
      || el.getAttribute('aria-label')
      || el.textContent
      || el.value
      || '';

    return String(text).trim().replace(/\s+/g, ' ');
  }

  /**
   * Ritorna una lista di label "atomiche" per l'azione:
   * - se presenti, usa data-kira-label e data-title
   * - altrimenti prende le textContent dei figli diretti (es. span interni) come frasi separate
   * - come fallback aggiunge comunque la label completa.
   *
   * Scopo: permettere al backend di scegliere una frase breve e con senso compiuto
   * da pronunciare (es. "Richiedi Trasferta") invece della concatenazione di tutti i testi.
   */
  function getActionLabels(el) {
    var labels = [];

    var forced = el.getAttribute('data-kira-label');
    if (forced) {
      labels.push(String(forced).trim().replace(/\s+/g, ' '));
    }

    var title = el.getAttribute('data-title');
    if (title) {
      labels.push(String(title).trim().replace(/\s+/g, ' '));
    }

    // Testi dei figli diretti (tipico caso: <span>Richiedi</span><span>Richiedi Trasferta</span>)
    for (var i = 0; i < el.children.length; i++) {
      var child = el.children[i];
      var t = (child.textContent || '').trim().replace(/\s+/g, ' ');
      if (t && t.length > 1) {
        labels.push(t);
      }
    }

    // Fallback: se non è stato trovato nulla, usa almeno la label completa
    if (labels.length === 0) {
      var full = getActionLabel(el);
      if (full) {
        labels.push(full);
      }
    }

    // Deduplica mantenendo l'ordine
    var seen = {};
    var unique = [];
    for (var j = 0; j < labels.length; j++) {
      var l = labels[j];
      if (!seen[l]) {
        seen[l] = true;
        unique.push(l);
      }
    }

    return unique;
  }

  /**
   * Azione considerata "attiva" se l'elemento è cliccabile (non disabled, non visivamente disabilitato).
   */
  function isElementActive(el) {
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') return false;
    if (el.classList && (el.classList.contains('opacity-40') || el.classList.contains('cursor-not-allowed') || el.classList.contains('pointer-events-none'))) return false;
    return true;
  }

  /**
   * Scansiona la pagina: button, input[type=submit], a[href] (escluso il widget).
   * Cerca nel main se presente, altrimenti in body.
   *
   * NOTA: per Kira è "funzione" QUALSIASI cosa cliccabile (attiva o disattivata):
   * - <button>
   * - <input type="submit">
   * - <a href="...">
   * - elementi con role="button"
   * - elementi con handler onclick (span/div usati come bottoni)
   *
   * Per ogni elemento: label dal testo visibile, active da disabled/classi,
   * id da slug(label). Assegna data-kira-action-id per il trigger.
   */
  function scanPageActions() {
    var root = document.getElementById(rootId);
    var scope = document.querySelector('main') || document.querySelector('[role="main"]') || document.body;
    // Includi tutto ciò che può essere cliccabile: bottoni, link, elementi con role="button" o onclick.
    var selector = 'button, input[type=submit], a[href], [role="button"], [onclick]';
    var nodes = scope.querySelectorAll(selector);
    var list = [];
    var usedIds = {};
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (root && root.contains(el)) continue;
      var label = getActionLabel(el);
      if (!label || label.length < 2) continue;
      var baseId = slugForAction(label);
      if (!baseId) continue;
      var id = baseId;
      var n = 1;
      while (usedIds[id]) { id = baseId + '_' + n; n++; }
      usedIds[id] = true;
      el.setAttribute('data-kira-action-id', id);
      var active = isElementActive(el);
      var labels = getActionLabels(el);
      list.push({
        id: id,
        label: label,
        labels: labels,
        selector: '[data-kira-action-id="' + id + '"]',
        active: active
      });
    }
    return list;
  }

  /**
   * Tenta di riconoscere un "form di lavoro" nella pagina (come il Foglio di intervento)
   * analizzando struttura, label e campi. Non usa URL.
   *
   * Ritorna un array di step:
   * [{ label: 'Cliente', question: 'Dammi il cliente.', el: HTMLElement, type: 'text'|'date'|'textarea'|'select' }, ...]
   */
  function detectGuidedFormSteps() {
    // 1) Trova un form "principale" con molti campi e un header descrittivo
    var candidateForms = Array.prototype.slice.call(document.querySelectorAll('form'));
    if (!candidateForms.length) return [];

    var mainForm = null;
    for (var i = 0; i < candidateForms.length; i++) {
      var f = candidateForms[i];
      // Heuristics: classe "worksheet-form" oppure molti input/select/textarea
      var fields = f.querySelectorAll('input, textarea, select');
      if ((f.classList && f.classList.contains('worksheet-form')) || fields.length >= 5) {
        mainForm = f;
        break;
      }
    }
    if (!mainForm) return [];

    // 2) Associa label -> controllo
    var labels = Array.prototype.slice.call(mainForm.querySelectorAll('label'));
    var steps = [];

    function addStepFrom(labelEl, controlEl) {
      if (!controlEl) return;
      var tag = controlEl.tagName.toLowerCase();
      var type = (controlEl.getAttribute('type') || '').toLowerCase();
      if (
        (tag === 'input' && (type === 'text' || type === 'date' || type === 'number')) ||
        tag === 'textarea' ||
        tag === 'select'
      ) {
        var rawLabel = (labelEl.textContent || '').trim().replace(/\s+/g, ' ');
        if (!rawLabel) return;
        var lower = rawLabel.toLowerCase();
        var question;
        if (lower.indexOf('cliente') !== -1) {
          question = 'Dammi il cliente.';
        } else if (lower.indexOf('data') !== -1) {
          question = 'Dammi la data.';
        } else if (lower.indexOf('descrizione') !== -1) {
          question = 'Dammi la descrizione del lavoro.';
        } else {
          question = 'Dammi il valore per "' + rawLabel + '".';
        }
        steps.push({
          label: rawLabel,
          question: question,
          el: controlEl,
          type: tag === 'textarea' ? 'textarea' : (tag === 'select' ? 'select' : (type || 'text'))
        });
      }
    }

    for (var j = 0; j < labels.length; j++) {
      var lab = labels[j];
      var text = (lab.textContent || '').trim();
      if (!text) continue;

      var target = null;
      var forId = lab.getAttribute('for');
      if (forId) {
        target = mainForm.querySelector('#' + CSS.escape(forId));
      }
      if (!target) {
        // Prova a trovare un input/select/textarea discendente
        target = lab.querySelector('input, textarea, select');
      }
      addStepFrom(lab, target);
    }

    // Ordina per posizione nel DOM (già in ordine naturale, quindi va bene).
    // Filtra i duplicati per stesso elemento.
    var seenEls = new Set();
    var filtered = [];
    for (var k = 0; k < steps.length; k++) {
      var s = steps[k];
      if (!s.el || seenEls.has(s.el)) continue;
      seenEls.add(s.el);
      filtered.push(s);
    }

    // Per ora teniamo solo i campi più utili se presenti.
    var priority = ['cliente', 'data', 'ore lavoro', 'ore viaggio', 'descrizione'];
    filtered.sort(function (a, b) {
      var al = a.label.toLowerCase();
      var bl = b.label.toLowerCase();
      var ai = priority.findIndex(function (p) { return al.indexOf(p) !== -1; });
      var bi = priority.findIndex(function (p) { return bl.indexOf(p) !== -1; });
      if (ai === -1) ai = 999;
      if (bi === -1) bi = 999;
      if (ai !== bi) return ai - bi;
      return 0;
    });

    // Se non abbiamo almeno 2-3 campi significativi, non attiviamo la guida.
    if (filtered.length < 2) return [];

    return filtered;
  }

  /**
   * Restituisce i campi form visibili per il backend (label, required, type).
   * Usato per la compilazione intelligente: l'IA estrae i valori dal messaggio in base alle label.
   * Cerca in tutti i form con almeno un campo; non solo worksheet-form.
   */
  function getFormFieldsForBackend() {
    var forms = Array.prototype.slice.call(document.querySelectorAll('form'));
    var out = [];
    var seenLabels = {};
    for (var i = 0; i < forms.length; i++) {
      var f = forms[i];
      var labels = Array.prototype.slice.call(f.querySelectorAll('label'));
      for (var j = 0; j < labels.length; j++) {
        var lab = labels[j];
        var text = (lab.textContent || '').trim().replace(/\s+/g, ' ');
        if (!text || seenLabels[text]) continue;
        var target = null;
        var forId = lab.getAttribute('for');
        if (forId) {
          target = f.querySelector('#' + CSS.escape(forId));
        }
        if (!target) {
          target = lab.querySelector('input, textarea, select');
        }
        if (!target) continue;
        var tag = target.tagName.toLowerCase();
        var type = (target.getAttribute('type') || '').toLowerCase();
        if (
          (tag === 'input' && (type === 'text' || type === 'date' || type === 'number' || type === 'email')) ||
          tag === 'textarea' ||
          tag === 'select'
        ) {
          seenLabels[text] = true;
          out.push({
            label: text,
            required: !!(target.required || target.getAttribute('required')),
            type: tag === 'textarea' ? 'textarea' : (tag === 'select' ? 'select' : (type || 'text'))
          });
        }
      }
    }
    return out;
  }

  /**
   * Compila i campi del form in pagina in base a form_fill (mappa label -> value).
   * Cerca i campi per label (testo del <label> associato all'input).
   */
  function applyFormFill(formFill) {
    if (!formFill || typeof formFill !== 'object') return;
    if (typeof console !== 'undefined') {
      console.log('[Kira] applyFormFill (label -> value)', formFill);
    }

    function normalizeLabel(str) {
      if (!str) return '';
      // Rimuove asterischi, due punti e spazi extra; case-insensitive.
      return String(str)
        .replace(/[\s]+/g, ' ')
        .replace(/[:*]+/g, '')
        .trim()
        .toLowerCase();
    }

    var forms = document.querySelectorAll('form');
    for (var key in formFill) {
      if (!Object.prototype.hasOwnProperty.call(formFill, key)) continue;
      var value = formFill[key];
      if (value === undefined || value === null) value = '';
      value = String(value).trim();
      var labelText = String(key).trim();
      var normKey = normalizeLabel(labelText);

      for (var i = 0; i < forms.length; i++) {
        var labels = forms[i].querySelectorAll('label');
        for (var j = 0; j < labels.length; j++) {
          var lab = labels[j];
          var text = (lab.textContent || '').trim().replace(/\s+/g, ' ');
          var normLabel = normalizeLabel(text);
          if (!normLabel || normLabel !== normKey) continue;

          var target = null;
          var forId = lab.getAttribute('for');
          if (forId) {
            try {
              target = forms[i].querySelector('#' + CSS.escape(forId));
            } catch (e) {
              // se CSS.escape non è disponibile, prova selettore semplice
              target = forms[i].querySelector('#' + forId);
            }
          }
          if (!target) {
            target = lab.querySelector('input, textarea, select');
          }
          if (target) {
            if (typeof console !== 'undefined') {
              console.log('[Kira] set campo form', { label: text, normalizzato: normLabel, value: value });
            }
            target.value = value;
            try {
              target.dispatchEvent(new Event('input', { bubbles: true }));
              target.dispatchEvent(new Event('change', { bubbles: true }));
            } catch (e2) {}
            break;
          }
        }
      }
    }
  }

  // Normalizza una data dettata in italiano in formato YYYY-MM-DD quando possibile.
  function normalizeDateInput(message) {
    if (!message) return message;
    var txt = String(message).trim().toLowerCase();
    if (!txt) return message;

    var today = new Date();
    function toYmd(d) {
      var y = d.getFullYear();
      var m = String(d.getMonth() + 1).padStart(2, '0');
      var day = String(d.getDate()).padStart(2, '0');
      return y + '-' + m + '-' + day;
    }

    if (txt === 'oggi') {
      return toYmd(today);
    }
    if (txt === 'domani') {
      var d1 = new Date(today.getTime());
      d1.setDate(d1.getDate() + 1);
      return toYmd(d1);
    }
    if (txt === 'ieri') {
      var d2 = new Date(today.getTime());
      d2.setDate(d2.getDate() - 1);
      return toYmd(d2);
    }

    // dd/mm/yyyy, dd-mm-yyyy, dd.mm.yyyy
    var m = txt.match(/(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{2,4})/);
    if (m) {
      var d = parseInt(m[1], 10);
      var mo = parseInt(m[2], 10);
      var y = parseInt(m[3], 10);
      if (y < 100) y += 2000;
      if (y >= 1900 && y <= 2100 && mo >= 1 && mo <= 12 && d >= 1 && d <= 31) {
        var yy = String(y);
        var mm = String(mo).padStart(2, '0');
        var dd = String(d).padStart(2, '0');
        return yy + '-' + mm + '-' + dd;
      }
    }

    // Già nel formato giusto?
    if (/^\d{4}-\d{2}-\d{2}$/.test(txt)) {
      return txt;
    }

    return message;
  }

  // Converte parole tipo "quattro" in "4" (stringa).
  function normalizeNumberInput(message) {
    if (!message) return message;
    var txt = String(message).trim().toLowerCase();
    if (!txt) return message;

    var map = {
      'zero': 0,
      'uno': 1,
      'una': 1,
      'un': 1,
      'due': 2,
      'tre': 3,
      'quattro': 4,
      'cinque': 5,
      'sei': 6,
      'sette': 7,
      'otto': 8,
      'nove': 9,
      'dieci': 10,
      'undici': 11,
      'dodici': 12
    };

    if (Object.prototype.hasOwnProperty.call(map, txt)) {
      return String(map[txt]);
    }

    // Se è già un numero valido, lascialo così.
    if (/^\d+([.,]\d+)?$/.test(txt)) {
      return txt.replace(',', '.');
    }

    return message;
  }

  // Rimuove il wake-word iniziale (es. "kira timbra entrata" -> "timbra entrata")
  function stripWakeWordPrefix(message) {
    if (!message) return message;
    var raw = String(message).trim();
    if (!raw) return raw;
    var lower = raw.toLowerCase();
    var patterns = ['kira ', 'hey kira ', 'ehi kira '];
    for (var i = 0; i < patterns.length; i++) {
      var p = patterns[i];
      if (lower.indexOf(p) === 0) {
        return raw.slice(p.length).trim();
      }
    }
    return raw;
  }

  /**
   * Analizza la pagina e restituisce le azioni disponibili (button, input submit, link).
   * Ogni pagina viene sempre scandita: niente getAvailableActions/availableActions dalla pagina.
   * La lista va in pasto all'IA insieme al messaggio; l'IA decide se il comando è uno di quelli (attivo/non attivo/inesistente).
   */
  function getAvailableActions() {
    var list = scanPageActions();
    if (typeof console !== 'undefined') console.log('[Kira] azioni pagina (scansione DOM)', list.length, list);
    return list;
  }

  /**
   * Trigger per indice: usa il progressivo nell'array delle azioni (0-based).
   * Evita id lunghi/troncati; il backend restituisce action_index = posizione nell'array inviato.
   */
  function triggerPageActionByIndex(index) {
    if (typeof index !== 'number' || index < 0) return { message: 'Funzione non trovata.' };
    var actions = getAvailableActions();
    var action = actions[index];
    if (!action) return { message: 'Funzione non trovata.' };
    if (!action.active) return { message: 'Funzione non attiva.' };
    var selector = action.selector;
    if (!selector) return { message: 'Funzione non trovata.' };
    try {
      var el = document.querySelector(selector);
      if (!el) return { message: 'Funzione non trovata.' };
      el.click();
      var label = (action.label || action.id || '').replace(/_/g, ' ');
      return { message: label + ' in corso…' };
    } catch (e) {
      return { message: 'Funzione non trovata.' };
    }
  }

  /**
   * Trigger per action_id: cerca l'azione per id (fallback se non c'è action_index).
   */
  function triggerPageAction(actionId) {
    if (!actionId) return { message: 'Funzione non trovata.' };
    var actions = getAvailableActions();
    var action = null;
    for (var i = 0; i < actions.length; i++) {
      if (actions[i].id === actionId) {
        action = actions[i];
        break;
      }
    }
    if (!action && actionId) {
      var idNorm = String(actionId).trim();
      for (var j = 0; j < actions.length; j++) {
        var aid = String(actions[j].id || '').trim();
        if (!aid) continue;
        if (idNorm.indexOf(aid) !== -1 || aid.indexOf(idNorm) !== -1) {
          action = actions[j];
          break;
        }
      }
    }
    if (!action) return { message: 'Funzione non trovata.' };
    if (!action.active) return { message: 'Funzione non attiva.' };
    var selector = action.selector;
    if (!selector) return { message: 'Funzione non trovata.' };
    try {
      var el = document.querySelector(selector);
      if (!el) return { message: 'Funzione non trovata.' };
      el.click();
      var label = (action.label || actionId).replace(/_/g, ' ');
      return { message: label + ' in corso…' };
    } catch (e) {
      return { message: 'Funzione non trovata.' };
    }
  }

  function renderChat(container) {
    container.innerHTML = [
      '<div class="devia-panel" style="',
      'position:fixed;bottom:24px;right:24px;width:380px;max-width:calc(100vw - 48px);',
      'max-height:480px;background:#fff;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,0.12);',
      'display:flex;flex-direction:column;font-family:system-ui,-apple-system,sans-serif;',
      'border:1px solid #e5e7eb;">',
      '<div class="devia-header" style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid #e5e7eb;font-weight:600;color:#111;">',
      '<span>Kira – Sessione attiva <span style="font-size:11px;font-weight:400;opacity:.6;">v' + KIRA_CLIENT_VERSION + '</span></span>',
      '<button type="button" class="devia-close" title="Chiudi" style="background:none;border:none;cursor:pointer;padding:4px;line-height:1;font-size:20px;color:#6b7280;border-radius:4px;" aria-label="Chiudi">×</button>',
      '</div>',
      '<div class="devia-messages" style="flex:1;overflow-y:auto;padding:12px;min-height:120px;max-height:320px;"></div>',
      '<div class="devia-input-wrap" style="padding:12px;border-top:1px solid #e5e7eb;">',
      '<form class="devia-form" style="margin:0;">',
      '<textarea class="devia-input" name="message" placeholder="Scrivi qui..." rows="2" style="',
      'width:100%;padding:10px 12px;border:1px solid #e5e7eb;border-radius:8px;resize:none;font-size:14px;box-sizing:border-box;"></textarea>',
      '<div style="display:flex;align-items:center;justify-content:space-between;margin-top:8px;gap:8px;">',
      '<button type="button" class="devia-mic-toggle" title="Disattiva microfono" style="background:#f3f4f6;border:none;cursor:pointer;padding:6px 10px;border-radius:999px;font-size:13px;color:#374151;display:inline-flex;align-items:center;gap:6px;">',
      '<span class="devia-mic-icon">🎤</span>',
      '<span class="devia-mic-label">Mic attivo</span>',
      '</button>',
      '<button type="submit" class="devia-send" style="padding:8px 16px;background:#2563eb;color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:14px;position:relative;z-index:10;pointer-events:auto;">Invia</button>',
      '</div>',
      '</form>',
      '</div>',
      '</div>'
    ].join('');

    var messagesEl = container.querySelector('.devia-messages');
    var inputEl = container.querySelector('.devia-input');
    var sendBtn = container.querySelector('.devia-send');
    var closeBtn = container.querySelector('.devia-close');
    var micBtn = container.querySelector('.devia-mic-toggle');
    if (closeBtn) {
      closeBtn.addEventListener('click', function () { closeSession(); });
      closeBtn.addEventListener('touchend', function (e) { e.preventDefault(); closeSession(); }, { passive: false });
    }

    // Auto-chiusura chat dopo un breve periodo senza comandi,
    // per evitare che resti in ascolto e possa eseguire azioni involontarie.
    var autoCloseTimer = null;
    var AUTO_CLOSE_DELAY_MS = 2000;

    function scheduleAutoClose() {
      try {
        if (autoCloseTimer) {
          clearTimeout(autoCloseTimer);
        }
        autoCloseTimer = setTimeout(function () {
          try { closeSession(); } catch (e) {}
        }, AUTO_CLOSE_DELAY_MS);
      } catch (e) {}
    }

    function cancelAutoClose() {
      try {
        if (autoCloseTimer) {
          clearTimeout(autoCloseTimer);
          autoCloseTimer = null;
        }
      } catch (e) {}
    }

    function refreshMicButton() {
      if (!micBtn) return;
      if (state.micEnabled) {
        var iconOn = micBtn.querySelector('.devia-mic-icon');
        var labelOn = micBtn.querySelector('.devia-mic-label');
        if (iconOn) iconOn.textContent = '🎤';
        if (labelOn) labelOn.textContent = 'Mic attivo';
        micBtn.title = 'Disattiva microfono';
      } else {
        var iconOff = micBtn.querySelector('.devia-mic-icon');
        var labelOff = micBtn.querySelector('.devia-mic-label');
        if (iconOff) iconOff.textContent = '🔇';
        if (labelOff) labelOff.textContent = 'Mic disattivato';
        micBtn.title = 'Attiva microfono';
      }
    }
    if (micBtn) {
      micBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        setMicEnabled(!state.micEnabled);
        refreshMicButton();
      });
      micBtn.addEventListener('touchend', function (e) {
        e.preventDefault();
        e.stopPropagation();
        setMicEnabled(!state.micEnabled);
        refreshMicButton();
      }, { passive: false });
      refreshMicButton();
    }

    function appendMessage(text, isUser, audioUrl) {
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

      // Testo risposta
      var spanText = document.createElement('span');
      spanText.textContent = text;
      div.appendChild(spanText);

      // Bottone altoparlante per le risposte del bot (sempre visibile)
      if (!isUser) {
        var btnAudio = document.createElement('button');
        btnAudio.type = 'button';
        btnAudio.textContent = '🔊';
        btnAudio.title = 'Ascolta risposta';
        btnAudio.style.cssText = 'margin-left:8px;vertical-align:middle;border:none;background:transparent;cursor:pointer;font-size:16px;line-height:1;';

        btnAudio.addEventListener('click', function (e) {
          e.preventDefault();
          e.stopPropagation();
          try {
            // Se il backend ha restituito un URL audio (es. Piper), usalo
            if (audioUrl) {
              window.Kira = window.Kira || {};
              if (!window.Kira._audioPlayer) {
                window.Kira._audioPlayer = new Audio();
              }
              var player = window.Kira._audioPlayer;
              player.pause();
              player.currentTime = 0;
              player.src = audioUrl;
              player.play().catch(function () {});
              return;
            }
            // Altrimenti usa la sintesi vocale del browser
            if (typeof window.speechSynthesis !== 'undefined' && text) {
              window.speechSynthesis.cancel();
              var u = new SpeechSynthesisUtterance(text);
              u.lang = 'it-IT';
              u.rate = 1;
              var voices = window.speechSynthesis.getVoices();
              var itVoice = voices.filter(function (v) { return (v.lang || '').toLowerCase().indexOf('it') === 0; })[0];
              if (itVoice) u.voice = itVoice;
              window.speechSynthesis.speak(u);
            }
          } catch (err) {}
        });

        div.appendChild(btnAudio);
      }

      messagesEl.appendChild(div);
      messagesEl.scrollTop = messagesEl.scrollHeight;

      // Ogni nuovo messaggio (utente o Kira) resetta il timer;
      // la chiusura verrà programmata esplicitamente dopo le risposte.
      cancelAutoClose();
    }

    function stopSessionMic() {
      state.kiraResponding = true;
      if (window.Kira && window.Kira._recognition) {
        try { window.Kira._recognition.stop(); } catch (e) {}
      }
    }

    function restartSessionMic() {
      state.kiraResponding = false;
      if (window.Kira && window.Kira._recognition && state.sessionOpen) {
        setTimeout(function () { try { window.Kira._recognition.start(); } catch (e) {} }, 300);
      }
    }

    /**
     * Richiede TTS al backend e riproduce l'audio. Opzionale: onAudioReady(audioUrl) viene chiamato
     * quando l'audio è pronto (utile per aggiornare il bottone altoparlante di un messaggio
     * così l'utente può cliccare per ascoltare se l'autoplay è bloccato).
     */
    function speakWithTts(text, onAudioReady) {
      if (!text) return;
      try {
        var headers = { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' };
        if (window.Kira && window.Kira.csrfToken) {
          headers['X-CSRF-TOKEN'] = window.Kira.csrfToken;
        }
        fetch(baseUrl + '/devia/tts', {
          method: 'POST',
          headers: headers,
          credentials: 'same-origin',
          body: JSON.stringify({ text: text })
        })
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (data) {
            if (!data || !data.ok || !data.audio || !data.audio.base64 || !data.audio.mime) return;
            var audioUrl = 'data:' + data.audio.mime + ';base64,' + data.audio.base64;
            if (typeof onAudioReady === 'function') {
              try { onAudioReady(audioUrl); } catch (e) {}
            }
            try {
              window.Kira = window.Kira || {};
              // Inoltra sempre l'audio anche all'estensione (se presente).
              try {
                window.postMessage({
                  type: 'KIRA_REPLY',
                  text: text,
                  audioUrl: audioUrl,
                  source: 'devia-kira'
                }, '*');
              } catch (ePost) {}

              var extActive = !!window.Kira._extDetected;
              // Se l'estensione NON è attiva, riproduci in-page e salva pending;
              // altrimenti lascia la riproduzione all'offscreen dell'estensione.
              if (!extActive) {
                if (!window.Kira._audioPlayer) window.Kira._audioPlayer = new Audio();
                var player = window.Kira._audioPlayer;
                player.pause();
                player.currentTime = 0;
                player.volume = 1;
                player.muted = false;
                player.src = audioUrl;
                savePendingAudio({ text: text, audioUrl: audioUrl });
                player.play().catch(function () {});
              }
            } catch (e) {}
          })
          .catch(function () {});
      } catch (e) {}
    }

    // Timeout di reload dopo trigger: lo salviamo così possiamo posticiparlo se appare uno SweetAlert.
    function scheduleReloadAfterTrigger(delayMs) {
      if (window.Kira._reloadTimeout) {
        clearTimeout(window.Kira._reloadTimeout);
        window.Kira._reloadTimeout = null;
      }
      window.Kira._reloadTimeout = setTimeout(function () {
        window.Kira._reloadTimeout = null;
        window.location.reload();
      }, delayMs);
    }

    // Osserva eventuali SweetAlert2 aperti in pagina: legge il contenuto e, se ci sono più pulsanti,
    // chiede conferma all'utente tramite chat. Se c'è un reload in programma, lo posticipa per dare
    // tempo al TTS della conferma di essere richiesto e riprodotto.
    (function watchSweetAlert() {
      var lastSpoken = null;
      function check() {
        try {
          var container = document.querySelector('.swal2-container.swal2-center, .swal2-container');
          if (!container || container.style.display === 'none') {
            return;
          }
          var titleEl = container.querySelector('.swal2-title');
          var textEl = container.querySelector('.swal2-html-container, .swal2-content');
          var title = titleEl ? (titleEl.textContent || '').trim() : '';
          var body = textEl ? (textEl.textContent || '').trim() : '';
          var full = (title + ' ' + body).trim();
          if (!full) return;

          if (full !== lastSpoken) {
            lastSpoken = full;

            // Conta i pulsanti: se c'è un solo bottone è solo avviso; se più di uno è richiesta di conferma.
            var buttons = container.querySelectorAll('.swal2-confirm, .swal2-deny, .swal2-cancel');
            var btnCount = buttons ? buttons.length : 0;

            if (btnCount > 1) {
              // Richiesta di conferma: posticipa il reload (se in programma) per dare tempo al TTS di essere pronunciato.
              if (window.Kira._reloadTimeout) {
                scheduleReloadAfterTrigger(6000);
              }
              state.pendingConfirm = {
                text: full,
                hasCancel: !!container.querySelector('.swal2-cancel'),
              };
              var messageForChat = '«' + full + '»\nVuoi che proceda? Rispondi sì o no.';
              appendMessage(messageForChat, false, null);
              // Quando il TTS è pronto, aggiorna l'altoparlante dell'ultimo messaggio così l'utente può cliccare per ascoltare
              // (l'autoplay può essere bloccato dal browser in questo contesto).
              speakWithTts(full, function (audioUrl) {
                var lastMsg = messagesEl && messagesEl.lastElementChild;
                if (!lastMsg) return;
                var btn = lastMsg.querySelector('button[title="Ascolta risposta"]');
                if (!btn) return;
                btn._kiraAudioUrl = audioUrl;
                btn.onclick = function (e) {
                  e.preventDefault();
                  e.stopPropagation();
                  if (btn._kiraAudioUrl) {
                    try {
                      window.Kira = window.Kira || {};
                      if (!window.Kira._audioPlayer) window.Kira._audioPlayer = new Audio();
                      var p = window.Kira._audioPlayer;
                      p.pause();
                      p.currentTime = 0;
                      p.src = btn._kiraAudioUrl;
                      p.play().catch(function () {});
                    } catch (err) {}
                    return;
                  }
                  var span = lastMsg.querySelector('span');
                  var textToSpeak = span ? span.textContent : '';
                  if (typeof window.speechSynthesis !== 'undefined' && textToSpeak) {
                    window.speechSynthesis.cancel();
                    var u = new SpeechSynthesisUtterance(textToSpeak);
                    u.lang = 'it-IT';
                    window.speechSynthesis.speak(u);
                  }
                };
              });
            } else {
              // Solo messaggio informativo: leggi e mostra il testo, nessuna domanda.
              state.pendingConfirm = null;
              appendMessage(full, false, null);
              speakWithTts(full);
            }
          }
        } catch (e) {}
      }
      setInterval(check, 800);
    })();

    function setLoading(loading) {
      if (loading) {
        stopSessionMic();
      }
      var loadingEl = container.querySelector('.devia-loading');
      if (loading && !loadingEl) {
        loadingEl = document.createElement('div');
        loadingEl.className = 'devia-loading';
        loadingEl.style.cssText = 'padding:8px 12px;font-size:13px;color:#6b7280;';
        loadingEl.textContent = 'Kira sta rispondendo...';
        messagesEl.appendChild(loadingEl);
        messagesEl.scrollTop = messagesEl.scrollHeight;
      } else if (!loading && loadingEl) {
        loadingEl.remove();
      }
    }

    function startFormGuide(steps) {
      if (!steps || !steps.length) return;
      state.formGuide = {
        steps: steps,
        index: 0,
        active: true,
      };
      var first = steps[0];
      appendMessage(first.question, false, null);
      speakWithTts(first.question);
    }

    function handleFormGuideAnswer(message) {
      if (!state.formGuide || !state.formGuide.active) return;
      var fg = state.formGuide;
      var steps = fg.steps || [];
      if (!steps.length || fg.index >= steps.length) {
        fg.active = false;
        return;
      }
      var step = steps[fg.index];
      var el = step.el;
      if (el) {
        var tag = el.tagName.toLowerCase();
        var type = (el.getAttribute('type') || '').toLowerCase();
        if (tag === 'input' && type === 'date') {
          // Normalizza "oggi", "domani", "04/02/2026", ecc. in YYYY-MM-DD.
          el.value = normalizeDateInput(message);
        } else if (tag === 'select') {
          // Prova a selezionare l'opzione che contiene il testo o il numero normalizzato.
          var normalized = normalizeNumberInput(message);
          var lower = String(normalized).toLowerCase();
          var opts = el.options || [];
          var matchedIndex = -1;
          for (var i = 0; i < opts.length; i++) {
            var optText = (opts[i].text || '').toLowerCase();
            if (optText.indexOf(lower) !== -1) {
              matchedIndex = i;
              break;
            }
          }
          if (matchedIndex >= 0) {
            el.selectedIndex = matchedIndex;
          }
        } else {
          // Per numeri (es. ore) prova a normalizzare; altrimenti inserisci il testo.
          if (tag === 'input' && type === 'number') {
            el.value = normalizeNumberInput(message);
          } else {
            el.value = message;
          }
        }
        try {
          el.dispatchEvent(new Event('input', { bubbles: true }));
          el.dispatchEvent(new Event('change', { bubbles: true }));
        } catch (e) {}
      }

      fg.index += 1;
      if (fg.index < steps.length) {
        var next = steps[fg.index];
        appendMessage(next.question, false, null);
        speakWithTts(next.question);
      } else {
        fg.active = false;
        var finalMsg = 'Ho compilato i campi principali del form. Puoi completare eventuali materiali, documenti o firme dalla pagina. Quando sei pronto puoi usare il bottone Avanti o dirmi di procedere.';
        appendMessage(finalMsg, false, null);
        speakWithTts(finalMsg);
      }
    }

    function sendMessage(optionalMessage) {
      var message = (typeof optionalMessage === 'string' ? optionalMessage : (inputEl.value || '')).trim();
      if (!message) return;

      cancelAutoClose();

      if (typeof optionalMessage !== 'string') inputEl.value = '';
      // Mostriamo sempre ciò che l'utente ha detto/scritto
      appendMessage(message, true, null);

      // Per la logica e il backend rimuoviamo l'eventuale wake-word iniziale
      var cleaned = stripWakeWordPrefix(message);
      var msgLower = cleaned.toLowerCase();

      // Se c'è una conferma pendente (SweetAlert), interpreta questo messaggio come sì/no
      // e NON chiamare il backend.
      if (state.pendingConfirm && state.pendingConfirm.text) {
        var isYes = (msgLower === 'si' || msgLower === 'sì' || msgLower === 'ok' || msgLower === 'ok.' || msgLower === 'va bene' || msgLower === 'procedi' || msgLower === 'confermo');
        var isNo = (msgLower === 'no' || msgLower === 'no grazie' || msgLower === 'annulla' || msgLower === 'non confermare');
        var container = document.querySelector('.swal2-container.swal2-center, .swal2-container');
        if (isYes && container) {
          var confirmBtn = container.querySelector('.swal2-confirm');
          if (confirmBtn) {
            try { confirmBtn.click(); } catch (e) {}
          }
          appendMessage('Ok, confermo l\'operazione.', false, null);
          state.pendingConfirm = null;
          restartSessionMic();
          return;
        }
        if (isNo && container) {
          var cancelBtn = container.querySelector('.swal2-cancel, .swal2-close');
          if (cancelBtn) {
            try { cancelBtn.click(); } catch (e) {}
          }
          appendMessage('Ok, annullo l\'operazione.', false, null);
          state.pendingConfirm = null;
          restartSessionMic();
          return;
        }
        // Messaggio non chiaro: chiedi sì/no esplicito e non andare al backend.
        appendMessage('Per favore rispondi solo con sì o no per la conferma.', false, null);
        restartSessionMic();
        return;
      }

      // Se siamo in modalità guida form, non chiamiamo il backend:
      // usiamo il messaggio per compilare il campo corrente.
      if (state.formGuide && state.formGuide.active) {
        if (msgLower === 'esci' || msgLower === 'stop' || msgLower === 'basta' || msgLower === 'annulla') {
          state.formGuide.active = false;
          appendMessage('Ok, smetto di guidare la compilazione del form.', false, null);
          return;
        }
        handleFormGuideAnswer(cleaned);
        // Dopo aver gestito la risposta guidata, riattiva il microfono di sessione
        // così puoi continuare a dettare il campo successivo.
        restartSessionMic();
        return;
      }

      setLoading(true);

      // Sblocca l'audio con un gesto utente: riproduci un istante di silenzio subito (così l'autoplay della risposta funziona)
      try {
        window.Kira = window.Kira || {};
        if (!window.Kira._audioPlayer) window.Kira._audioPlayer = new Audio();
        var primed = window.Kira._audioPlayer;
        primed.src = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=';
        primed.volume = 0;
        primed.play().catch(function () {});
      } catch (e) {}

      var actions = getAvailableActions();
      // Payload snello: solo id, label, active per evitare troncamento (75+ azioni con label lunghe).
      // labels non serve al backend per il matching; se serve in futuro si può riaggiungere.
      var available_actions = actions.map(function (a) {
        return {
          id: a.id,
          label: a.label,
          active: !!a.active
        };
      });
      var form_fields = getFormFieldsForBackend();

      if (typeof console !== 'undefined') {
        console.log('[Kira] invio messaggio + azioni + form all\'IA', actions.length, form_fields.length);
      }

      var body = {
        message: cleaned,
        conversation_id: state.conversationId,
        available_actions: available_actions,
        form_fields: form_fields.length ? form_fields : undefined
      };

      var headers = { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' };
      if (window.Kira && window.Kira.csrfToken) {
        headers['X-CSRF-TOKEN'] = window.Kira.csrfToken;
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
          if (typeof console !== 'undefined' && console.debug) {
            console.debug('[Kira] chat response', {
              message: data && data.message,
              client_action: data && data.client_action,
              action_id: data && data.action_id,
              conversation_id: data && data.conversation_id,
            });
          }
          if (data && data.conversation_id) {
            state.conversationId = data.conversation_id;
            persistState({ conversationId: state.conversationId || null });
          }

          var reply = (data && data.message) ? data.message : 'Nessuna risposta.';

          // Audio: Piper restituisce data.audio.base64 + data.audio.mime; altrimenti URL
          var audioUrl = null;
          if (data) {
            if (data.audio && data.audio.base64 && data.audio.mime) {
              audioUrl = 'data:' + data.audio.mime + ';base64,' + data.audio.base64;
            } else {
              audioUrl =
                data.audio_url ||
                data.tts_url ||
                data.voice_url ||
                (data.audio && (data.audio.url || data.audio.href)) ||
                null;
            }
          }

          // Compilazione form intelligente (prima del trigger, così dopo il click il form è già compilato se visibile)
          if (data && data.form_fill && typeof data.form_fill === 'object') {
            applyFormFill(data.form_fill);
          }

          // Se il backend segnala auto_reapply e il trigger non ha ancora un form da compilare,
          // salva il messaggio per riapplicarlo sulla pagina successiva finché non c'è un form.
          var hasFormFill = data && data.form_fill && typeof data.form_fill === 'object' && Object.keys(data.form_fill).length > 0;
          var shouldAutoReapply = !!(data && data.auto_reapply);
          if (data && data.client_action === 'trigger' && !hasFormFill && message && shouldAutoReapply) {
            if (typeof console !== 'undefined') {
              console.log('[Kira] salvo messaggio per riapplicazione automatica dopo trigger', message);
            }
            savePendingReapplyMessage(message);
          }

          // action_indices: più azioni in cascata per progressivo (preferito)
          // Non mettiamo in coda l'audio del trigger: in coda va solo il messaggio SweetAlert (es. "Timbratura registrata!").
          if (data && data.action_indices && Array.isArray(data.action_indices) && data.action_indices.length > 0) {
            var indices = data.action_indices;
            function runNext(i) {
              if (i >= indices.length) return;
              triggerPageActionByIndex(indices[i]);
              if (i + 1 < indices.length) {
                setTimeout(function () { runNext(i + 1); }, 400);
              }
            }
            runNext(0);
          } else if (data && (data.client_action === 'trigger' && (typeof data.action_index === 'number' || data.action_id))) {
            // trigger singolo: preferenza a action_index (numero), altrimenti action_id
            // Non mettiamo in coda l'audio del trigger.
            var triggerResult = typeof data.action_index === 'number'
              ? triggerPageActionByIndex(data.action_index)
              : triggerPageAction(data.action_id);
            reply = triggerResult.message;
          } else if (data && data.client_action) {
            // Legacy: click_timbra_entrata / click_timbra_uscita → stesso trigger per action_id
            // Non mettiamo in coda l'audio del trigger.
            var aid = data.action_id || (data.client_action === 'click_timbra_entrata' ? 'timbra_entrata' : data.client_action === 'click_timbra_uscita' ? 'timbra_uscita' : null);
            if (aid) {
              var triggerResult = triggerPageAction(aid);
              reply = triggerResult.message;
            }
          }

          appendMessage(reply, false, audioUrl);

          // Notifica eventuali estensioni browser: se è presente un listener
          // che intercetta i messaggi "KIRA_REPLY", può usare questo testo.
          try {
            window.postMessage({
              type: 'KIRA_REPLY',
              text: reply,
              audioUrl: audioUrl || null,
              source: 'devia-kira'
            }, '*');
          } catch (e) {}

          // Audio in-page solo per le risposte "normali" (senza cambio pagina).
          function onElaborationDone() {
            restartSessionMic();
          }
          var extActive = !!(window.Kira && window.Kira._extDetected);

          if (!data || !data.client_action) {
            if (audioUrl && !extActive) {
              try {
                window.Kira = window.Kira || {};
                if (!window.Kira._audioPlayer) window.Kira._audioPlayer = new Audio();
                var player = window.Kira._audioPlayer;
                player.pause();
                player.currentTime = 0;
                player.volume = 1;
                player.muted = false;
                player.src = audioUrl;
                player.addEventListener('ended', onElaborationDone, { once: true });
                player.addEventListener('error', onElaborationDone, { once: true });
                player.play().catch(function () { onElaborationDone(); });
              } catch (e) {
                onElaborationDone();
              }
            } else {
              // Nessun audio locale (o estensione attiva che gestisce l'audio): sblocca subito il mic.
              onElaborationDone();
            }
          } else {
            // Per i casi con cambio pagina, rimandiamo l'audio alla prossima pagina (pendingAudio).
            restartSessionMic();
          }

          // Se Kira ha registrato una timbratura, la dashboard mostra ancora i dati caricati al load:
          // ricarichiamo la pagina dopo un delay. Se appare uno SweetAlert di conferma, watchSweetAlert
          // posticipa il reload per dare tempo al TTS della conferma di essere pronunciato.
          if (reply && reply.indexOf(' in corso…') !== -1) {
            scheduleReloadAfterTrigger(3000);
          }

          // Se non ci sono pendingConfirm né guida form attiva, pianifica chiusura
          // automatica dopo un breve periodo di inattività.
          if (!state.pendingConfirm && !(state.formGuide && state.formGuide.active)) {
            scheduleAutoClose();
          }

          // Mette subito il focus sull'input così non rimani bloccato
          setTimeout(function () {
            if (inputEl && typeof inputEl.focus === 'function') inputEl.focus();
          }, 0);
        })
        .catch(function () {
          setLoading(false);
          appendMessage('Errore di connessione. Riprova.', false);
          restartSessionMic();
          setTimeout(function () {
            if (inputEl && typeof inputEl.focus === 'function') inputEl.focus();
          }, 0);
        });
    }

    // Espone sendMessage per il listener globale (capture); _sendMessageWithMessage per riapplicare messaggio dopo navigazione
    window.Kira = window.Kira || {};
    window.Kira._sendMessage = sendMessage;
    window.Kira._sendMessageWithMessage = function (msg) { sendMessage(msg); };

    var formEl = container.querySelector('.devia-form');
    if (formEl) {
      formEl.addEventListener('submit', function (e) {
        e.preventDefault();
        e.stopPropagation();
        sendMessage();
        return false;
      });
    }

    container.addEventListener('click', function (e) {
      if (e.target && (e.target.classList.contains('devia-send') || (e.target.closest && e.target.closest('.devia-send')))) {
        e.preventDefault();
        e.stopPropagation();
        sendMessage();
        return false;
      }
    });
    container.addEventListener('touchend', function (e) {
      if (e.target && (e.target.classList.contains('devia-send') || (e.target.closest && e.target.closest('.devia-send')))) {
        e.preventDefault();
        e.stopPropagation();
        sendMessage();
        return false;
      }
    }, { passive: false });
    sendBtn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      sendMessage();
    });
    sendBtn.addEventListener('touchend', function (e) {
      e.preventDefault();
      e.stopPropagation();
      sendMessage();
    }, { passive: false });
    inputEl.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });

    // Se c'è un audio "in sospeso" (salvato prima di un cambio pagina),
    // riproducilo ora che la nuova pagina è aperta.
    var hadPendingNavigation = false;
    try {
      var pending = consumePendingAudio();
      if (pending && pending.text && pending.audioUrl) {
        hadPendingNavigation = true;
        appendMessage(pending.text, false, pending.audioUrl);
        try {
          window.Kira = window.Kira || {};
          if (!window.Kira._audioPlayer) window.Kira._audioPlayer = new Audio();
          var p = window.Kira._audioPlayer;
          p.pause();
          p.currentTime = 0;
          p.volume = 1;
          p.muted = false;
          p.src = pending.audioUrl;
          p.play().catch(function () {});
        } catch (e) {}
      }
    } catch (e) {}

    // Riapplica prima il messaggio salvato dopo un trigger senza form: invia di nuovo al backend
    // sulla pagina corrente (es. Ferie/ROL) finché non viene restituito un form da compilare.
    // Se riapplichiamo il messaggio, NON attiviamo la guida form automatica.
    var hadReapply = false;
    try {
      var reapplyMsg = getPendingReapplyMessage();
      if (reapplyMsg) {
        clearPendingReapplyMessage();
        hadReapply = true;
        if (typeof console !== 'undefined') {
          console.log('[Kira] riapplico messaggio dopo navigazione:', reapplyMsg);
        }
        setTimeout(function () { sendMessage(reapplyMsg); }, 500);
      }
    } catch (e) {}

    // Se siamo arrivati qui a seguito di una navigazione guidata da Kira
    // (hadPendingNavigation) e NON c'è un messaggio da riapplicare, attiva la guida form.
    try {
      if (hadPendingNavigation && !hadReapply) {
        var steps = detectGuidedFormSteps();
        if (steps && steps.length) {
          startFormGuide(steps);
        }
      }
    } catch (e) {}

    // Focus automatico sul testo quando la chat si apre
    try {
      setTimeout(function () {
        if (inputEl && typeof inputEl.focus === 'function') {
          inputEl.focus();
          if (typeof inputEl.setSelectionRange === 'function') {
            var len = inputEl.value.length;
            inputEl.setSelectionRange(len, len);
          }
        }
      }, 0);
    } catch (e) {
      // ignore
    }


    // Suggerimento: se il browser è compatibile con l'estensione
    // audio e NON è stata rilevata l'estensione Kira by Devitalia,
    // mostra un breve messaggio informativo con il link di installazione.
    try {
      var extActive = !!(window.Kira && window.Kira._extDetected);
      if (isChromeLikeDesktop() && !extActive) {
        var info = document.createElement('div');
        info.setAttribute('data-kira-banner', 'install-ext');
        info.style.marginBottom = '8px';
        info.style.padding = '8px 12px';
        info.style.borderRadius = '8px';
        info.style.fontSize = '13px';
        info.style.wordBreak = 'break-word';
        info.style.background = '#fefce8';
        info.style.marginRight = '24px';
        var extUrl = (window.Kira && window.Kira.baseUrl ? window.Kira.baseUrl : '') + '/vendor/devia/kira.crx';
        info.innerHTML =
          'Installa <strong>Kira by Devitalia</strong> – puoi attivare la voce persistente di Kira installando ' +
          'l&#39;estensione <strong>&quot;Kira by Devitalia&quot;</strong> in Chrome. ' +
          '<a href="' + extUrl + '" style="text-decoration:underline; color:#2563eb;" target="_blank" rel="noopener noreferrer">' +
          'Scarica Kira</a>.';
        if (messagesEl) {
          messagesEl.appendChild(info);
          messagesEl.scrollTop = messagesEl.scrollHeight;
        }
      }
    } catch (e) {}

    // Attiva automaticamente il microfono (se supportato) quando si apre Kira
    try {
      var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (SpeechRecognition && state.micEnabled) {
        var recognition = new SpeechRecognition();
        recognition.lang = 'it-IT';
        recognition.continuous = true;
        recognition.interimResults = true;

        window.Kira = window.Kira || {};
        window.Kira._recognition = recognition;

        recognition.onresult = function (event) {
          if (!event.results || !event.results.length) return;
          var lastIdx = event.results.length - 1;
          var transcript = (event.results[lastIdx] && event.results[lastIdx][0]) ? event.results[lastIdx][0].transcript : '';
          if (!transcript || !(event.results[lastIdx] && event.results[lastIdx].isFinal)) return;

          // Ferma subito il microfono così non cattura altro mentre Kira elabora (evita invii multipli "c'è", "qui sotto", ecc.)
          stopSessionMic();

          console.log('[Kira] (sessione) pronunciato:', transcript);

          // Inserisce il testo riconosciuto nell'input
          var current = (inputEl.value || '').trim();
          inputEl.value = current ? (current + ' ' + transcript) : transcript;

          // Porta il cursore alla fine
          try {
            var len = inputEl.value.length;
            inputEl.setSelectionRange(len, len);
          } catch (e) {}

          // Invio automatico subito dopo la dettatura
          try {
            console.log('[Kira] (sessione) invio messaggio:', inputEl.value.trim());
            sendMessage();
            setTimeout(function () { inputEl.focus(); }, 50);
          } catch (e) {
            setTimeout(function () { inputEl.focus(); }, 50);
          }
        };

        recognition.onerror = function (e) {
          console.log('[Kira] (sessione) recognition error:', e.error, e.message || '');
        };
        recognition.onend = function () {
          console.log('[Kira] (sessione) recognition end → riavvio microfono');
          if (state.sessionOpen && state.micEnabled && !state.kiraResponding && getChatContainer() && getChatContainer().querySelector('.devia-panel')) {
            setTimeout(function () { try { recognition.start(); } catch (err) {} }, 300);
          }
        };

        console.log('[Kira] (sessione) microfono dettatura avviato');
        recognition.start();
      }
    } catch (e) {
      console.log('[Kira] (sessione) init recognition failed:', e);
    }
  }

  // Comando vocale per aprire Kira (es. "ehi devi")
  var VOICE_TRIGGER = (window.Kira && window.Kira.voiceTrigger)
    ? String(window.Kira.voiceTrigger).toLowerCase().trim()
    : 'kira';

  function startGlobalTriggerListener() {
    if (state.sessionOpen) return;
    if (!state.micEnabled) return;
    var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return;

    var recognition = new SpeechRecognition();
    recognition.lang = 'it-IT';
    recognition.continuous = true;
    recognition.interimResults = true;

    recognition.onresult = function (event) {
      if (state.sessionOpen) return;
      if (!event.results || !event.results.length) return;
      var transcript = '';
      var last = event.results.length - 1;
      if (event.results[last] && event.results[last][0]) {
        transcript = event.results[last][0].transcript || '';
      }
      transcript = transcript.toLowerCase().trim();
      if (transcript) {
        console.log('[Kira] (comando) pronunciato:', transcript, '(cercando trigger:', VOICE_TRIGGER + ')');
      }
      if (transcript.indexOf(VOICE_TRIGGER) !== -1) {
        console.log('[Kira] trigger rilevato → apertura sessione');
        try { recognition.stop(); } catch (e) {}
        openSession();
      }
    };

    recognition.onerror = function (e) {
      console.log('[Kira] (comando) recognition error:', e.error, e.message || '');
    };
    recognition.onend = function () {
      console.log('[Kira] (comando) recognition end (sessionOpen:', state.sessionOpen, ')');
      if (!state.sessionOpen) {
        window.Kira = window.Kira || {};
        window.Kira._globalRecognition = recognition;
        setTimeout(function () {
          if (!state.sessionOpen) try { recognition.start(); } catch (e) {}
        }, 400);
      }
    };

    window.Kira = window.Kira || {};
    window.Kira._globalRecognition = recognition;
    console.log('[Kira] microfono comando avviato (trigger: "' + VOICE_TRIGGER + '")');
    try { recognition.start(); } catch (e) {
      console.log('[Kira] (comando) start failed:', e);
    }
  }

  function init() {
    var root = getRoot();
    var btn = getFloatBtn();
    if (!root || !btn) return;

    // Handshake con l'estensione Kira Audio Companion (se presente):
    // se risponde con KIRA_EXT_PONG, disattiviamo l'audio locale automatico.
    try {
      window.Kira = window.Kira || {};
      window.Kira._extDetected = false;

      window.addEventListener('message', function (event) {
        var data = event.data;
        if (!data || typeof data !== 'object') return;
        if (data.type === 'KIRA_EXT_PONG') {
          window.Kira._extDetected = true;
          // Rimuovi eventuale banner \"Installa Kira\" già mostrato.
          try {
            var root = getChatContainer && getChatContainer();
            if (root) {
              var msgs = root.querySelector('.devia-messages');
              if (msgs) {
                var banners = msgs.querySelectorAll('[data-kira-banner=\"install-ext\"]');
                banners.forEach(function (n) { n.remove(); });
              }
            }
          } catch (e2) {}
        }
      });

      setTimeout(function () {
        try {
          window.postMessage({ type: 'KIRA_EXT_PING', source: 'devia-kira' }, '*');
        } catch (e) {}
      }, 500);
    } catch (e) {}

    function handleDeviaSend(e) {
      var target = e.target;
      if (!target || !target.closest) return;
      var sendBtnEl = target.closest('.devia-send');
      if (!sendBtnEl) return;
      var panel = sendBtnEl.closest('.devia-panel');
      if (!panel || panel.closest('#devia-root') === null) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      if (window.Kira && typeof window.Kira._sendMessage === 'function') {
        window.Kira._sendMessage();
      }
    }
    document.addEventListener('click', handleDeviaSend, true);
    document.addEventListener('touchend', handleDeviaSend, true);

    btn.addEventListener('click', function (e) {
      e.preventDefault();
      openSession();
    });

    // Se la sessione era aperta nella pagina precedente, riapriamo
    // automaticamente la chat in questa pagina.
    var persisted = loadPersistedState();
    if (persisted && persisted.sessionOpen) {
      // Ripristina eventuale conversationId noto (verrà comunque
      // aggiornato dalla risposta di /devia/session o /devia/chat).
      if (persisted.conversationId) {
        state.conversationId = persisted.conversationId;
      }
      openSession();
    } else {
      showFloat();
    }

    // Microfono sempre attivo: ascolta il comando "ehi devi" per aprire la sessione
    startGlobalTriggerListener();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
