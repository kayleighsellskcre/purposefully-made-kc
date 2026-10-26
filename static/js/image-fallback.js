/* A design image that fails to load never leaves a blank tile: logo strips drop the tile, cards show the monogram. */
(function () {
    document.addEventListener('error', function (e) {
        var img = e.target;
        if (!img || img.tagName !== 'IMG' || img.getAttribute('data-fell-back')) { return; }
        var tile = img.closest('.group-order-showcase-item');
        if (tile) {
            tile.hidden = true;
            var strip = tile.parentElement;
            if (strip && !strip.querySelector('.group-order-showcase-item:not([hidden])')) { strip.hidden = true; }
            return;
        }
        if (img.closest('.logo-gallery-item, .dist-card-art, .org-card-art, .group-order-cover')) {
            img.setAttribute('data-fell-back', '1');
            img.classList.add('img-fallback');
            img.src = '/static/img/logo-monogram.png';
        }
    }, true);
})();
