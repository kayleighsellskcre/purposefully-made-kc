/* Select several items and delete them in one go. Boxes point at the bar's form with form="<id>". */
(function () {
    document.querySelectorAll('[data-bulk-bar]').forEach(function (bar) {
        var id = bar.id;
        var noun = bar.getAttribute('data-noun') || 'item';
        var count = bar.querySelector('[data-bulk-count]');
        var button = bar.querySelector('[data-bulk-delete]');
        function picks() { return Array.prototype.slice.call(document.querySelectorAll('input.bulk-pick[form="' + id + '"]')); }
        function chosen() { return picks().filter(function (p) { return p.checked && !p.disabled; }); }
        function plural(n) { return n + ' ' + noun + (n === 1 ? '' : 's'); }
        function update() {
            var n = chosen().length;
            count.textContent = n ? plural(n) + ' selected' : 'None selected';
            button.disabled = n === 0;
            button.textContent = n ? 'Delete ' + n + ' selected' : 'Delete selected';
        }
        bar.querySelectorAll('[data-bulk-select]').forEach(function (b) {
            b.addEventListener('click', function () {
                var which = b.getAttribute('data-bulk-select');
                picks().forEach(function (p) {
                    if (p.disabled) { return; }
                    p.checked = which === 'all' || (which !== 'none' && p.getAttribute('data-kind') === which);
                });
                update();
            });
        });
        document.addEventListener('change', function (e) {
            if (e.target && e.target.matches && e.target.matches('input.bulk-pick[form="' + id + '"]')) { update(); }
        });
        bar.addEventListener('submit', function (e) {
            var names = chosen().map(function (p) { return p.getAttribute('data-name') || ''; }).filter(Boolean);
            if (!names.length) { e.preventDefault(); return; }
            var shown = names.slice(0, 6).join(', ') + (names.length > 6 ? ' and ' + (names.length - 6) + ' more' : '');
            var message = 'Delete ' + plural(names.length) + '?\n\n' + shown +
                '\n\nAnything with orders or sign-ups is not erased. It is turned off and kept.';
            if (!window.confirm(message)) { e.preventDefault(); }
        });
        update();
    });
})();
