(() => {
  'use strict';
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-password-toggle]');
    if (!button || button.disabled) return;
    const input = document.getElementById(button.dataset.passwordToggle);
    if (!input || !['password', 'text'].includes(input.type)) return;
    const visible = input.type === 'password';
    input.type = visible ? 'text' : 'password';
    button.textContent = visible ? '隱藏密碼' : '顯示密碼';
    button.setAttribute('aria-pressed', String(visible));
  });
})();
