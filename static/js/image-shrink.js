/* Shrink photos in the browser before they are uploaded.
 *
 * Why: /shop/group-orders/create returned 413 Request Entity Too Large four
 * times in production. That form takes a cover photo plus any number of design
 * files, and a few untouched phone photos clear the 50 MB request limit on
 * their own. Nothing was resizing them, so the upload died before Flask ever
 * saw it and the organizer lost everything they had typed.
 *
 * Two ways in.
 *
 * 1. Declarative, for a file input that is submitted with its form:
 *        <input type="file" name="cover_image" data-shrink="1400">
 *    The value is the longest edge in pixels (default 1800, matching the design
 *    request form). Shrinking happens on change; if the form is submitted while
 *    that is still running, the submit waits rather than sending the originals.
 *
 * 2. Direct, for a file that JavaScript uploads itself:
 *        PMKC.shrinkImage(file).then(function (smaller) { ... })
 *    The group-order design picker posts each file to /design/upload, which
 *    refuses anything over 15 MB, so it shrinks first.
 *
 * PNGs stay PNG so transparent artwork does not flatten to a black box.
 * Anything the canvas cannot decode is passed through untouched — the server
 * still enforces its own type and size limits.
 */
(function () {
    'use strict';

    var DEFAULT_MAX_EDGE = 1800;
    var JPEG_QUALITY = 0.88;
    // Below this there is nothing worth doing, and re-encoding a small PNG can
    // make it bigger.
    var SKIP_UNDER_BYTES = 400 * 1024;

    var supported = (
        typeof DataTransfer !== 'undefined' &&
        typeof File === 'function' &&
        !!document.createElement('canvas').toBlob
    );

    function isShrinkable(file) {
        return /^image\/(png|jpe?g|webp|gif|heic|heif)$/i.test(file.type || '');
    }

    function loadImage(file) {
        return new Promise(function (resolve, reject) {
            var url = URL.createObjectURL(file);
            var img = new Image();
            img.onload = function () {
                URL.revokeObjectURL(url);
                resolve(img);
            };
            img.onerror = function () {
                URL.revokeObjectURL(url);
                reject(new Error('could not decode ' + file.name));
            };
            img.src = url;
        });
    }

    function shrinkOne(file, maxEdge) {
        if (!isShrinkable(file)) return Promise.resolve(file);
        if (file.size < SKIP_UNDER_BYTES) return Promise.resolve(file);

        return loadImage(file).then(function (img) {
            var w = img.naturalWidth || img.width;
            var h = img.naturalHeight || img.height;
            if (!w || !h) return file;

            var scale = Math.min(1, maxEdge / Math.max(w, h));
            var targetW = Math.max(1, Math.round(w * scale));
            var targetH = Math.max(1, Math.round(h * scale));

            var keepAlpha = /png$/i.test(file.type);
            // A HEIC or an already-large JPEG still benefits from re-encoding
            // even when it needs no resizing at all.
            if (scale === 1 && keepAlpha) return file;

            var canvas = document.createElement('canvas');
            canvas.width = targetW;
            canvas.height = targetH;
            var ctx = canvas.getContext('2d');
            if (!keepAlpha) {
                // Flatten onto white; a JPEG has no alpha and would otherwise
                // render transparent pixels as black.
                ctx.fillStyle = '#ffffff';
                ctx.fillRect(0, 0, targetW, targetH);
            }
            ctx.drawImage(img, 0, 0, targetW, targetH);

            var mime = keepAlpha ? 'image/png' : 'image/jpeg';
            var ext = keepAlpha ? '.png' : '.jpg';

            return new Promise(function (resolve) {
                canvas.toBlob(function (blob) {
                    if (!blob || blob.size >= file.size) {
                        resolve(file);
                        return;
                    }
                    var name = file.name.replace(/\.[^.]+$/, '') + ext;
                    resolve(new File([blob], name, {
                        type: mime,
                        lastModified: Date.now(),
                    }));
                }, mime, JPEG_QUALITY);
            });
        }).catch(function () {
            return file;
        });
    }

    function replaceFiles(input, files) {
        var dt = new DataTransfer();
        files.forEach(function (f) { dt.items.add(f); });
        input.files = dt.files;
    }

    /* Pending shrink work, keyed by the form element, so a submit can wait. */
    var pending = new WeakMap();

    function track(form, promise) {
        if (!form) return promise;
        var list = pending.get(form) || [];
        list.push(promise);
        pending.set(form, list);
        promise.then(function () {
            var current = pending.get(form) || [];
            var i = current.indexOf(promise);
            if (i >= 0) current.splice(i, 1);
            pending.set(form, current);
        });
        return promise;
    }

    function attach(input) {
        var maxEdge = parseInt(input.getAttribute('data-shrink'), 10) || DEFAULT_MAX_EDGE;
        var form = input.form;

        input.addEventListener('change', function () {
            var originals = Array.prototype.slice.call(input.files || []);
            if (!originals.length) return;

            var work = Promise.all(originals.map(function (f) {
                return shrinkOne(f, maxEdge);
            })).then(function (shrunk) {
                // The selection may have changed while we were working.
                var current = Array.prototype.slice.call(input.files || []);
                var sameSelection = (
                    current.length === originals.length &&
                    current.every(function (f, i) { return f === originals[i]; })
                );
                if (!sameSelection) return;
                if (shrunk.some(function (f, i) { return f !== originals[i]; })) {
                    replaceFiles(input, shrunk);
                    input.dispatchEvent(new CustomEvent('imageshrink', {
                        bubbles: true,
                        detail: { files: shrunk },
                    }));
                }
            });

            track(form, work);
        });
    }

    function guardSubmit(form) {
        form.addEventListener('submit', function (event) {
            var outstanding = pending.get(form) || [];
            if (!outstanding.length || form.dataset.shrinkReady === '1') return;
            event.preventDefault();
            event.stopImmediatePropagation();
            Promise.all(outstanding).then(function () {
                form.dataset.shrinkReady = '1';
                if (typeof form.requestSubmit === 'function') {
                    form.requestSubmit();
                } else {
                    form.submit();
                }
            });
        // Capture, so this runs before the page's own submit handlers (which
        // disable the button and would otherwise leave it stuck).
        }, true);
    }

    document.addEventListener('DOMContentLoaded', function () {
        if (!supported) return;
        var inputs = document.querySelectorAll('input[type="file"][data-shrink]');
        if (!inputs.length) return;
        var forms = new Set();
        Array.prototype.forEach.call(inputs, function (input) {
            attach(input);
            if (input.form) forms.add(input.form);
        });
        forms.forEach(guardSubmit);
    });

    window.PMKC = window.PMKC || {};

    /* Resolve to a smaller File, or to the original if shrinking is impossible
     * or would not help. Never rejects — the caller should upload something. */
    window.PMKC.shrinkImage = function (file, maxEdge) {
        if (!supported || !file) return Promise.resolve(file);
        return shrinkOne(file, maxEdge || DEFAULT_MAX_EDGE);
    };
})();
