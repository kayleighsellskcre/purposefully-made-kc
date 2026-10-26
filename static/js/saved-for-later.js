/* Save for later: set a cart item aside, bring it back, or remove it. The page reloads so every total is right. */
(function () {
    function say(message, kind) {
        if (window.PMKC && typeof window.PMKC.showFlash === 'function') { window.PMKC.showFlash(message, kind || 'error'); }
        else { window.alert(message); }
    }
    function post(url, button, done) {
        var label = button.textContent;
        button.disabled = true;
        button.textContent = 'One moment…';
        fetch(url, { method: 'POST', headers: { 'Accept': 'application/json' } })
            .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
            .then(function (res) {
                if (res.ok && res.data.success) {
                    if (res.data.note) { try { sessionStorage.setItem('pmkcSavedNote', res.data.note); } catch (e) {} }
                    done(res.data);
                } else {
                    say((res.data && res.data.message) || 'That did not work. Please try again.');
                    button.disabled = false;
                    button.textContent = label;
                }
            })
            .catch(function () {
                say('That did not work. Please check your connection and try again.');
                button.disabled = false;
                button.textContent = label;
            });
    }
    document.addEventListener('click', function (e) {
        var save = e.target.closest('[data-save-for-later]');
        var move = e.target.closest('[data-saved-move]');
        var remove = e.target.closest('[data-saved-remove]');
        if (save) {
            e.preventDefault();
            post('/cart/save-for-later/' + save.getAttribute('data-save-for-later'), save, function () { window.location.reload(); });
        } else if (move) {
            e.preventDefault();
            post('/cart/saved/' + move.getAttribute('data-saved-move') + '/move', move, function () {
                window.location.href = '/cart/';
            });
        } else if (remove) {
            e.preventDefault();
            post('/cart/saved/' + remove.getAttribute('data-saved-remove') + '/remove', remove, function () { window.location.reload(); });
        }
    });
    try {
        var note = sessionStorage.getItem('pmkcSavedNote');
        if (note) { sessionStorage.removeItem('pmkcSavedNote'); say(note, 'info'); }
    } catch (e) {}
})();
