/*
 * Dark mode toggle (G12).
 *
 * The theme is stored in localStorage and applied to <html> as
 * data-bs-theme before first paint (see the inline snippet in
 * template.html) so there is no flash of the wrong theme. With no stored
 * preference the OS setting wins.
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'wger-theme';

    function apply(theme) {
        document.documentElement.setAttribute('data-bs-theme', theme);
    }

    function current() {
        return document.documentElement.getAttribute('data-bs-theme') || 'light';
    }

    function toggle() {
        var next = current() === 'dark' ? 'light' : 'dark';
        apply(next);
        try {
            localStorage.setItem(STORAGE_KEY, next);
        } catch (e) {
            // Private mode: the toggle still works for this page view
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        var button = document.getElementById('theme-toggle');
        if (!button) {
            return;
        }
        button.addEventListener('click', toggle);
    });
})();
