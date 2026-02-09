<?php

namespace Devia\Plugin\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

class DeviaToolToken
{
    /**
     * Protegge le route dei tool DevIA: accetta solo richieste con Bearer token valido.
     * Nessuna sessione/cookie: usato per le chiamate server-to-server da DevIA.
     */
    public function handle(Request $request, Closure $next): Response
    {
        $configured = config('devia.tool_token');
        if (! $configured) {
            return $next($request);
        }
        $header = $request->header('Authorization', '');
        if (! str_starts_with($header, 'Bearer ')) {
            return response()->json(['ok' => false, 'error' => 'Missing Bearer token for DevIA tool'], 401);
        }
        $token = substr($header, 7);
        if (! hash_equals($configured, $token)) {
            return response()->json(['ok' => false, 'error' => 'Invalid DevIA tool token'], 401);
        }
        return $next($request);
    }
}
