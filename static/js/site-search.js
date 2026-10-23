/* Header search: products and gallery designs together, as you type. */
(function () {
    var btn = document.getElementById('siteSearchToggle');
    var panel = document.getElementById('siteSearch');
    var input = document.getElementById('siteSearchInput');
    var out = document.getElementById('siteSearchResults');
    if (!btn || !panel || !input || !out) return;
    var timer = null, last = '';

    function open() { panel.hidden = false; btn.setAttribute('aria-expanded', 'true'); input.focus(); }
    function close() { panel.hidden = true; btn.setAttribute('aria-expanded', 'false'); }
    btn.addEventListener('click', function () { panel.hidden ? open() : close(); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !panel.hidden) { close(); btn.focus(); } });
    document.addEventListener('click', function (e) {
        if (!panel.hidden && !panel.contains(e.target) && !btn.contains(e.target)) close();
    });

    function esc(text) { var d = document.createElement('div'); d.textContent = text == null ? '' : text; return d.innerHTML; }
    function group(title, items, render) {
        if (!items.length) return '';
        return '<div class="ss-group"><p class="ss-title">' + title + '</p>' + items.map(render).join('') + '</div>';
    }
    function show(data, q) {
        var html = group('Shirts', data.products, function (p) {
            return '<a class="ss-item" href="' + esc(p.url) + '"><span>' + esc(p.name) + '</span><small>' + esc(p.brand) + '</small></a>';
        }) + group('Designs', data.designs, function (d) {
            return '<a class="ss-item" href="' + esc(d.url) + '">' + (d.image ? '<img src="' + esc(d.image) + '" alt="" loading="lazy">' : '') + '<span>' + esc(d.title) + '</span></a>';
        });
        out.innerHTML = html || '<p class="ss-empty">Nothing found for that yet. Try another word, or <a href="/contact">message us</a>.</p>';
        if (html) out.innerHTML += '<a class="ss-all" href="/shop/?q=' + encodeURIComponent(q) + '">See all shirts for &ldquo;' + esc(q) + '&rdquo;</a>';
    }
    input.addEventListener('input', function () {
        var q = input.value.trim();
        clearTimeout(timer);
        if (q.length < 2) { out.innerHTML = ''; last = ''; return; }
        timer = setTimeout(function () {
            if (q === last) return;
            last = q;
            fetch('/api/site-search?q=' + encodeURIComponent(q), { headers: { 'Accept': 'application/json' } })
                .then(function (r) { return r.ok ? r.json() : { products: [], designs: [] }; })
                .then(function (data) { if (input.value.trim() === q) show(data, q); })
                .catch(function () { out.innerHTML = ''; });
        }, 220);
    });
    input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && input.value.trim()) { window.location.href = '/shop/?q=' + encodeURIComponent(input.value.trim()); }
    });
})();
