(() => {
  const dialog = document.querySelector("[data-asset-modal]");
  if (!dialog) return;

  const modalBody = dialog.querySelector("[data-modal-body]");
  let currentUrl = "";

  const bindModalContent = () => {
    window.bindAssetForm?.(modalBody);
    const form = modalBody.querySelector("[data-asset-form]");
    if (!form) return;

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!form.reportValidity()) return;

      const submitButton = form.querySelector("button[type='submit']");
      submitButton.disabled = true;
      submitButton.textContent = "儲存中…";

      try {
        const response = await fetch(form.action || currentUrl, {
          method: "POST",
          body: new FormData(form),
          headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        if (response.ok) {
          await response.json();
          window.location.reload();
          return;
        }
        if ([409, 422].includes(response.status)) {
          const selectedFiles = form.querySelector('input[name="images"]')?.files;
          modalBody.innerHTML = await response.text();
          bindModalContent();
          const imageInput = modalBody.querySelector('input[name="images"]');
          if (imageInput && selectedFiles?.length) {
            imageInput.files = selectedFiles;
            imageInput.dispatchEvent(new Event("change"));
          }
          return;
        }
        throw new Error("asset save failed");
      } catch (error) {
        modalBody.insertAdjacentHTML(
          "afterbegin",
          '<p class="asset-modal-error" role="alert">儲存失敗，請稍後再試。</p>'
        );
        submitButton.disabled = false;
        submitButton.textContent = "重新儲存";
      }
    });
  };

  const openModal = async (url) => {
    currentUrl = url;
    modalBody.innerHTML = '<p class="asset-modal-loading">正在載入表單…</p>';
    if (!dialog.open) dialog.showModal();

    try {
      const response = await fetch(url, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (!response.ok) throw new Error("asset form load failed");
      modalBody.innerHTML = await response.text();
      bindModalContent();
      modalBody.querySelector("input:not([disabled]), select, textarea")?.focus();
    } catch (error) {
      modalBody.innerHTML = '<p class="asset-modal-error" role="alert">表單載入失敗，請關閉後再試。</p>';
    }
  };

  document.addEventListener("click", (event) => {
    if (event.target.closest(".asset-image-thumbnails a")) return;
    const closeButton = event.target.closest("[data-modal-close]");
    if (closeButton && dialog.open) {
      dialog.close();
      return;
    }

    const trigger = event.target.closest("[data-asset-form-url]");
    if (!trigger) return;
    event.preventDefault();
    openModal(trigger.dataset.assetFormUrl);
  });

  document.addEventListener("keydown", (event) => {
    if (event.target.closest(".asset-image-thumbnails a")) return;
    const trigger = event.target.closest(".asset-clickable-row[data-asset-form-url]");
    if (!trigger || !["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    openModal(trigger.dataset.assetFormUrl);
  });

  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
})();
