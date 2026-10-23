/* Kind Words: filter chips and a quiet photo viewer. */
(function () {
    var collage = document.getElementById('kwCollage');
    if (!collage) return;

    var chips = document.querySelectorAll('.kw-chip');
    chips.forEach(function (chip) {
        chip.addEventListener('click', function () {
            var want = chip.dataset.filter;
            chips.forEach(function (c) {
                var on = c === chip;
                c.classList.toggle('is-on', on);
                c.setAttribute('aria-pressed', on ? 'true' : 'false');
            });
            collage.querySelectorAll('.kw-tile').forEach(function (tile) {
                tile.hidden = want !== 'all' && tile.dataset.kind !== want;
            });
        });
    });

    var box = document.getElementById('kwLightbox');
    var img = document.getElementById('kwLightboxImg');
    var cap = document.getElementById('kwLightboxCap');
    var opener = null;

    function close() {
        box.hidden = true;
        img.src = '';
        document.body.style.overflow = '';
        if (opener) opener.focus();
    }

    collage.addEventListener('click', function (event) {
        var btn = event.target.closest('.kw-zoom');
        if (!btn) return;
        opener = btn;
        img.src = btn.dataset.src;
        img.alt = btn.getAttribute('aria-label') || '';
        cap.textContent = btn.dataset.caption || '';
        box.hidden = false;
        document.body.style.overflow = 'hidden';
        box.querySelector('.kw-close').focus();
    });
    box.addEventListener('click', function (event) {
        if (event.target === box || event.target.closest('.kw-close')) close();
    });
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && !box.hidden) close();
    });
})();
