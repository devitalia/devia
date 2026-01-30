<?php

namespace Devia\Plugin\Http\Controllers;

use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Http;
use Illuminate\Routing\Controller;
use Illuminate\Support\Facades\Log;

class DeviaController extends Controller
{
    public function session(Request $request): JsonResponse
    {
        $user = $request->user();
        $userPayload = $user ? [
            'id' => $user->getAuthIdentifier(),
            'name' => $user->name ?? $user->email ?? 'Guest',
            'email' => $user->email ?? null,
        ] : [
            'id' => 'guest',
            'name' => 'Guest',
        ];

        return response()->json([
            'ok' => true,
            'user' => $userPayload,
            'conversation_id' => 'conv-' . uniqid(),
        ]);
    }

    public function chat(Request $request): JsonResponse
    {
        $request->validate([
            'message' => 'required|string|max:10000',
            'conversation_id' => 'nullable|string|max:255',
        ]);

        $user = $request->user();
        $userPayload = $user ? [
            'id' => (string) $user->getAuthIdentifier(),
            'name' => $user->name ?? $user->email ?? 'Guest',
            'email' => $user->email ?? null,
        ] : [
            'id' => 'guest',
            'name' => 'Guest',
        ];

        $apiUrl = rtrim(config('devia.api_url'), '/') . '/chat';
        $payload = [
            'user' => $userPayload,
            'message' => $request->input('message'),
            'conversation_id' => $request->input('conversation_id'),
        ];

        try {
            $response = Http::timeout(30)->post($apiUrl, $payload);

            if (! $response->successful()) {
                Log::warning('DevIA chat non 2xx', [
                    'status' => $response->status(),
                    'body' => $response->body(),
                ]);
                return response()->json([
                    'type' => 'message',
                    'assistant' => 'DevIA',
                    'message' => 'Errore temporaneo nel rispondere. Riprova.',
                ], 200);
            }

            return response()->json($response->json());
        } catch (\Throwable $e) {
            Log::error('DevIA chat exception', ['error' => $e->getMessage()]);
            return response()->json([
                'type' => 'message',
                'assistant' => 'DevIA',
                'message' => 'Servizio non raggiungibile. Verifica DEVIA_API_URL.',
            ], 200);
        }
    }
}
