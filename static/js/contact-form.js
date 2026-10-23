/* Contact form: show an order number box for order questions, and a pointer for custom designs. */
(function () {
    var subject = document.getElementById('subject');
    var order = document.getElementById('orderNumberGroup');
    var hint = document.getElementById('customDesignHint');
    if (!subject) return;
    function sync() {
        if (order) order.hidden = subject.value !== 'Order question';
        if (hint) hint.hidden = subject.value !== 'Custom design';
    }
    subject.addEventListener('change', sync);
    sync();
})();
