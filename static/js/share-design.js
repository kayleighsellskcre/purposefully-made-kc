/* Share this design: ask for the link, then show it with a Copy button and a QR code. */
(function () {
    var dialog = document.getElementById('madeShareDialog');
    if (!dialog) { return; }
    var input = document.getElementById('madeShareInput');
    function token() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.content : '';
    }
    function say(message) {
        if (window.PMKC && typeof window.PMKC.showFlash === 'function') { window.PMKC.showFlash(message, 'error'); }
        else { window.alert(message); }
    }
    document.addEventListener('click', function (e) {
        var open = e.target.closest('[data-share-design]');
        if (open) {
            e.preventDefault();
            var label = open.textContent;
            open.disabled = true;
            open.textContent = 'One moment…';
            fetch(open.getAttribute('data-share-design'), { method: 'POST', headers: { 'Accept': 'application/json', 'X-CSRFToken': token() } })
                .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
                .then(function (res) {
                    open.disabled = false;
                    open.textContent = label;
                    if (!(res.ok && res.data.success)) { say((res.data && res.data.message) || 'That did not work. Please try again.'); return; }
                    input.value = res.data.url;
                    document.getElementById('madeShareQr').src = res.data.qr;
                    document.getElementById('madeShareDownload').href = res.data.qr + '?download=1';
                    if (typeof dialog.showModal === 'function') { dialog.showModal(); } else { dialog.setAttribute('open', ''); }
                })
                .catch(function () { open.disabled = false; open.textContent = label; say('That did not work. Please check your connection and try again.'); });
        } else if (e.target.closest('[data-made-close]') || e.target === dialog) {
            dialog.close();
        } else if (e.target.id === 'madeShareCopy') {
            input.select();
            var button = e.target;
            var done = function () { button.textContent = 'Copied'; setTimeout(function () { button.textContent = 'Copy'; }, 1800); };
            if (navigator.clipboard) { navigator.clipboard.writeText(input.value).then(done, function () { document.execCommand('copy'); done(); }); }
            else { document.execCommand('copy'); done(); }
        }
    });
})();
