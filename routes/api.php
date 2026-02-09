<?php

use Devia\Plugin\Http\Controllers\DeviaController;

Route::middleware(['web'])->group(function () {
    // Shell iframe di Kira (chatbot persistente lato browser)
    Route::get('kira-shell', function () {
        return view('devia::kira-shell');
    })->name('kira-shell');

    Route::get('session', [DeviaController::class, 'session'])->name('session');
    Route::get('connection-test', [DeviaController::class, 'connectionTest'])->name('connection-test');
    Route::get('manifest', [DeviaController::class, 'manifest'])->name('manifest');
    Route::get('chat', [DeviaController::class, 'chatGet'])->name('chat.get');
    Route::post('chat', [DeviaController::class, 'chat'])->name('chat');
    Route::post('debug-context', [DeviaController::class, 'debugContext'])->name('debug-context');
    Route::post('tts', [DeviaController::class, 'tts'])->name('tts');
});
