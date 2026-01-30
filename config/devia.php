<?php

return [
    'api_url' => env('DEVIA_API_URL', 'http://localhost:8787'),
    'tool_token' => env('DEVIA_LARAVEL_TOOL_TOKEN', env('CHATBOT_TOOL_TOKEN')),
    'voice_trigger' => env('DEVIA_VOICE_TRIGGER', 'ehi devia'),
];
