<?php

namespace Devia\Plugin;

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
        ], 'devia-assets');

        $this->loadViewsFrom(__DIR__ . '/../resources/views', 'devia');

        Blade::directive('devia', function () {
            return "<?php echo view('devia::widget')->render(); ?>";
        });

        $this->registerRoutes();
    }

    protected function registerRoutes(): void
    {
        Route::middleware('web')->group(function () {
            $path = __DIR__ . '/../routes/api.php';
            if (file_exists($path)) {
                Route::prefix('devia')->name('devia.')->group($path);
            }
        });
    }
}
