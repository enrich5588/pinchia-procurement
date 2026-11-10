(() => {
  const bindAssetForm = (root = document) => {
    const assetForm = root.querySelector("[data-asset-form]");
    const unitPriceInput = assetForm?.querySelector("[data-asset-unit-price]");
    const businessTaxInput = assetForm?.querySelector("[data-asset-business-tax]");
    const totalInput = assetForm?.querySelector("[data-asset-total]");
    if (unitPriceInput && businessTaxInput && totalInput && !totalInput.dataset.totalBound) {
      totalInput.dataset.totalBound = "true";
      const updateTotal = () => {
        const unitPrice = Number.parseFloat(unitPriceInput.value) || 0;
        const businessTax = Number.parseFloat(businessTaxInput.value) || 0;
        totalInput.value = (Math.round((unitPrice + businessTax + Number.EPSILON) * 100) / 100).toFixed(2);
      };
      unitPriceInput.addEventListener("input", updateTotal);
      businessTaxInput.addEventListener("input", updateTotal);
      updateTotal();
    }
    const imageInput = assetForm?.querySelector('input[name="images"]');
    const preview = assetForm?.querySelector("[data-image-preview]");
    if (imageInput && preview && !imageInput.dataset.previewBound) {
      imageInput.dataset.previewBound = "true";
      let previewUrls = [];
      imageInput.addEventListener("change", () => {
        previewUrls.forEach((url) => URL.revokeObjectURL(url));
        previewUrls = [];
        preview.replaceChildren();
        const files = Array.from(imageInput.files);
        const error = files.length > 10 ? "每次最多上傳 10 張圖片。" :
          files.some((file) => file.size > 5 * 1024 * 1024) ? "每張圖片不可超過 5 MB。" : "";
        imageInput.setCustomValidity(error);
        if (error) {
          preview.textContent = error;
          imageInput.reportValidity();
          return;
        }
        files.forEach((file) => {
          const item = document.createElement("figure");
          item.className = "asset-image-item";
          const img = document.createElement("img");
          img.src = URL.createObjectURL(file);
          img.addEventListener("load", () => URL.revokeObjectURL(img.src), {once: true});
          img.addEventListener("error", () => URL.revokeObjectURL(img.src), {once: true});
          previewUrls.push(img.src);
          img.alt = file.name;
          const caption = document.createElement("figcaption");
          caption.textContent = file.name;
          item.append(img, caption);
          preview.append(item);
        });
      });
    }
    const departmentInput = assetForm?.querySelector("[data-registration-department]");
    const custodianInput = assetForm?.querySelector("[data-registration-custodian]");
    const custodianOptionsUrl = assetForm?.dataset.custodianOptionsUrl;
    if (departmentInput && custodianInput && custodianOptionsUrl && !departmentInput.dataset.custodianBound) {
      departmentInput.dataset.custodianBound = "true";
      departmentInput.addEventListener("change", async () => {
        const previousValue = custodianInput.value;
        custodianInput.disabled = true;
        custodianInput.replaceChildren(new Option("正在載入保管人員…", ""));
        try {
          const url = new URL(custodianOptionsUrl, window.location.origin);
          url.searchParams.set("department", departmentInput.value);
          const response = await fetch(url, {headers: {"X-Requested-With": "XMLHttpRequest"}});
          if (!response.ok) throw new Error("custodian lookup failed");
          const result = await response.json();
          custodianInput.replaceChildren(new Option("部門資產（共用資源）", ""));
          result.custodians.forEach((custodian) => {
            const option = new Option(custodian.label, String(custodian.id));
            option.selected = String(custodian.id) === previousValue;
            custodianInput.add(option);
          });
        } catch (error) {
          custodianInput.replaceChildren(new Option("保管人員載入失敗，請重新選擇部門", ""));
        } finally {
          custodianInput.disabled = false;
        }
      });
    }
    if (!assetForm || assetForm.dataset.numberCheckBound) return;

    const numberInput = assetForm.querySelector("#id_asset_no");
    const numberStatus = assetForm.querySelector("[data-number-status]");
    const checkUrl = assetForm.dataset.numberCheckUrl;
    if (!numberInput || numberInput.disabled || !numberStatus || !checkUrl) return;

    assetForm.dataset.numberCheckBound = "true";
    let debounceTimer;
    let activeRequest;

    const updateStatus = (state, message) => {
      numberStatus.dataset.state = state;
      numberStatus.textContent = message;
    };

    const checkNumber = async () => {
      const assetNumber = numberInput.value.trim();
      activeRequest?.abort();
      numberInput.setCustomValidity("");

      if (!assetNumber) {
        updateStatus("", "");
        return;
      }

      activeRequest = new AbortController();
      updateStatus("checking", "正在檢查編號…");

      try {
        const url = new URL(checkUrl, window.location.origin);
        url.searchParams.set("asset_no", assetNumber);
        const response = await fetch(url, {
          headers: { "X-Requested-With": "XMLHttpRequest" },
          signal: activeRequest.signal,
        });
        if (!response.ok) throw new Error("number check failed");

        const result = await response.json();
        if (result.exists) {
          const message = "此財產編號已存在，請使用其他編號。";
          numberInput.setCustomValidity(message);
          updateStatus("duplicate", message);
        } else {
          numberInput.setCustomValidity("");
          updateStatus("available", "此財產編號可以使用。");
        }
      } catch (error) {
        if (error.name === "AbortError") return;
        numberInput.setCustomValidity("");
        updateStatus("error", "暫時無法檢查，送出時會再次驗證。");
      }
    };

    numberInput.addEventListener("input", () => {
      window.clearTimeout(debounceTimer);
      numberInput.setCustomValidity("");
      updateStatus("checking", numberInput.value.trim() ? "等待檢查…" : "");
      debounceTimer = window.setTimeout(checkNumber, 350);
    });

    numberInput.addEventListener("blur", () => {
      window.clearTimeout(debounceTimer);
      checkNumber();
    });
  };

  window.bindAssetForm = bindAssetForm;
  bindAssetForm();
})();
