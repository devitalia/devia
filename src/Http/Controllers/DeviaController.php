<?php

namespace Devia\Plugin\Http\Controllers;

use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Http;
use Illuminate\Routing\Controller;
use Illuminate\Support\Facades\Log;
use Illuminate\Support\Str;

class DeviaController extends Controller
{
    /**
     * Payload utente per DevIA: solo id. Nome, email, reparto, azienda vengono letti dal DB
     * tramite query che il modello costruisce analizzando schema e codice intranet.
     */
    private function buildUserPayload(object $user): array
    {
        return [
            'id' => (string) $user->getAuthIdentifier(),
        ];
    }

    public function session(Request $request): JsonResponse
    {
        $user = $request->user();
        $userPayload = $user ? $this->buildUserPayload($user) : ['id' => 'guest'];

        return response()->json([
            'ok' => true,
            'user' => $userPayload,
            'conversation_id' => 'conv-' . uniqid(),
        ]);
    }

    /**
     * Manifest delle capacità esposte dall'app corrente a DevIA.
     * Ogni progetto può personalizzare/estendere questo elenco di tool.
     */
    public function manifest(Request $request): JsonResponse
    {
        $appId = config('app.name', 'intranet');

        return response()->json([
            'app_id' => Str::slug($appId) ?: 'intranet',
            'description' => $appId . ' (manifest DevIA)',
            'tools' => [
                [
                    'name' => 'timbra_entrata',
                    'description' => 'Registra una timbratura di entrata per l\'utente attualmente autenticato.',
                    'method' => 'POST',
                    'endpoint' => '/devia/tools/timbra-entrata',
                    'parameters' => [
                        'type' => 'object',
                        'properties' => [
                            'timestamp' => ['type' => 'string', 'format' => 'date-time'],
                        ],
                        'required' => [],
                    ],
                ],
                [
                    'name' => 'timbra_uscita',
                    'description' => 'Registra una timbratura di uscita per l\'utente attualmente autenticato.',
                    'method' => 'POST',
                    'endpoint' => '/devia/tools/timbra-uscita',
                    'parameters' => [
                        'type' => 'object',
                        'properties' => [
                            'timestamp' => ['type' => 'string', 'format' => 'date-time'],
                        ],
                        'required' => [],
                    ],
                ],
                [
                    'name' => 'prenota_ferie',
                    'description' => 'Crea una richiesta di ferie per l\'utente autenticato.',
                    'method' => 'POST',
                    'endpoint' => '/devia/tools/prenota-ferie',
                    'parameters' => [
                        'type' => 'object',
                        'properties' => [
                            'start_date' => ['type' => 'string', 'format' => 'date'],
                            'end_date' => ['type' => 'string', 'format' => 'date'],
                            'note' => ['type' => 'string'],
                        ],
                        'required' => ['start_date', 'end_date'],
                    ],
                ],
                [
                    'name' => 'prenota_rol',
                    'description' => 'Crea una richiesta di ROL per l\'utente autenticato.',
                    'method' => 'POST',
                    'endpoint' => '/devia/tools/prenota-rol',
                    'parameters' => [
                        'type' => 'object',
                        'properties' => [
                            'start_date' => ['type' => 'string', 'format' => 'date'],
                            'end_date' => ['type' => 'string', 'format' => 'date'],
                            'note' => ['type' => 'string'],
                        ],
                        'required' => ['start_date', 'end_date'],
                    ],
                ],
            ],
        ]);
    }

    /**
     * GET /devia/chat — risposta chiara se qualcuno apre l'URL con GET (evita 405 HTML).
     */
    public function chatGet(): JsonResponse
    {
        return response()->json([
            'type' => 'message',
            'assistant' => config('devia.assistant_name', 'Kira'),
            'message' => 'Questa route accetta solo POST. Invia un messaggio dalla chat (widget) o con: POST /devia/chat e body {"message": "testo"}.',
        ], 200);
    }

    public function chat(Request $request): JsonResponse
    {
        $request->validate([
            'message' => 'required|string|max:10000',
            'conversation_id' => 'nullable|string|max:255',
            'available_actions' => 'nullable|array',
            'available_actions.*.id' => 'required|string|max:500',
            'available_actions.*.label' => 'nullable|string|max:1000',
            'available_actions.*.active' => 'nullable|boolean',
            'form_fields' => 'nullable|array',
            'form_fields.*.label' => 'nullable|string|max:500',
            'form_fields.*.required' => 'nullable|boolean',
            'form_fields.*.type' => 'nullable|string|max:50',
        ]);

        $user = $request->user();
        $userPayload = $user ? $this->buildUserPayload($user) : ['id' => 'guest'];

        $apiUrl = rtrim(config('devia.api_url'), '/') . '/chat';
        $payload = [
            'user' => $userPayload,
            'message' => $request->input('message'),
            'conversation_id' => $request->input('conversation_id'),
            'app_url' => rtrim($request->root(), '/'),
        ];

        if ($request->has('available_actions') && is_array($request->input('available_actions'))) {
            $payload['available_actions'] = $request->input('available_actions');
        }
        if ($request->has('form_fields') && is_array($request->input('form_fields'))) {
            $payload['form_fields'] = $request->input('form_fields');
        }

        try {
            Log::debug('DevIA chat request', [
                'api_url' => $apiUrl,
                'message_preview' => mb_substr($request->input('message'), 0, 80),
                'available_actions_count' => isset($payload['available_actions']) ? count($payload['available_actions']) : 0,
                'available_actions' => $payload['available_actions'] ?? null,
            ]);

            $timeout = config('devia.chat_timeout', 120);
            $response = Http::timeout($timeout)->post($apiUrl, $payload);

            if (! $response->successful()) {
                $status = $response->status();
                $body = $response->body();
                Log::warning('DevIA chat non 2xx', [
                    'api_url' => $apiUrl,
                    'status' => $status,
                    'body' => $body,
                ]);
                $message = 'Errore temporaneo nel rispondere. Riprova.';
                if (config('app.debug')) {
                    $message .= ' [Debug: HTTP ' . $status . ' — ' . mb_substr($body, 0, 200) . ']';
                }
                $json = [
                    'type' => 'message',
                    'assistant' => config('devia.assistant_name', 'Kira'),
                    'message' => $message,
                ];
                if (config('app.debug')) {
                    $json['_debug'] = ['api_url' => $apiUrl, 'status' => $status, 'body_preview' => mb_substr($body, 0, 500)];
                }
                return response()->json($json, 200);
            }

            return response()->json($response->json());
        } catch (\Throwable $e) {
            $errorDetail = $e->getMessage();
            $previous = $e->getPrevious();
            if ($previous) {
                $errorDetail .= ' (causa: ' . $previous->getMessage() . ')';
            }
            Log::error('DevIA chat exception', [
                'api_url' => $apiUrl,
                'error' => $errorDetail,
                'exception' => get_class($e),
            ]);

            $userMessage = 'Servizio non raggiungibile. Verifica DEVIA_API_URL.';
            if (config('app.env') === 'local' || config('app.debug')) {
                $userMessage .= ' Debug: URL=' . $apiUrl . ' — ' . $errorDetail;
            }

            $json = [
                'type' => 'message',
                'assistant' => config('devia.assistant_name', 'Kira'),
                'message' => $userMessage,
            ];
            if (config('app.debug')) {
                $json['_debug'] = ['api_url' => $apiUrl, 'error' => $errorDetail, 'exception' => get_class($e)];
            }
            return response()->json($json, 200);
        }
    }

    /**
     * Proxy TTS: inoltra il testo a DevIA (/tts) e restituisce l'audio Piper.
     */
    public function tts(Request $request): JsonResponse
    {
        $validated = $request->validate([
            'text' => 'required|string|max:5000',
        ]);

        $apiUrl = rtrim(config('devia.api_url'), '/') . '/tts';

        try {
            $response = Http::timeout(30)->post($apiUrl, [
                'text' => $validated['text'],
            ]);

            if (! $response->successful()) {
                Log::warning('DevIA TTS non 2xx', [
                    'api_url' => $apiUrl,
                    'status' => $response->status(),
                    'body' => $response->body(),
                ]);

                return response()->json(['ok' => false], 200);
            }

            $json = $response->json();
            if (! is_array($json) || ! ($json['ok'] ?? false)) {
                return response()->json(['ok' => false], 200);
            }

            return response()->json($json);
        } catch (\Throwable $e) {
            Log::warning('DevIA TTS exception', [
                'api_url' => $apiUrl,
                'error' => $e->getMessage(),
            ]);

            return response()->json(['ok' => false], 200);
        }
    }

    /**
     * Estrae l'ID utente passato da DevIA nel header dedicato.
     * In demo non facciamo mapping al modello User; nelle integrazioni reali
     * qui puoi risolvere l'utente effettivo dal DB.
     */
    protected function getToolUserId(Request $request): string
    {
        return (string) $request->header('X-Devia-User-Id', 'guest');
    }

    public function toolTimbraEntrata(Request $request): JsonResponse
    {
        $userId = $this->getToolUserId($request);
        $timestamp = $request->input('timestamp') ?: now()->toIso8601String();

        // DEMO: nessuna scrittura DB, solo eco. In produzione qui registri la timbratura.
        return response()->json([
            'ok' => true,
            'tool' => 'timbra_entrata',
            'user_id' => $userId,
            'timestamp' => $timestamp,
            'message' => "Timbratura di entrata registrata (demo) alle {$timestamp} per utente {$userId}.",
        ]);
    }

    public function toolTimbraUscita(Request $request): JsonResponse
    {
        $userId = $this->getToolUserId($request);
        $timestamp = $request->input('timestamp') ?: now()->toIso8601String();

        return response()->json([
            'ok' => true,
            'tool' => 'timbra_uscita',
            'user_id' => $userId,
            'timestamp' => $timestamp,
            'message' => "Timbratura di uscita registrata (demo) alle {$timestamp} per utente {$userId}.",
        ]);
    }

    public function toolPrenotaFerie(Request $request): JsonResponse
    {
        $validated = $request->validate([
            'start_date' => 'required|date',
            'end_date' => 'required|date|after_or_equal:start_date',
            'note' => 'nullable|string|max:1000',
        ]);

        $userId = $this->getToolUserId($request);

        return response()->json([
            'ok' => true,
            'tool' => 'prenota_ferie',
            'user_id' => $userId,
            'data' => $validated,
            'message' => sprintf(
                'Richiesta ferie (demo) dal %s al %s creata per utente %s.',
                $validated['start_date'],
                $validated['end_date'],
                $userId
            ),
        ]);
    }

    public function toolPrenotaRol(Request $request): JsonResponse
    {
        $validated = $request->validate([
            'start_date' => 'required|date',
            'end_date' => 'required|date|after_or_equal:start_date',
            'note' => 'nullable|string|max:1000',
        ]);

        $userId = $this->getToolUserId($request);

        return response()->json([
            'ok' => true,
            'tool' => 'prenota_rol',
            'user_id' => $userId,
            'data' => $validated,
            'message' => sprintf(
                'Richiesta ROL (demo) dal %s al %s creata per utente %s.',
                $validated['start_date'],
                $validated['end_date'],
                $userId
            ),
        ]);
    }

    /**
     * Test connessione Laravel → DevIA. Restituisce health DevIA o errore.
     * GET /devia/connection-test — utile per debug (vedi se Laravel raggiunge DevIA).
     */
    public function connectionTest(): JsonResponse
    {
        $apiUrl = rtrim(config('devia.api_url'), '/') . '/health';

        try {
            $response = Http::timeout(5)->get($apiUrl);
            $status = $response->status();
            $body = $response->json();

            if ($response->successful()) {
                return response()->json([
                    'ok' => true,
                    'message' => 'Laravel raggiunge DevIA.',
                    'devia_health' => $body,
                ]);
            }

            return response()->json([
                'ok' => false,
                'message' => 'DevIA ha risposto con HTTP ' . $status,
                'status' => $status,
                'body' => $response->body(),
                'api_url' => $apiUrl,
            ], 200);
        } catch (\Throwable $e) {
            $msg = $e->getMessage();
            Log::warning('DevIA connection test failed', ['api_url' => $apiUrl, 'error' => $msg]);

            return response()->json([
                'ok' => false,
                'message' => 'Laravel non riesce a raggiungere DevIA.',
                'error' => config('app.debug') ? $msg : null,
                'api_url' => $apiUrl,
            ], 200);
        }
    }

    /**
     * Restituisce il contesto che verrebbe inviato all'LLM (system prompt, user, message, schema DB)
     * senza effettuare la chiamata alla chat. Utile per "vedere la chiamata" in debug.
     * Body: come POST /devia/chat (message obbligatorio, conversation_id opzionale).
     */
    public function debugContext(Request $request): JsonResponse
    {
        $request->validate([
            'message' => 'required|string|max:10000',
            'conversation_id' => 'nullable|string|max:255',
        ]);

        $user = $request->user();
        $userPayload = $user ? $this->buildUserPayload($user) : [
            'id' => 'guest',
            'name' => 'Guest',
        ];

        $apiUrl = rtrim(config('devia.api_url'), '/') . '/debug/context';
        $payload = [
            'user' => $userPayload,
            'message' => $request->input('message'),
            'conversation_id' => $request->input('conversation_id'),
            'app_url' => rtrim($request->root(), '/'),
        ];

        try {
            $timeout = config('devia.chat_timeout', 120);
            $response = Http::timeout($timeout)->post($apiUrl, $payload);

            if (! $response->successful()) {
                return response()->json([
                    'error' => 'Backend DevIA non ha risposto',
                    'status' => $response->status(),
                    'body' => $response->body(),
                ], 502);
            }

            return response()->json($response->json());
        } catch (\Throwable $e) {
            Log::warning('DevIA debug/context exception', [
                'api_url' => $apiUrl,
                'error' => $e->getMessage(),
            ]);

            return response()->json([
                'error' => 'Servizio non raggiungibile',
                'detail' => config('app.debug') ? $e->getMessage() : null,
            ], 502);
        }
    }
}
