(() => {
  const mainDialog = document.querySelector("[data-approval-main-modal]");
  const mainBody = document.querySelector("[data-approval-main-body]");
  const decisionDialog = document.querySelector("[data-approval-decision-modal]");
  const decisionBody = document.querySelector("[data-approval-decision-body]");
  const withdrawDialog = document.querySelector("[data-approval-withdraw-confirm]");
  const withdrawForm = document.querySelector("[data-approval-withdraw-form]");
  const withdrawCase = document.querySelector("[data-approval-withdraw-case]");

  const openDialog = (dialog) => { if (dialog && !dialog.open) dialog.showModal(); };

  const bindRoutePreview = (container) => {
    const inputs = [...container.querySelectorAll("input[name='amount_range']")];
    const output = container.querySelector("[data-approval-route]");
    const rulesNode = container.querySelector("#approval-route-rules");
    if (!inputs.length || !output || !rulesNode) return;
    const rules = JSON.parse(rulesNode.textContent);
    const update = () => {
      const selected = inputs.find((input) => input.checked);
      if (!selected) output.textContent = "請選擇涉及金額";
      else {
        const rule = rules.find((item) => item.value === selected.value);
        output.textContent = rule ? rule.route : "找不到適用的簽核路徑";
      }
    };
    inputs.forEach((input) => input.addEventListener("change", update)); update();
  };

  const submitModalForm = (form, body, bind) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = form.querySelector("button[type='submit']");
      button.disabled = true;
      try {
        const response = await fetch(form.action, {
          method: "POST", body: new FormData(form),
          headers: {"X-Requested-With": "XMLHttpRequest"},
        });
        if (response.ok) {
          const result = await response.json();
          window.location.assign(result.redirect_url); return;
        }
        if ([409, 422].includes(response.status)) {
          body.innerHTML = await response.text(); bind(body); return;
        }
        throw new Error();
      } catch (error) {
        body.insertAdjacentHTML("afterbegin", '<p class="approval-form-error">操作失敗，請稍後再試。</p>');
        button.disabled = false;
      }
    });
  };

  const bindCreate = (container) => {
    bindRoutePreview(container);
    const form = container.querySelector("[data-approval-form]");
    if (form) submitModalForm(form, mainBody, bindCreate);
  };
  const bindDecision = (container) => {
    const form = container.querySelector("[data-approval-decision-form]");
    if (form) submitModalForm(form, decisionBody, bindDecision);
  };

  const load = async (dialog, body, url, bind) => {
    body.innerHTML = "<p>正在載入…</p>"; openDialog(dialog);
    try {
      const response = await fetch(url, {headers: {"X-Requested-With": "XMLHttpRequest"}});
      if (!response.ok) throw new Error();
      body.innerHTML = await response.text(); bind?.(body);
    } catch (error) {
      body.innerHTML = '<p class="approval-form-error">內容載入失敗，請關閉後再試。</p>';
    }
  };

  document.addEventListener("click", (event) => {
    const create = event.target.closest("[data-approval-create-url]");
    if (create) { load(mainDialog, mainBody, create.dataset.approvalCreateUrl, bindCreate); return; }
    const detail = event.target.closest("[data-approval-detail-url]");
    if (detail) { load(mainDialog, mainBody, detail.dataset.approvalDetailUrl); return; }
    const decision = event.target.closest("[data-approval-decision-url]");
    if (decision) { event.preventDefault(); load(decisionDialog, decisionBody, decision.dataset.approvalDecisionUrl, bindDecision); return; }
    const withdraw = event.target.closest("[data-approval-withdraw-url]");
    if (withdraw) {
      withdrawForm.action = withdraw.dataset.approvalWithdrawUrl;
      withdrawCase.textContent = withdraw.dataset.approvalCaseNo;
      openDialog(withdrawDialog); return;
    }
    if (event.target.closest("[data-approval-modal-close]")) mainDialog?.close();
    if (event.target.closest("[data-approval-decision-close]")) decisionDialog?.close();
    if (event.target.closest("[data-approval-withdraw-close]")) withdrawDialog?.close();
  });
  for (const dialog of [mainDialog, decisionDialog, withdrawDialog]) {
    dialog?.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  }
  bindRoutePreview(document);
})();
