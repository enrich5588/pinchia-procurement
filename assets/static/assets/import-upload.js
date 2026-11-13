(() => {
  document.querySelectorAll('[data-upload-drop]').forEach(zone => {
    const input = zone.querySelector('input[type="file"]');
    const filename = zone.querySelector('[data-upload-filename]');
    const error = zone.parentElement.querySelector('[data-upload-error]');
    if (!input) return;
    const update = () => {
      const file = input.files[0];
      const message = file && !file.name.toLowerCase().endsWith('.xlsx') ? '僅支援 .xlsx 格式的 Excel 檔案。' :
        file && file.size > 150 * 1024 * 1024 ? 'Excel 檔案不可超過 150 MB。' : '';
      filename.textContent = file ? `已選擇：${file.name}` : '尚未選擇檔案';
      error.textContent = message;
      input.setCustomValidity(message);
    };
    input.addEventListener('change', update);
    zone.addEventListener('keydown', event => {
      if (event.target === zone && ['Enter', ' '].includes(event.key)) {
        event.preventDefault(); input.click();
      }
    });
    ['dragenter','dragover'].forEach(name => zone.addEventListener(name, event => {
      event.preventDefault(); zone.classList.add('is-dragging');
    }));
    zone.addEventListener('dragleave', event => {
      if (!zone.contains(event.relatedTarget)) zone.classList.remove('is-dragging');
    });
    zone.addEventListener('drop', event => {
      event.preventDefault(); zone.classList.remove('is-dragging');
      if (event.dataTransfer.files.length !== 1) {
        error.textContent = '一次只能上傳一個 Excel 檔案。'; return;
      }
      input.files = event.dataTransfer.files; update();
    });
  });
})();
