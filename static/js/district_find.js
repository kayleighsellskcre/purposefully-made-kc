/* Find your school: filters the cards as you type, lists matches, and Enter opens the first one. */
(function () {
    var input = document.getElementById('distFind');
    if (!input) { return; }
    var list = document.getElementById('distFindList');
    var none = document.getElementById('distNone');
    var cards = Array.prototype.slice.call(document.querySelectorAll('.dist-school-card'));
    var levels = Array.prototype.slice.call(document.querySelectorAll('[data-level]'));
    function norm(s) { return (s || '').toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim(); }
    function matches(card, q) {
        return norm(card.getAttribute('data-school') + ' ' + card.getAttribute('data-mascot')).indexOf(q) !== -1;
    }
    function run() {
        var q = norm(input.value);
        var hits = [];
        cards.forEach(function (card) {
            var ok = !q || matches(card, q);
            card.hidden = !ok;
            if (ok && q) { hits.push(card); }
        });
        levels.forEach(function (level) {
            level.hidden = !level.querySelector('.dist-school-card:not([hidden])');
        });
        if (none) { none.hidden = !q || hits.length > 0; }
        list.innerHTML = '';
        hits.slice(0, 6).forEach(function (card) {
            var li = document.createElement('li');
            var a = document.createElement('a');
            a.href = card.getAttribute('href');
            a.textContent = card.getAttribute('data-school');
            li.appendChild(a);
            list.appendChild(li);
        });
        list.hidden = !hits.length;
    }
    input.addEventListener('input', run);
    input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
            var first = list.querySelector('a');
            if (first) { e.preventDefault(); window.location.href = first.href; }
        }
    });
})();
