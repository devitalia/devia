<?php

use Devia\Plugin\Http\Controllers\DeviaController;

// Chiamate server-to-server da DevIA: solo Bearer token, nessuna sessione.
Route::post('tools/timbra-entrata', [DeviaController::class, 'toolTimbraEntrata'])->name('tools.timbra-entrata');
Route::post('tools/timbra-uscita', [DeviaController::class, 'toolTimbraUscita'])->name('tools.timbra-uscita');
Route::post('tools/prenota-ferie', [DeviaController::class, 'toolPrenotaFerie'])->name('tools.prenota-ferie');
Route::post('tools/prenota-rol', [DeviaController::class, 'toolPrenotaRol'])->name('tools.prenota-rol');
