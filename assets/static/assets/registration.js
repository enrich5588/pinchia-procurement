(() => {
  const dialog = document.querySelector("[data-registration-confirm]");
  if (!dialog) return;
  const form = dialog.querySelector("[data-registration-cancel-form]");
  const caseLabel = dialog.querySelector("[data-registration-case]");
  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-registration-cancel-url]");
    if (trigger) {
      form.action = trigger.dataset.registrationCancelUrl;
      caseLabel.textContent = trigger.dataset.registrationCaseNo;
      dialog.showModal();
    }
    if (event.target.closest("[data-registration-confirm-close]")) dialog.close();
  });
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
})();

(() => {
  const checkboxes = [...document.querySelectorAll("[data-bulk-checkbox]")];
  const selectAll = document.querySelector("[data-bulk-select-all]");
  const buttons = [...document.querySelectorAll("[data-bulk-submit]")];
  if (!selectAll) return;
  const shown = () => checkboxes.filter((checkbox) => !checkbox.closest("tr")?.hidden);
  const update = () => {
    const visible = shown();
    const checked = visible.filter((checkbox) => checkbox.checked).length;
    buttons.forEach((button) => { button.disabled = checked === 0; });
    selectAll.checked = visible.length > 0 && checked === visible.length;
    selectAll.indeterminate = checked > 0 && checked < visible.length;
    const bar = document.querySelector("[data-bulk-bar]");
    if (bar) bar.hidden = checked === 0;
    const count = document.querySelector("[data-bulk-count]");
    if (count) count.textContent = `已選取 ${checked} 筆`;
  };
  selectAll.addEventListener("change", () => {
    shown().forEach((checkbox) => { checkbox.checked = selectAll.checked; });
    update();
  });
  checkboxes.forEach((checkbox) => checkbox.addEventListener("change", update));
  update();
})();
