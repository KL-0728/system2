(() => {
  document.querySelectorAll('[data-local-time]').forEach((node) => {
    const value = new Date(node.dataset.localTime);
    if (!Number.isNaN(value.getTime())) node.textContent = value.toLocaleString('zh-TW', {
      timeZone: 'Asia/Taipei', hour12: false,
    });
  });
})();
