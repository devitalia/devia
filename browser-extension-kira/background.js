// Background service worker: riceve i messaggi dal content script e
// invia l'audioUrl di Piper a un offscreen document che lo riproduce.

chrome.runtime.onInstalled.addListener(() => {
  console.log('[Kira Audio Companion] Estensione installata.');
});

async function ensureOffscreenDocument() {
  if (await chrome.offscreen.hasDocument?.()) {
    return;
  }
  await chrome.offscreen.createDocument({
    url: 'offscreen.html',
    reasons: ['AUDIO_PLAYBACK'],
    justification: 'Riprodurre l’audio di Kira (Piper) in modo persistente tra i cambi pagina.'
  });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || typeof message !== 'object') return;
  if (message.type !== 'KIRA_REPLY') return;

  const audioUrl = message.audioUrl || null;
  if (!audioUrl) {
    // Nessun audio Piper: per ora non facciamo nulla (niente TTS browser).
    return;
  }

  ensureOffscreenDocument()
    .then(() => {
      chrome.runtime.sendMessage({
        type: 'PLAY_KIRA_AUDIO',
        audioUrl: audioUrl
      });
    })
    .catch((e) => {
      console.warn('[Kira Audio Companion] impossibile creare offscreen document:', e);
    });
});

