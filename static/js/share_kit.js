/* Share box: the link with Copy, the QR code, Download QR and Print flyer. One dialog per page. */
(function () {
    if (window.__shareKit) { return; }
    window.__shareKit = true;
    function ready(fn) {
        if (document.readyState !== 'loading') { fn(); } else { document.addEventListener('DOMContentLoaded', fn); }
    }
    ready(function () {
        var dialog = document.getElementById('distShareDialog');
        if (!dialog) { return; }
        var input = document.getElementById('distShareInput');
        var copy = document.getElementById('distShareCopy');
        function open(btn) {
            document.getElementById('distShareTitle').textContent = btn.getAttribute('data-share-title');
            input.value = btn.getAttribute('data-share-display');
            input.setAttribute('data-full', btn.getAttribute('data-share-url'));
            var qr = btn.getAttribute('data-share-qr');
            document.getElementById('distShareQr').src = qr;
            document.getElementById('distShareDownload').href = qr + '?download=1';
            var flyer = btn.getAttribute('data-share-flyer');
            dialog.querySelectorAll('[data-flyer-image]').forEach(function (a) {
                a.href = flyer.replace('/flyer.pdf', '/flyer.png') + (flyer.indexOf('?') < 0 ? '?' : '&') + 'style=' + a.getAttribute('data-flyer-image') + '&download=1';
            });
            dialog.querySelectorAll('[data-flyer-style]').forEach(function (a) {
                a.href = flyer + (flyer.indexOf('?') < 0 ? '?' : '&') + 'style=' + a.getAttribute('data-flyer-style');
            });
            copy.textContent = 'Copy';
            if (dialog.showModal) { dialog.showModal(); } else { dialog.setAttribute('open', ''); }
        }
        document.addEventListener('click', function (e) {
            var btn = e.target.closest('[data-share-url]');
            if (btn) { e.preventDefault(); open(btn); return; }
            if (e.target === dialog) { dialog.close(); }
        });
        copy.addEventListener('click', function () {
            var text = input.getAttribute('data-full') || input.value;
            function done() { copy.textContent = 'Copied'; }
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text).then(done, function () { input.select(); document.execCommand('copy'); done(); });
            } else { input.select(); document.execCommand('copy'); done(); }
        });
    });
})();
