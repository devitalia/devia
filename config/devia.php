<?php

return [
    'api_url' => env('DEVIA_API_URL', 'http://localhost:8787'),
    'chat_timeout' => (int) env('DEVIA_CHAT_TIMEOUT', 120),
    'tool_token' => env('DEVIA_LARAVEL_TOOL_TOKEN', env('CHATBOT_TOOL_TOKEN')),
    'voice_trigger' => env('DEVIA_VOICE_TRIGGER', 'kira'),
    'assistant_name' => env('DEVIA_ASSISTANT_NAME', 'Kira'),

    // Se false, il plugin NON registra le route demo dei tool (timbra-entrata, timbra-uscita, ecc.).
    // L'app (es. intranet) deve registrare le proprie route reali in web.php o api.php.
    'register_tool_routes' => env('DEVIA_REGISTER_TOOL_ROUTES', true),
];
