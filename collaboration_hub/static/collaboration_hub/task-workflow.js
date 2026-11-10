(() => {
  const taskDialog = document.querySelector("[data-collaboration-task-modal]");
  const taskBody = taskDialog?.querySelector("[data-collaboration-task-body]");
  const returnDialog = document.querySelector("[data-collaboration-return-modal]");
  const returnBody = returnDialog?.querySelector("[data-collaboration-return-body]");
  const withdrawDialog = document.querySelector("[data-collaboration-withdraw-confirm]");
  const withdrawForm = withdrawDialog?.querySelector("[data-collaboration-withdraw-form]");
  const withdrawCase = withdrawDialog?.querySelector("[data-collaboration-withdraw-case]");
  const loadInto = async (dialog, body, url, bind) => {
    body.innerHTML = "<p>正在載入…</p>"; if (!dialog.open) dialog.showModal();
    try { const response = await fetch(url, {headers:{"X-Requested-With":"XMLHttpRequest"}}); if (!response.ok) throw new Error(); body.innerHTML = await response.text(); bind?.(); }
    catch (error) { body.innerHTML = '<p class="collaboration-forward-error">內容載入失敗，請關閉後再試。</p>'; }
  };
  const bindReturnForm = () => {
    const form = returnBody.querySelector("[data-collaboration-return-form]");
    if (!form) return;
    form.addEventListener("submit", async (event) => {
      event.preventDefault(); const submit = form.querySelector("button[type='submit']"); submit.disabled = true;
      try {
        const response = await fetch(form.action, {method:"POST", body:new FormData(form), headers:{"X-Requested-With":"XMLHttpRequest"}});
        if (response.ok) { window.location.reload(); return; }
        if ([409, 422].includes(response.status)) { returnBody.innerHTML = await response.text(); bindReturnForm(); return; }
        throw new Error();
      } catch (error) { returnBody.insertAdjacentHTML("afterbegin", '<p class="collaboration-forward-error">退回失敗，請稍後再試。</p>'); submit.disabled = false; }
    });
  };
  document.addEventListener("click", (event) => {
    const detail = event.target.closest("[data-collaboration-detail-url]");
    if (detail) { event.preventDefault(); loadInto(taskDialog, taskBody, detail.dataset.collaborationDetailUrl); return; }
    const returnButton = event.target.closest("[data-collaboration-return-url]");
    if (returnButton) { loadInto(returnDialog, returnBody, returnButton.dataset.collaborationReturnUrl, bindReturnForm); return; }
    const withdraw = event.target.closest("[data-collaboration-withdraw-url]");
    if (withdraw) { withdrawForm.action = withdraw.dataset.collaborationWithdrawUrl; withdrawCase.textContent = withdraw.dataset.collaborationCaseNo; withdrawDialog.showModal(); return; }
    if (event.target.closest("[data-collaboration-task-close]")) taskDialog.close();
    if (event.target.closest("[data-collaboration-return-close]")) returnDialog.close();
    if (event.target.closest("[data-collaboration-withdraw-close]")) withdrawDialog.close();
  });
  taskDialog?.addEventListener("click", (event) => { if (event.target === taskDialog) taskDialog.close(); });
  returnDialog?.addEventListener("click", (event) => { if (event.target === returnDialog) returnDialog.close(); });
  withdrawDialog?.addEventListener("click", (event) => { if (event.target === withdrawDialog) withdrawDialog.close(); });
})();
