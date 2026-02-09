// Offscreen document: riproduce l'audio di Piper (audioUrl) in modo
// indipendente dalla pagina che ha generato la risposta.

let audio = null;

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || typeof message !== 'object') return;
  if (message.type !== 'PLAY_KIRA_AUDIO') return;

  const url = message.audioUrl;
  if (!url) return;

  try {
    if (!audio) {
      audio = new Audio();
    }
    audio.pause();
    audio.currentTime = 0;
    audio.src = url;
    audio.volume = 1.0;
    audio.muted = false;
    audio.play().catch((e) => {
      console.warn('[Kira Audio Offscreen] play failed:', e);
    });
  } catch (e) {
    console.warn('[Kira Audio Offscreen] error:', e);
  }
});

