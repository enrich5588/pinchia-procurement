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
  const update = () => {
    const checked = checkboxes.filter((checkbox) => checkbox.checked).length;
    buttons.forEach((button) => { button.disabled = checked === 0; });
    selectAll.checked = checked > 0 && checked === checkboxes.length;
    selectAll.indeterminate = checked > 0 && checked < checkboxes.length;
  };
  selectAll.addEventListener("change", () => {
    checkboxes.forEach((checkbox) => { checkbox.checked = selectAll.checked; });
    update();
  });
  checkboxes.forEach((checkbox) => checkbox.addEventListener("change", update));
  update();
})();
