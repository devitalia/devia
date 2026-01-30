{{-- DevIA: widget invisibile fino al trigger vocale "ehi DevIa" --}}
<div id="devia-root" aria-hidden="true" style="position:fixed;z-index:999999;pointer-events:none;opacity:0;width:0;height:0;overflow:hidden;">
    {{-- UI chat montata qui quando la sessione si apre --}}
</div>
<script>
(function() {
    window.DevIA = {
        baseUrl: @json(rtrim(url('/'), '/')),
        apiUrl: @json(config('devia.api_url', '')),
        voiceTrigger: @json(config('devia.voice_trigger', 'ehi devia')),
        csrfToken: @json(csrf_token()),
    };
})();
</script>
<script src="{{ asset('vendor/devia/devia-client.js') }}" defer></script>
