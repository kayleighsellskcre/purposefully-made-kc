/* Keep the shopper's place on the page.
   When a button or link reloads the SAME page with new information (a form that
   saves and redirects back, a filter, a sort), put the page back where it was
   instead of jumping to the top. Different pages still open at the top. */
(function () {
    var KEY = 'pmkc_keep_scroll';
    var MAX_AGE_MS = 15000;

    function save() {
        try {
            sessionStorage.setItem(KEY, JSON.stringify({
                path: location.pathname, y: window.scrollY, t: Date.now()
            }));
        } catch (e) {}
    }

    function restore() {
        var raw;
        try { raw = sessionStorage.getItem(KEY); sessionStorage.removeItem(KEY); } catch (e) { return; }
        if (!raw || location.hash) return;            // a #link means "go there"
        var s;
        try { s = JSON.parse(raw); } catch (e) { return; }
        if (!s || s.path !== location.pathname || Date.now() - s.t > MAX_AGE_MS) return;
        if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
        window.scrollTo(0, s.y);
        // Images and fonts can push things down after load; set it once more.
        window.addEventListener('load', function () { window.scrollTo(0, s.y); });
    }

    document.addEventListener('submit', function (e) {
        var f = e.target;
        if (!f || e.defaultPrevented || f.target === '_blank' || f.hasAttribute('data-top')) return;
        var action = f.getAttribute('action');
        if (action) {
            var a = document.createElement('a');
            a.href = action;
            if (a.pathname !== location.pathname) { save(); return; }   // posts elsewhere, then redirects back
        }
        save();
    }, true);

    document.addEventListener('click', function (e) {
        var a = e.target.closest && e.target.closest('a[href]');
        if (!a || e.defaultPrevented || a.target === '_blank' || a.hasAttribute('data-top') ||
            e.metaKey || e.ctrlKey || e.shiftKey || a.hasAttribute('download')) return;
        if (a.origin === location.origin && a.pathname === location.pathname && !a.hash) save();
    }, true);

    restore();
})();
