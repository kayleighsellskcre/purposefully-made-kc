/* Long intro text shows two lines with a "Read more" link. Short text is left alone. */
(function () {
    document.querySelectorAll('[data-readmore]').forEach(function (el) {
        el.classList.add('rm-clamp');
        if (el.scrollHeight <= el.clientHeight + 2) { el.classList.remove('rm-clamp'); return; }
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'rm-toggle';
        btn.textContent = 'Read more';
        btn.setAttribute('aria-expanded', 'false');
        btn.addEventListener('click', function () {
            var open = el.classList.toggle('rm-clamp') === false;
            btn.textContent = open ? 'Show less' : 'Read more';
            btn.setAttribute('aria-expanded', open ? 'true' : 'false');
        });
        el.insertAdjacentElement('afterend', btn);
    });
})();
