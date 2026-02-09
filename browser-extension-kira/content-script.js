// Content script: gira dentro la pagina dell'intranet.
// Ascolta i postMessage generati da devia-client.js e li inoltra al background.

(function () {
  try {
    window.addEventListener('message', function (event) {
      // Per sicurezza, filtriamo solo i messaggi che ci interessano.
      var data = event.data;
      if (!data || typeof data !== 'object') return;

      // Handshake: conferma alla pagina che l'estensione è installata.
      if (data.type === 'KIRA_EXT_PING') {
        try {
          window.postMessage(
            {
              type: 'KIRA_EXT_PONG',
              source: 'kira-audio-extension'
            },
            '*'
          );
        } catch (e2) {}
        return;
      }

      if (data.type !== 'KIRA_REPLY') return;

      chrome.runtime.sendMessage({
        type: 'KIRA_REPLY',
        text: data.text || '',
        audioUrl: data.audioUrl || null
      });
    });
  } catch (e) {
    // Se qualcosa va storto, non blocchiamo la pagina.
  }
})();

