<?php

namespace Devia\Plugin;

use Devia\Plugin\Http\Middleware\DeviaToolToken;
use Illuminate\Support\Facades\Blade;
use Illuminate\Support\Facades\Route;
use Illuminate\Support\ServiceProvider;

class DeviaServiceProvider extends ServiceProvider
{
    public function register(): void
    {
        $this->mergeConfigFrom(__DIR__ . '/../config/devia.php', 'devia');
    }

    public function boot(): void
    {
        $this->publishes([
            __DIR__ . '/../config/devia.php' => config_path('devia.php'),
        ], 'devia-config');

        $this->publishes([
            __DIR__ . '/../resources/js' => public_path('vendor/devia'),
            __DIR__ . '/../resources/public' => public_path('vendor/devia'),
        ], 'devia-assets');

        $this->loadViewsFrom(__DIR__ . '/../resources/views', 'devia');

        Blade::directive('devia', function () {
            return "<?php echo view('devia::widget')->render(); ?>";
        });

        $this->app['router']->aliasMiddleware('devia.tool', DeviaToolToken::class);

        $this->registerRoutes();
    }

    protected function registerRoutes(): void
    {
        // Chat, session, manifest: richiedono sessione (browser con cookie)
        Route::middleware('web')->group(function () {
            $path = __DIR__ . '/../routes/api.php';
            if (file_exists($path)) {
                Route::prefix('devia')->name('devia.')->group($path);
            }
        });

        // Tool: solo Bearer token. Se l'app usa i propri controller (es. DeviaToolsController),
        // imposta config devia.register_tool_routes = false e registra le route in web.php.
        if (config('devia.register_tool_routes', true)) {
            Route::middleware(['devia.tool'])->group(function () {
                $path = __DIR__ . '/../routes/tools.php';
                if (file_exists($path)) {
                    Route::prefix('devia')->name('devia.')->group($path);
                }
            });
        }
    }
}
