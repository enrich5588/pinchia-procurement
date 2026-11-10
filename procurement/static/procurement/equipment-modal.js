(() => {
  const dialog = document.querySelector("[data-equipment-modal]");
  if (!dialog) return;
  const body = dialog.querySelector("[data-equipment-modal-body]");
  let currentUrl = "";
  const bindContent = () => {
    window.bindEquipmentItems?.(body);
    const form = body.querySelector("[data-equipment-form]");
    if (!form) return;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!form.reportValidity()) return;
      const button = form.querySelector("button[type='submit']");
      button.disabled = true;
      try {
        const response = await fetch(form.action || currentUrl, {method:"POST", body:new FormData(form), headers:{"X-Requested-With":"XMLHttpRequest"}});
        if (response.ok) { window.location.reload(); return; }
        if ([409, 422].includes(response.status)) { body.innerHTML = await response.text(); bindContent(); return; }
        throw new Error("save failed");
      } catch (error) {
        body.insertAdjacentHTML("afterbegin", '<p class="supply-modal-error" role="alert">儲存失敗，請稍後再試。</p>');
        button.disabled = false;
      }
    });
  };
  const open = async (url) => {
    currentUrl = url; body.innerHTML = "<p>正在載入…</p>"; if (!dialog.open) dialog.showModal();
    try { const response = await fetch(url, {headers:{"X-Requested-With":"XMLHttpRequest"}}); if (!response.ok) throw new Error(); body.innerHTML = await response.text(); bindContent(); }
    catch (error) { body.innerHTML = '<p class="supply-modal-error">表單載入失敗，請關閉後再試。</p>'; }
  };
  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-equipment-modal-close]")) { if (dialog.open) dialog.close(); return; }
    const trigger = event.target.closest("[data-equipment-form-url]"); if (!trigger || trigger.closest("dialog")) return; event.preventDefault(); open(trigger.dataset.equipmentFormUrl);
  });
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
})();
