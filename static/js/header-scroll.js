/* The PM badge hangs below the header at the top of a page. Once you scroll, it tucks into the
   header bar so it never sits on top of what you are reading. */
(function () {
    var nav = document.querySelector('.navbar');
    if (!nav) return;
    var ticking = false;
    function update() {
        var y = window.scrollY || document.documentElement.scrollTop || 0;
        if (y > 36) nav.classList.add('is-scrolled');
        else if (y < 10) nav.classList.remove('is-scrolled');
        ticking = false;
    }
    window.addEventListener('scroll', function () {
        if (!ticking) { ticking = true; window.requestAnimationFrame(update); }
    }, { passive: true });
    update();
})();
