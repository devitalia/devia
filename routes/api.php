<?php

use Devia\Plugin\Http\Controllers\DeviaController;

Route::middleware(['web'])->group(function () {
    Route::get('session', [DeviaController::class, 'session'])->name('session');
    Route::post('chat', [DeviaController::class, 'chat'])->name('chat');
});
