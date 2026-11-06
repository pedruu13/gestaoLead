(function () {
    'use strict';

    const focusableSelector = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    let toastTimer;
    let confirmResolver;
    let previousFocus;

    function initClearableSearches(root = document) {
        root.querySelectorAll('input[data-clearable]').forEach(input => {
            if (input.dataset.clearReady === 'true') return;
            const parent = input.parentElement;
            parent.classList.add('ui-search');
            const clear = document.createElement('button');
            clear.type = 'button';
            clear.className = 'ui-search__clear';
            clear.setAttribute('aria-label', 'Limpar pesquisa');
            clear.innerHTML = '<span aria-hidden="true">×</span>';
            const refresh = () => { clear.hidden = !input.value; };
            clear.addEventListener('click', () => {
                input.value = '';
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
                input.focus();
                refresh();
            });
            input.addEventListener('input', refresh);
            parent.appendChild(clear);
            input.dataset.clearReady = 'true';
            refresh();
        });
    }

    function setButtonLoading(button, loading, label) {
        if (!button) return;
        if (loading) {
            button.dataset.originalHtml = button.innerHTML;
            button.disabled = true;
            button.setAttribute('aria-busy', 'true');
            button.innerHTML = `<span class="ui-button__spinner" aria-hidden="true"></span><span>${label || 'Processando...'}</span>`;
            return;
        }
        button.disabled = false;
        button.removeAttribute('aria-busy');
        if (button.dataset.originalHtml) button.innerHTML = button.dataset.originalHtml;
        delete button.dataset.originalHtml;
    }

    function showToast(message, type = 'success') {
        const toast = document.getElementById('app-toast');
        if (!toast) return;
        const text = document.getElementById('app-toast-text');
        const icon = document.getElementById('app-toast-icon');
        text.textContent = message;
        toast.dataset.type = type;
        icon.textContent = type === 'error' ? '!' : '✓';
        icon.className = type === 'error' ? 'text-rose-400 font-black' : 'text-blue-300 font-black';
        toast.classList.remove('hidden');
        requestAnimationFrame(() => toast.classList.add('is-visible'));
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => {
            toast.classList.remove('is-visible');
            setTimeout(() => toast.classList.add('hidden'), 220);
        }, 3500);
    }

    function closeConfirm(answer) {
        const modal = document.getElementById('app-confirm');
        if (!modal || !modal.classList.contains('is-open')) return;
        modal.classList.remove('is-open');
        modal.setAttribute('aria-hidden', 'true');
        document.body.style.overflow = '';
        setTimeout(() => modal.classList.add('hidden'), 220);
        if (previousFocus) previousFocus.focus();
        if (confirmResolver) confirmResolver(answer);
        confirmResolver = null;
    }

    function showConfirm({ title, message, confirmLabel = 'Confirmar', danger = false }) {
        return new Promise(resolve => {
            const modal = document.getElementById('app-confirm');
            const accept = document.getElementById('app-confirm-accept');
            const cancel = document.getElementById('app-confirm-cancel');
            previousFocus = document.activeElement;
            confirmResolver = resolve;
            document.getElementById('app-confirm-title').textContent = title;
            document.getElementById('app-confirm-text').textContent = message;
            accept.textContent = confirmLabel;
            accept.className = danger ? 'ui-button ui-button--danger' : 'ui-button ui-button--primary';
            modal.classList.remove('hidden');
            modal.setAttribute('aria-hidden', 'false');
            document.body.style.overflow = 'hidden';
            requestAnimationFrame(() => {
                modal.classList.add('is-open');
                accept.focus();
            });
            accept.onclick = () => closeConfirm(true);
            cancel.onclick = () => closeConfirm(false);
        });
    }

    function handleModalKeys(event) {
        const modal = document.getElementById('app-confirm');
        if (!modal || !modal.classList.contains('is-open')) return;
        if (event.key === 'Escape') {
            event.preventDefault();
            closeConfirm(false);
            return;
        }
        if (event.key !== 'Tab') return;
        const focusable = [...modal.querySelectorAll(focusableSelector)];
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }

    document.addEventListener('DOMContentLoaded', () => {
        initClearableSearches();
        document.querySelectorAll('[data-tooltip]').forEach(element => {
            if (!element.hasAttribute('aria-label')) element.setAttribute('aria-label', element.dataset.tooltip);
            if (!element.matches('button, a, input, select, textarea, [tabindex]')) element.tabIndex = 0;
        });
    });
    document.addEventListener('keydown', handleModalKeys);

    window.GestaoLeadUI = { initClearableSearches, setButtonLoading, showToast, showConfirm };
    window.showAppToast = showToast;
    window.showAppConfirm = showConfirm;
})();
