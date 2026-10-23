/* Heart next to the product name: saves or removes the product from favorites (same endpoints as the Shop cards). */
(function () {
    var btn = document.querySelector('.title-heart');
    if (!btn) return;
    var id = parseInt(btn.dataset.heartId, 10);
    function paint(on) {
        btn.classList.toggle('active', on);
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        btn.setAttribute('aria-label', on ? 'Remove from favorites' : 'Save to favorites');
        var path = btn.querySelector('path');
        if (path) path.setAttribute('fill', on ? 'currentColor' : 'none');
    }
    function post(url, body) {
        return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
            .then(function (r) { return r.json(); });
    }
    post('/favorites/check-batch', { items: [{ product_id: id, color_name: '' }] })
        .then(function (d) { paint(!!(d.favorites && d.favorites[id + ':'])); })
        .catch(function () {});
    btn.addEventListener('click', function () {
        var on = btn.classList.contains('active');
        post(on ? '/favorites/remove' : '/favorites/add', { product_id: id, color_name: '' })
            .then(function (d) {
                if (d.success) paint(!on);
                else if (window.PMKC && PMKC.showFlash) PMKC.showFlash(d.error || 'Could not update favorites', 'error');
            })
            .catch(function () {});
    });
})();
