/* District admin: search boxes for the style list, the color grid and the color picks. */
(function () {
    function norm(s) { return (s || '').toLowerCase().trim(); }
    document.querySelectorAll('input[data-filter]').forEach(function (box) {
        var sel = box.getAttribute('data-filter');
        box.addEventListener('input', function () {
            var q = norm(box.value);
            document.querySelectorAll(sel).forEach(function (row) {
                var text = norm(row.getAttribute('data-label') || row.textContent);
                row.hidden = !!q && text.indexOf(q) === -1;
            });
        });
    });
    document.querySelectorAll('input[data-filter-cols]').forEach(function (box) {
        var table = document.querySelector(box.getAttribute('data-filter-cols'));
        if (!table) { return; }
        box.addEventListener('input', function () {
            var q = norm(box.value);
            table.querySelectorAll('[data-label]').forEach(function (cell) {
                cell.hidden = !!q && cell.getAttribute('data-label').indexOf(q) === -1;
            });
        });
    });
})();
