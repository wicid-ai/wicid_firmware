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

  const setupState = document.getElementById('setupState');
  const successStateNoUpdate = document.getElementById('successStateNoUpdate');
  const successStateUpdate = document.getElementById('successStateUpdate');
  const activateButton = document.getElementById('activateButton');
  const updateNowButton = document.getElementById('updateNowButton');

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

  // Poll validation status endpoint
  async function pollValidationStatus(statusUrl, timeout = 120000) {
    const startTime = Date.now();
    const pollInterval = 2000; // 2 seconds
    let consecutiveErrors = 0;
    const maxConsecutiveErrors = 3;

    while (Date.now() - startTime < timeout) {
      try {
        // Update button text based on elapsed time
        const elapsed = Math.floor((Date.now() - startTime) / 1000);

        const response = await fetch(statusUrl);
        if (!response.ok) {
          // Network error - retry with backoff
          consecutiveErrors++;
          if (consecutiveErrors >= maxConsecutiveErrors) {
            return {
              success: false,
              error: {
                message: 'Lost connection to device. Please check your connection to WICID-Setup.',
                field: null
              }
            };
          }
          // Wait and retry
          await new Promise(resolve => setTimeout(resolve, pollInterval));
          continue;
        }

        // Reset error counter on successful response
        consecutiveErrors = 0;

        const data = await response.json();

        // Update button text based on state
        if (data.state === 'validating_wifi') {
          if (buttonText) buttonText.textContent = 'Testing WiFi…';
        } else if (data.state === 'checking_updates') {
          if (buttonText) buttonText.textContent = 'Checking for updates…';
        } else if (data.state === 'success') {
          // Validation complete
          return {
            success: true,
            updateAvailable: data.update_available || false,
            updateInfo: data.update_info || null
          };
        } else if (data.state === 'error') {
          // Validation failed - this is a real error, not a network issue
          const error = data.error || { message: 'Validation failed', field: null };
          return {
            success: false,
            error: {
              message: error.message,
              field: error.field || null
            }
          };
        }

        // Wait before next poll
        await new Promise(resolve => setTimeout(resolve, pollInterval));

      } catch (error) {
        // Network/parsing error - retry with backoff
        consecutiveErrors++;
        if (consecutiveErrors >= maxConsecutiveErrors) {
          return {
            success: false,
            error: {
              message: 'Lost connection to device. Please check your connection to WICID-Setup.',
              field: null
            }
          };
        }
        // Wait and retry
        await new Promise(resolve => setTimeout(resolve, pollInterval));
      }
    }

    // Timeout
    return {
      success: false,
      error: {
        message: 'Validation timed out. Please try again.',
        field: null
      }
    };
  }

  // Show success state with appropriate content
  function showSuccessState(updateAvailable, updateInfo) {
    // Hide setup form
    if (setupState) setupState.classList.add('hidden');

    if (updateAvailable && updateInfo) {
      // Show update state
      if (successStateUpdate) {
        // Update version number
        const versionElement = successStateUpdate.querySelector('#updateVersion');
        if (versionElement && updateInfo.version) {
          versionElement.textContent = " to firmware version " + updateInfo.version;
        }

        successStateUpdate.style.display = 'block';
        scrollIntoViewWithOffset(successStateUpdate);
      }
    } else {
      // Show no-update state
      if (successStateNoUpdate) {
        successStateNoUpdate.style.display = 'block';
        scrollIntoViewWithOffset(successStateNoUpdate);
      }
    }
  }

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

      // Prevent multiple submissions
      if (saveButton && saveButton.disabled) return;

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
      // Only re-enable if we're still in the setup state (not moved to success)
      let safetyReset = setTimeout(() => {
        if (saveButton && setupState && !setupState.classList.contains('hidden')) {
          saveButton.disabled = false;
          if (buttonText) buttonText.textContent = 'Save & Continue';
          if (buttonLoader) buttonLoader.classList.remove('show');
        }
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

        // Parse response to get status URL
        const data = await res.json();

        if (data.status === 'validation_started' && data.status_url) {
          // Start polling for validation status
          const validationResult = await pollValidationStatus(data.status_url);

          if (validationResult.success) {
            // Validation successful - show appropriate success state
            // Button stays disabled - don't re-enable it
            showSuccessState(validationResult.updateAvailable, validationResult.updateInfo);
            return; // Exit early - button remains disabled
          } else {
            // Validation failed - show error
            const err = new Error(validationResult.error.message || 'Validation failed');
            if (validationResult.error && validationResult.error.field) {
              err.field = validationResult.error.field;
            }
            throw err;
          }
        } else {
          throw new Error('Unexpected response from server');
        }
      } catch (error) {
        let msg = String(error && error.message ? error.message : error);
        let fieldName = (error && typeof error === 'object' && 'field' in error) ? error.field : null;

        // Friendlier copy for fetch/captive cases
        if ((error && error.name === 'TypeError') || /Failed to fetch|NetworkError/i.test(msg)) {
          msg = 'Network error: Could not reach the device. Make sure you\'re still connected to "WICID-Setup" and try again.';
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
        // Only re-enable button on error
        if (saveButton) saveButton.disabled = false;
        if (buttonText) buttonText.textContent = 'Save & Continue';
        if (buttonLoader) buttonLoader.classList.remove('show');
      }
    });
  }

  // Activate button handler (no update scenario)
  if (activateButton) {
    activateButton.addEventListener('click', async () => {
      // Prevent multiple clicks
      if (activateButton.disabled) return;

      activateButton.disabled = true;
      const buttonTextSpan = activateButton.querySelector('.button-text');
      const originalText = buttonTextSpan?.textContent || '';

      try {
        if (buttonTextSpan) buttonTextSpan.textContent = 'Activating…';
        const response = await fetch('/activate', { method: 'POST' });
        if (!response.ok) throw new Error('Activation failed.');

        setTimeout(() => {
          if (buttonTextSpan) buttonTextSpan.textContent = 'Activated!';
        }, 2000);
      } catch (err) {
        // Only re-enable on error
        activateButton.disabled = false;
        if (buttonTextSpan) buttonTextSpan.textContent = originalText;
        showError('Activation failed. Please try again.');
      }
    });
  }

  // Update Now button handler (update available scenario)
  if (updateNowButton) {
    updateNowButton.addEventListener('click', async () => {
      // Prevent multiple clicks
      if (updateNowButton.disabled) return;

      updateNowButton.disabled = true;
      const buttonTextSpan = updateNowButton.querySelector('.button-text');
      const progressSpan = document.querySelector('.progress-text');
      const originalText = buttonTextSpan?.textContent || '';

      try {
        if (buttonTextSpan) buttonTextSpan.textContent = 'Starting update…';
        if (progressSpan) progressSpan.textContent = '';

        // Trigger update and get status URL
        const response = await fetch('/update-now', { method: 'POST' });
        const data = await response.json();

        if (data.status === 'update_started' && data.status_url) {
          // Poll for update progress
          await pollUpdateProgress(data.status_url, buttonTextSpan, progressSpan);
        }

        // Device will reboot after update completes - button stays disabled
      } catch (err) {
        // Only re-enable on error
        updateNowButton.disabled = false;
        if (buttonTextSpan) buttonTextSpan.textContent = originalText;
        if (progressSpan) progressSpan.textContent = '';
        showError('Update failed. Please try again.');
      }
    });
  }

  function formatProgressLabel(baseText, progressValue) {
    if (progressValue === null || progressValue === undefined) {
      return `${baseText}...`;
    }

    if (typeof progressValue === 'string' && progressValue.trim() === '') {
      return `${baseText}...`;
    }

    const numericProgress = Number(progressValue);
    if (!Number.isFinite(numericProgress)) {
      return `${baseText}...`;
    }

    const clampedProgress = Math.max(0, Math.min(100, Math.round(numericProgress)));
    return `${baseText} ${clampedProgress}%`;
  }

  function setButtonProgress(buttonTextElement, progressElement, baseText, progressValue) {
    if (buttonTextElement) {
      buttonTextElement.textContent = formatProgressLabel(baseText, progressValue);
    }

    if (progressElement) {
      progressElement.textContent = '';
    }
  }

  // Poll update progress and update button text
  async function pollUpdateProgress(statusUrl, buttonTextElement, progressElement) {
    const pollInterval = 500; // Poll every 500ms for smoother updates
    let consecutiveErrors = 0;
    const maxConsecutiveErrors = 10; // Allow more retries before giving up

    while (true) {
      try {
        const response = await fetch(statusUrl);
        if (!response.ok) {
          consecutiveErrors++;
          if (consecutiveErrors >= maxConsecutiveErrors) {
            throw new Error('Failed to get update status');
          }
          // Wait and retry on transient errors
          await new Promise(resolve => setTimeout(resolve, pollInterval));
          continue;
        }

        // Reset error counter on successful response
        consecutiveErrors = 0;

        const data = await response.json();

        // Update button text and progress based on state
        if (data.state === 'downloading') {
          setButtonProgress(buttonTextElement, progressElement, 'Downloading', data.progress);
        } else if (data.state === 'verifying') {
          setButtonProgress(buttonTextElement, progressElement, 'Verifying', data.progress);
        } else if (data.state === 'unpacking') {
          setButtonProgress(buttonTextElement, progressElement, 'Unpacking', data.progress);
        } else if (data.state === 'restarting') {
          if (buttonTextElement) buttonTextElement.textContent = 'Restarting...';
          if (progressElement) progressElement.textContent = '';
          // Device will reboot shortly, stop polling
          return;
        } else if (data.state === 'error') {
          throw new Error('Update failed');
        }

        // Wait before next poll
        await new Promise(resolve => setTimeout(resolve, pollInterval));

      } catch (error) {
        consecutiveErrors++;
        if (consecutiveErrors >= maxConsecutiveErrors) {
          // Too many consecutive errors - give up
          throw error;
        }
        // Wait and retry on transient errors
        await new Promise(resolve => setTimeout(resolve, pollInterval));
      }
    }
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
