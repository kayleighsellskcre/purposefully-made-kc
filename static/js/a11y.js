/* Shared accessibility behaviour for the whole site.
 *
 * Three things live here, all of which were missing and all of which would
 * otherwise have to be repeated in a dozen templates.
 *
 * 1. Keyboard activation for div-based controls.
 *    The colour cards, size cards and placement options on the customizer are
 *    <div onclick="...">. A div is not focusable and does not fire click on
 *    Enter, so none of those choices could be made without a mouse — a customer
 *    navigating by keyboard could not pick a colour, which meant they could not
 *    buy anything. Marking them role="button" tabindex="0" makes them
 *    reachable; this makes them activatable.
 *
 * 2. Keeping aria-pressed honest.
 *    Selection is shown by adding a `selected` or `active` class, in about a
 *    dozen places across customize.html alone. Rather than edit every one, watch
 *    for the class changing and mirror it onto aria-pressed, so what a screen
 *    reader announces always matches what is on screen.
 *
 * 3. A dialog helper (PMKC.dialog).
 *    The size chart and image zoom panels are plain divs toggled by display.
 *    They trap nobody, ignore Escape, and leave focus behind on the page under
 *    them. This adds Escape, focus containment, and returning focus to whatever
 *    opened the dialog.
 */
(function () {
    'use strict';

    /* ── 1. Enter/Space activate role="button" ─────────────────────────── */

    document.addEventListener('keydown', function (event) {
        if (event.key !== 'Enter' && event.key !== ' ' && event.key !== 'Spacebar') return;

        var el = event.target;
        if (!el || typeof el.closest !== 'function') return;

        var control = el.closest('[role="button"]');
        if (!control) return;

        // Native buttons and links already do this themselves.
        var tag = control.tagName;
        if (tag === 'BUTTON' || tag === 'A' || tag === 'INPUT' || tag === 'TEXTAREA') return;
        if (control.getAttribute('aria-disabled') === 'true') return;

        // Space scrolls the page by default, which is never what was wanted here.
        event.preventDefault();
        control.click();
    });

    /* ── 2. Mirror the selected class onto aria-pressed ────────────────── */

    var SELECTED_CLASSES = ['selected', 'active'];

    function syncPressed(el) {
        if (!el.hasAttribute('aria-pressed')) return;
        var on = SELECTED_CLASSES.some(function (name) {
            return el.classList.contains(name);
        });
        var next = on ? 'true' : 'false';
        if (el.getAttribute('aria-pressed') !== next) {
            el.setAttribute('aria-pressed', next);
        }
    }

    if (typeof MutationObserver === 'function') {
        var observer = new MutationObserver(function (records) {
            for (var i = 0; i < records.length; i++) {
                syncPressed(records[i].target);
            }
        });

        document.addEventListener('DOMContentLoaded', function () {
            var tracked = document.querySelectorAll('[aria-pressed]');
            for (var i = 0; i < tracked.length; i++) {
                syncPressed(tracked[i]);
                observer.observe(tracked[i], {
                    attributes: true,
                    attributeFilter: ['class'],
                });
            }
        });
    }

    /* ── 3. Dialogs ────────────────────────────────────────────────────── */

    var FOCUSABLE = [
        'a[href]',
        'button:not([disabled])',
        'input:not([disabled]):not([type="hidden"])',
        'select:not([disabled])',
        'textarea:not([disabled])',
        '[tabindex]:not([tabindex="-1"])',
    ].join(',');

    function focusableWithin(root) {
        return Array.prototype.filter.call(
            root.querySelectorAll(FOCUSABLE),
            function (el) {
                return el.offsetWidth > 0 || el.offsetHeight > 0 || el === document.activeElement;
            }
        );
    }

    /* One open dialog at a time is all this site needs. */
    var open = null;

    function onKeydown(event) {
        if (!open) return;

        if (event.key === 'Escape') {
            event.preventDefault();
            close();
            return;
        }

        if (event.key !== 'Tab') return;

        // Keep Tab inside the dialog; otherwise focus wanders onto the page
        // behind it, which a sighted keyboard user cannot see and a screen
        // reader user cannot escape.
        var items = focusableWithin(open.element);
        if (!items.length) {
            event.preventDefault();
            open.element.focus();
            return;
        }

        var first = items[0];
        var last = items[items.length - 1];
        var active = document.activeElement;

        if (event.shiftKey && (active === first || !open.element.contains(active))) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && active === last) {
            event.preventDefault();
            first.focus();
        }
    }

    function show(element, options) {
        if (open) close();

        var settings = options || {};
        element.setAttribute('role', element.getAttribute('role') || 'dialog');
        element.setAttribute('aria-modal', 'true');

        open = {
            element: element,
            returnFocusTo: document.activeElement,
            onClose: settings.onClose,
        };

        if (typeof settings.onOpen === 'function') {
            settings.onOpen();
        } else {
            element.style.display = settings.display || 'flex';
            element.removeAttribute('hidden');
        }

        var items = focusableWithin(element);
        if (items.length) {
            items[0].focus();
        } else {
            if (!element.hasAttribute('tabindex')) element.setAttribute('tabindex', '-1');
            element.focus();
        }

        document.addEventListener('keydown', onKeydown, true);
    }

    function close() {
        if (!open) return;
        var closing = open;
        open = null;

        document.removeEventListener('keydown', onKeydown, true);

        if (typeof closing.onClose === 'function') {
            closing.onClose();
        } else {
            closing.element.style.display = 'none';
        }

        // Send focus back where it came from, so the customer is not dumped at
        // the top of the page after closing a size chart.
        var target = closing.returnFocusTo;
        if (target && typeof target.focus === 'function' && document.contains(target)) {
            target.focus();
        }
    }

    function isOpen(element) {
        return !!open && (!element || open.element === element);
    }

    window.PMKC = window.PMKC || {};
    window.PMKC.dialog = {
        show: show,
        close: close,
        isOpen: isOpen,
    };
})();
