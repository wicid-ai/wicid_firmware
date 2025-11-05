// Utility: tiny timeout wrapper
async function withTimeout(promise, ms = 5000) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error('scan_timeout')), ms))
  ]);
}

document.addEventListener('DOMContentLoaded', () => {
  const pageData = window.WICID_PAGE_DATA || {};
  const initialSettings = pageData.settings || {};
  const initialSsid = (initialSettings.ssid || '').trim();
  const initialPassword = initialSettings.password || '';
  const initialZip = initialSettings.zip_code || '';
  const lastErrorMessage = typeof pageData.error === 'string'
    ? pageData.error
    : (pageData.error && typeof pageData.error === 'object' && 'message' in pageData.error)
      ? pageData.error.message
      : '';
  const lastErrorField = pageData.error && typeof pageData.error === 'object' && 'field' in pageData.error
    ? pageData.error.field
    : null;

  const banner = document.querySelector('.banner');
  const ssidSelect = document.getElementById('ssid');
  const ssidManualWrapper = document.getElementById('ssidManualWrapper');
  const ssidManual = document.getElementById('ssid-manual');
  const passwordInput = document.getElementById('password');
  const zipInput = document.getElementById('zip_code');

  const setupForm = document.getElementById('setupForm');
  const errorContainer = document.getElementById('errorContainer');
  const saveButton = document.getElementById('saveButton');
  const buttonText = saveButton?.querySelector('.button-text');
  const buttonLoader = saveButton?.querySelector('.button-loader');

  const successState = document.getElementById('successState');
  const setupState = document.getElementById('setupState');
  const restartNowButton = document.getElementById('restartNowButton');

  const passwordToggle = document.getElementById('passwordToggle');
  const passwordToggleIconShow = passwordToggle?.querySelector('.password-toggle-icon-show');
  const passwordToggleIconHide = passwordToggle?.querySelector('.password-toggle-icon-hide');
  const systemDetailsToggle = document.getElementById('systemDetailsToggle');
  const systemDetailsContent = document.getElementById('systemDetailsContent');

  let initialSsidApplied = false;
  let systemInfoLoaded = false;
  let systemInfoLoading = false;
  let currentErrorField = null;

  if (passwordInput && initialPassword) passwordInput.value = initialPassword;
  if (zipInput && initialZip) zipInput.value = initialZip;
  if (ssidManual && initialSsid) ssidManual.value = initialSsid;

  if (lastErrorMessage) {
    showError(lastErrorMessage, lastErrorField);
  }

  if (passwordToggle) {
    passwordToggle.addEventListener('click', () => {
      if (!passwordInput) return;
      const wasPassword = passwordInput.type === 'password';
      passwordInput.type = wasPassword ? 'text' : 'password';
      updatePasswordToggleState();
      passwordInput.focus({ preventScroll: true });
    });
    updatePasswordToggleState();
  }

  if (ssidSelect) {
    ssidSelect.addEventListener('change', handleSsidChange);
  }

  toggleManualSsid(isManualSelection());

  populateNetworks();

  if (systemDetailsToggle && systemDetailsContent) {
    systemDetailsToggle.setAttribute('aria-expanded', 'false');
    systemDetailsToggle.setAttribute('aria-controls', 'systemDetailsContent');
    systemDetailsToggle.addEventListener('click', (event) => {
      event.preventDefault();
      const isHidden = systemDetailsContent.classList.contains('hidden');
      if (isHidden) {
        systemDetailsContent.classList.remove('hidden');
        systemDetailsToggle.classList.add('open');
        systemDetailsToggle.setAttribute('aria-expanded', 'true');
        if (!systemInfoLoaded && !systemInfoLoading) {
          fetchSystemDetails();
        }
      } else {
        systemDetailsContent.classList.add('hidden');
        systemDetailsToggle.classList.remove('open');
        systemDetailsToggle.setAttribute('aria-expanded', 'false');
      }
    });
  }

  // Form submit
  if (setupForm) {
    setupForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      hideError();

      const ssid = ssidSelect && ssidSelect.value && ssidSelect.value !== 'manual'
        ? ssidSelect.value
        : (ssidManual?.value || '').trim();

      const password = (passwordInput?.value || '').trim();
      const zip = (zipInput?.value || '').trim();

      if (!ssid) return showError('Please select or enter a Wi-Fi network.', 'ssid');
      if (!password) return showError('Please enter your Wi-Fi password.', 'password');
      if (!/^\d{5}(-\d{4})?$/.test(zip)) return showError('Please enter a valid ZIP code.', 'zip_code');

      // Button -> loading
      if (saveButton) saveButton.disabled = true;
      if (buttonText) buttonText.textContent = 'Validating…';
      if (buttonLoader) buttonLoader.classList.add('show');

      // Safety reset in case the request is lost by captive network
      let safetyReset = setTimeout(() => {
        if (saveButton) saveButton.disabled = false;
        if (buttonText) buttonText.textContent = 'Save & Connect';
        if (buttonLoader) buttonLoader.classList.remove('show');
      }, 15000);

      try {
        const res = await fetch('/configure', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ssid, password, zip_code: zip })
        });

        clearTimeout(safetyReset);

        if (!res.ok) {
          const raw = await res.text();
          let message = 'Configuration failed';
          let field;
          if (raw) {
            try {
              const parsed = JSON.parse(raw);
              if (parsed && parsed.error) {
                if (parsed.error.message) message = parsed.error.message;
                if (parsed.error.field) field = parsed.error.field;
              } else {
                message = typeof parsed === 'string' ? parsed : raw;
              }
            } catch (_) {
              message = raw;
            }
          }
          const err = new Error(message);
          if (field) err.field = field;
          throw err;
        }

        // Show ready to activate state
        if (setupState) setupState.classList.add('hidden');
        if (successState) successState.style.display = 'block';
        scrollIntoViewWithOffset(successState);
      } catch (error) {
        let msg = String(error && error.message ? error.message : error);
        let fieldName = (error && typeof error === 'object' && 'field' in error) ? error.field : null;

        // Friendlier copy for fetch/captive cases
        if ((error && error.name === 'TypeError') || /Failed to fetch|NetworkError/i.test(msg)) {
          msg = 'Network error: Could not reach the device. Make sure you’re still connected to “WICID-Setup” and try again.';
        }
        // If the message still looks like JSON, attempt to parse
        if (/^\s*\{.*\}\s*$/.test(msg)) {
          try {
            const fallback = JSON.parse(msg);
            if (fallback && fallback.error && fallback.error.message) {
              msg = fallback.error.message;
              if (!fieldName && fallback.error.field) fieldName = fallback.error.field;
            }
          } catch (_) {
            // keep original string
          }
        }
        showError(msg, fieldName);
      } finally {
        // Restore button
        if (saveButton) saveButton.disabled = false;
        if (buttonText) buttonText.textContent = 'Save & Connect';
        if (buttonLoader) buttonLoader.classList.remove('show');
      }
    });
  }

  // Restart / Activate
  if (restartNowButton) {
    restartNowButton.addEventListener('click', async () => {
      try {
        restartNowButton.disabled = true;
        const original = restartNowButton.textContent;
        restartNowButton.textContent = 'Activating…';
        await fetch('/restart-now', { method: 'POST' });
        // Let the device take over; no further UI needed here
        setTimeout(() => { restartNowButton.textContent = original; }, 4000);
      } catch (_) {
        restartNowButton.disabled = false;
      }
    });
  }

  async function populateNetworks() {
    if (!ssidSelect) return;
    try {
      ssidSelect.innerHTML = '';
      const loadingOption = document.createElement('option');
      loadingOption.value = '';
      loadingOption.textContent = 'Scanning networks...';
      loadingOption.disabled = true;
      loadingOption.selected = true;
      ssidSelect.appendChild(loadingOption);

      let data = { networks: [] };

      try {
        const response = await withTimeout(fetch('/scan'), 5000);
        data = await response.json();
      } catch (_) {
        try {
          const response2 = await withTimeout(fetch('/scan'), 5000);
          data = await response2.json();
        } catch (_) {
          // fallthrough to fallback
        }
      }

      ssidSelect.innerHTML = '';
      addPlaceholderOption(ssidSelect);

      if (data.networks && data.networks.length > 0) {
        data.networks.forEach(n => {
          const opt = document.createElement('option');
          opt.value = n.ssid;
          opt.textContent = n.ssid;
          opt.className = 'network-option';
          ssidSelect.appendChild(opt);
        });
      } else {
        ['HomeNetwork', 'OfficeWiFi', 'GuestNetwork'].forEach(n => {
          const opt = document.createElement('option');
          opt.value = n;
          opt.textContent = n;
          opt.className = 'network-option fallback';
          ssidSelect.appendChild(opt);
        });
      }

      addManualOption(ssidSelect);

      applyInitialSsidSelection();
    } catch (err) {
      ssidSelect.innerHTML = '';
      addPlaceholderOption(ssidSelect);
      addManualOption(ssidSelect);
      applyInitialSsidSelection();
    }
  }

  function handleSsidChange() {
    if (!ssidSelect) return;
    const isManual = isManualSelection();
    toggleManualSsid(isManual, { preserveValue: isManual });
    if (isManual && ssidManual) {
      ssidManual.focus();
    }
  }

  function toggleManualSsid(show, { preserveValue = false } = {}) {
    if (!ssidManualWrapper || !ssidManual) return;
    ssidManualWrapper.classList.toggle('hidden', !show);
    ssidManualWrapper.setAttribute('aria-hidden', show ? 'false' : 'true');
    ssidManual.disabled = !show;
    if (!show && !preserveValue) {
      ssidManual.value = '';
    }
    if (show) {
      if (ssidSelect) {
        ssidSelect.classList.remove('input-error');
        ssidSelect.removeAttribute('aria-invalid');
      }
    } else if (ssidManual) {
      ssidManual.classList.remove('input-error');
      ssidManual.removeAttribute('aria-invalid');
    }
    if (currentErrorField === 'ssid' && errorContainer && !errorContainer.classList.contains('hidden')) {
      applyFieldError('ssid');
    }
  }

  function applyInitialSsidSelection() {
    if (initialSsidApplied) return;
    if (!ssidSelect) return;

    if (!initialSsid) {
      toggleManualSsid(false, { preserveValue: true });
      initialSsidApplied = true;
      return;
    }
    const options = Array.from(ssidSelect.options || []);
    const match = options.find(opt => opt.value === initialSsid);
    if (match) {
      ssidSelect.value = initialSsid;
      toggleManualSsid(false, { preserveValue: true });
    } else {
      ssidSelect.value = 'manual';
      toggleManualSsid(true, { preserveValue: true });
      if (ssidManual && !ssidManual.value) {
        ssidManual.value = initialSsid;
      }
    }
    initialSsidApplied = true;
  }

  function scrollIntoViewWithOffset(element) {
    if (!element) return;
    const headerHeight = banner ? banner.offsetHeight : 0;
    const offset = Math.max(headerHeight + 16, 0);
    const targetY = Math.max(element.getBoundingClientRect().top + window.scrollY - offset, 0);
    window.scrollTo({ top: targetY, behavior: 'smooth' });
  }

  function updatePasswordToggleState() {
    if (!passwordToggle || !passwordInput) return;
    const isVisible = passwordInput.type === 'text';
    if (passwordToggleIconShow) passwordToggleIconShow.classList.toggle('hidden', !isVisible);
    if (passwordToggleIconHide) passwordToggleIconHide.classList.toggle('hidden', isVisible);
    passwordToggle.setAttribute('aria-label', isVisible ? 'Hide password' : 'Show password');
    passwordToggle.setAttribute('aria-pressed', isVisible ? 'true' : 'false');
  }

  async function fetchSystemDetails() {
    if (!systemDetailsContent) return;
    systemInfoLoading = true;
    renderSystemDetailsLoading();

    try {
      const response = await withTimeout(fetch('/system-info'), 5000);
      if (!response.ok) {
        throw new Error('Unable to load system details.');
      }
      const data = await response.json();
      renderSystemDetails(data);
      systemInfoLoaded = true;
    } catch (error) {
      renderSystemDetailsError();
    } finally {
      systemInfoLoading = false;
    }
  }

  function renderSystemDetails(details) {
    if (!systemDetailsContent) return;
    const info = details || {};
    const entries = [
      ['Device type', info.machine_type || 'Unknown'],
      ['OS version', info.os_version || 'Unknown'],
      ['WICID version', info.wicid_version || 'Unknown']
    ];

    const list = document.createElement('dl');
    list.className = 'system-details-list';

    entries.forEach(([label, value]) => {
      const term = document.createElement('dt');
      term.textContent = label;
      const description = document.createElement('dd');
      description.textContent = value;
      list.appendChild(term);
      list.appendChild(description);
    });

    systemDetailsContent.innerHTML = '';
    systemDetailsContent.appendChild(list);
  }

  function renderSystemDetailsLoading() {
    if (!systemDetailsContent) return;
    systemDetailsContent.innerHTML = '<div class="system-details-loading">Loading system information...</div>';
  }

  function renderSystemDetailsError() {
    if (!systemDetailsContent) return;
    systemDetailsContent.innerHTML = '<div class="system-details-loading">Unable to load system details. Please try again.</div>';
  }

  function addPlaceholderOption(select) {
    if (!select) return;
    const placeholderOption = document.createElement('option');
    placeholderOption.value = '';
    placeholderOption.textContent = 'Select a network...';
    placeholderOption.disabled = true;
    placeholderOption.hidden = true;
    placeholderOption.selected = true;
    select.appendChild(placeholderOption);
  }

  function isManualSelection() {
    return ssidSelect?.value === 'manual';
  }

  function addManualOption(select) {
    if (!select) return;
    const manualOption = document.createElement('option');
    manualOption.value = 'manual';
    manualOption.textContent = 'Manually enter...';
    select.appendChild(manualOption);
  }

  function showError(message, field) {
    if (!errorContainer) return;
    clearFieldErrors();
    errorContainer.textContent = message;
    errorContainer.classList.remove('hidden');
    applyFieldError(field);
    currentErrorField = field || null;
    return false;
  }

  function hideError() {
    if (!errorContainer) return;
    errorContainer.textContent = '';
    errorContainer.classList.add('hidden');
    currentErrorField = null;
    clearFieldErrors();
  }

  function applyFieldError(field) {
    if (!field) return;
    let target = null;
    if (field === 'ssid') {
      target = isManualSelection() ? ssidManual : ssidSelect;
      if (!target) {
        target = ssidSelect || ssidManual;
      }
    } else if (field === 'password') {
      target = passwordInput;
    } else if (field === 'zip_code') {
      target = zipInput;
    }
    if (target) {
      target.classList.add('input-error');
      target.setAttribute('aria-invalid', 'true');
    }
  }

  function clearFieldErrors() {
    [ssidSelect, ssidManual, passwordInput, zipInput].forEach(el => {
      if (!el) return;
      el.classList.remove('input-error');
      el.removeAttribute('aria-invalid');
    });
  }
});
