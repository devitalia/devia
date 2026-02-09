{{-- Kira: floating in basso a destra, compare 1s ogni 5s; click apre la chat --}}
<div id="devia-root" style="position:fixed;bottom:24px;right:24px;z-index:999999;width:auto;height:auto;pointer-events:none;">
    <div
        id="devia-float-btn"
        aria-label="Apri Kira, assistente IA"
        style="
            pointer-events:none;
            opacity:0;
            transition:opacity 0.25s ease, transform 0.15s ease;
            cursor:pointer;
            width:54px;
            height:54px;
            border-radius:999px;
            background:#2A588D;
            display:flex;
            align-items:center;
            justify-content:center;
            box-shadow:0 6px 18px rgba(42,88,141,0.45);
        "
    >
        {{-- Icona chat IA minimal --}}
        <span style="display:inline-flex;width:36px;height:36px;align-items:center;justify-content:center;">
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" style="width:28px;height:28px;fill:#ffffff;">
                <path d="M5 4h14a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2H13l-3.6 3.2A1 1 0 0 1 8 18.9V15H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Zm3 4a1 1 0 1 0 0 2h8a1 1 0 1 0 0-2H8Zm0 4a1 1 0 1 0 0 2h4a1 1 0 1 0 0-2H8Z"/>
            </svg>
        </span>
    </div>
    <div id="devia-chat-container"></div>
</div>
<script>
(function() {
    window.Kira = window.Kira || {};
    window.Kira.baseUrl = @json(rtrim(url('/'), '/'));
    window.Kira.apiUrl = @json(config('devia.api_url', ''));
    window.Kira.csrfToken = @json(csrf_token());
    window.Kira.voiceTrigger = @json(config('devia.voice_trigger', 'kira'));
})();
</script>
<script src="{{ asset('vendor/devia/devia-client.js') }}?v=3" defer></script>
