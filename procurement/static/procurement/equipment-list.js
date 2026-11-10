(() => {
  const dialog = document.querySelector("[data-equipment-confirm]");
  if (dialog) {
    const form = dialog.querySelector("[data-equipment-cancel-form]"); const label = dialog.querySelector("[data-equipment-case]");
    document.addEventListener("click", (event) => {
      const trigger = event.target.closest("[data-equipment-cancel-url]");
      if (trigger) { form.action = trigger.dataset.equipmentCancelUrl; label.textContent = trigger.dataset.equipmentCaseNo; dialog.showModal(); }
      if (event.target.closest("[data-equipment-confirm-close]")) dialog.close();
    });
    dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  }
  const completeDialog = document.querySelector("[data-equipment-complete-confirm]");
  const completeForm = completeDialog?.querySelector("[data-equipment-complete-form]");
  const completeCase = completeDialog?.querySelector("[data-equipment-complete-case]");
  const completeCaseWrap = completeDialog?.querySelector("[data-equipment-complete-case-wrap]");
  let bulkCompleteForm = null;
  if (completeDialog) {
    document.addEventListener("click", (event) => {
      const single = event.target.closest("[data-equipment-complete-url]");
      if (single) {
        bulkCompleteForm = null;
        completeForm.action = single.dataset.equipmentCompleteUrl;
        completeCase.textContent = single.dataset.equipmentCaseNo;
        completeCaseWrap.hidden = false;
        completeDialog.showModal();
        return;
      }
      const bulk = event.target.closest("[data-equipment-bulk-complete-url]");
      if (bulk) {
        bulkCompleteForm = document.querySelector("#equipment-bulk-form");
        completeForm.action = "";
        completeCase.textContent = "";
        completeCaseWrap.hidden = true;
        completeDialog.showModal();
        return;
      }
      if (event.target.closest("[data-equipment-complete-close]")) completeDialog.close();
    });
    completeForm.addEventListener("submit", (event) => {
      if (!bulkCompleteForm) return;
      event.preventDefault();
      bulkCompleteForm.action = document.querySelector("[data-equipment-bulk-complete-url]").dataset.equipmentBulkCompleteUrl;
      bulkCompleteForm.submit();
    });
    completeDialog.addEventListener("click", (event) => { if (event.target === completeDialog) completeDialog.close(); });
  }
  const checkboxes = [...document.querySelectorAll("[data-equipment-bulk-checkbox]")];
  const selectAll = document.querySelector("[data-equipment-select-all]");
  const buttons = [...document.querySelectorAll("[data-equipment-bulk-submit]")];
  if (!selectAll) return;
  const update = () => {
    const checked = checkboxes.filter((checkbox) => checkbox.checked).length;
    buttons.forEach((button) => { button.disabled = checked === 0; });
    selectAll.checked = checked > 0 && checked === checkboxes.length;
    selectAll.indeterminate = checked > 0 && checked < checkboxes.length;
  };
  selectAll.addEventListener("change", () => { checkboxes.forEach((checkbox) => { checkbox.checked = selectAll.checked; }); update(); });
  checkboxes.forEach((checkbox) => checkbox.addEventListener("change", update));
  update();
})();
