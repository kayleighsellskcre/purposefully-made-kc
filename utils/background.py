"""Run non-critical work after the customer already got a response."""
import threading


def run_in_background(app, fn, *args, **kwargs):
    """Start a daemon thread with an app context. Never raises to the caller."""
    def _run():
        try:
            with app.app_context():
                fn(*args, **kwargs)
        except Exception:
            try:
                app.logger.exception('background task failed: %s', getattr(fn, '__name__', fn))
            except Exception:
                pass

    if app.config.get('TESTING'):
        # Inline under test, so assertions see the effect and a second thread
        # cannot interleave transactions on SQLite's single shared connection.
        _run()
        return

    threading.Thread(target=_run, daemon=True).start()
