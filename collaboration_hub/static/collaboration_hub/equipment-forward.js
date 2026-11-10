(() => {
  const dialog = document.querySelector("[data-collaboration-forward-modal]");
  if (!dialog) return;
  const body = dialog.querySelector("[data-collaboration-forward-body]");
  const bindForm = () => {
    const form = body.querySelector("[data-collaboration-forward-form]");
    if (!form) return;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!form.reportValidity()) return;
      const submit = form.querySelector("button[type='submit']");
      submit.disabled = true;
      try {
        const response = await fetch(form.action, {method:"POST", body:new FormData(form), headers:{"X-Requested-With":"XMLHttpRequest"}});
        if (response.ok) { window.location.reload(); return; }
        if (response.status === 422) { body.innerHTML = await response.text(); bindForm(); return; }
        throw new Error("forward failed");
      } catch (error) {
        body.insertAdjacentHTML("afterbegin", '<p class="collaboration-forward-error" role="alert">轉發失敗，請稍後再試。</p>');
        submit.disabled = false;
      }
    });
  };
  const open = async (url) => {
    body.innerHTML = "<p>正在載入…</p>";
    if (!dialog.open) dialog.showModal();
    try {
      const response = await fetch(url, {headers:{"X-Requested-With":"XMLHttpRequest"}});
      if (!response.ok) throw new Error("load failed");
      body.innerHTML = await response.text(); bindForm();
    } catch (error) { body.innerHTML = '<p class="collaboration-forward-error">轉發表單載入失敗，請關閉後再試。</p>'; }
  };
  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-collaboration-forward-url]");
    if (trigger) { event.preventDefault(); open(trigger.dataset.collaborationForwardUrl); return; }
    if (event.target.closest("[data-collaboration-forward-close]")) dialog.close();
  });
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
})();
