document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('setupForm');
    const errorContainer = document.getElementById('errorContainer');
    const saveButton = document.getElementById('saveButton');
    const buttonText = saveButton.querySelector('.button-text');
    const buttonLoader = saveButton.querySelector('.button-loader');
    const passwordInput = document.getElementById('password');
    const passwordToggle = document.getElementById('passwordToggle');
    const ssidSelect = document.getElementById('ssid');
    const ssidManual = document.getElementById('ssid-manual');
    const statusDiv = document.getElementById('status');

    // Password reveal functionality
    passwordToggle.addEventListener('click', function() {
        if (passwordInput.type === 'password') {
            passwordInput.type = 'text';
            passwordToggle.innerHTML = '<svg fill="none" height="24" viewBox="0 0 24 24" width="24" xmlns="http://www.w3.org/2000/svg"><path d="M12 7C7.91992 7 5.1716 10.5514 4.29842 11.8582C4.10438 12.1486 4.10438 12.5181 4.29842 12.8085C5.1716 14.1153 7.91992 17.6667 12 17.6667C16.0801 17.6667 18.8284 14.1153 19.7016 12.8085C19.8956 12.5181 19.8956 12.1486 19.7016 11.8582C18.8284 10.5514 16.0801 7 12 7Z" stroke="currentColor"/><path d="M14.6667 12.3333C14.6667 13.8061 13.4728 15 12 15C10.5273 15 9.33334 13.8061 9.33334 12.3333C9.33334 11.9309 9.4225 11.5492 9.58214 11.2071C9.83966 10.6552 10.2806 10.2061 10.8265 9.93808C11.1806 9.76426 11.5789 9.66666 12 9.66666C13.4728 9.66666 14.6667 10.8606 14.6667 12.3333Z" stroke="currentColor"/></svg>';
            passwordToggle.setAttribute('aria-label', 'Hide password');
        } else {
            passwordInput.type = 'password';
            passwordToggle.innerHTML = '<svg fill="none" height="24" viewBox="0 0 24 24" width="24" xmlns="http://www.w3.org/2000/svg"><path d="M8.74986 7.77881C6.46113 8.90053 4.91386 10.9371 4.29838 11.8582C4.10433 12.1486 4.10438 12.5181 4.29842 12.8085C5.1716 14.1153 7.91992 17.6667 12 17.6667C12.9219 17.6667 13.7758 17.4853 14.5554 17.1896" stroke="currentColor" stroke-linecap="round"/><path d="M10.5 10.1282C10.105 10.3975 9.78607 10.7701 9.58214 11.2071C9.4225 11.5492 9.33334 11.9309 9.33334 12.3333C9.33334 13.8061 10.5273 15 12 15C12.4204 15 12.8181 14.9027 13.1718 14.7294" stroke="currentColor"/><path d="M12 9.66663C13.4728 9.66663 14.6667 10.8605 14.6667 12.3333C14.6667 12.7802 14.5567 13.2015 14.3624 13.5715" stroke="currentColor" stroke-linecap="round"/><path d="M6 3L17 21" stroke="currentColor" stroke-linecap="round"/><path d="M11.5 7.01786C11.6644 7.00609 11.831 7 12 7C16.0801 7 18.8284 10.5514 19.7016 11.8582C19.8956 12.1486 19.8952 12.5188 19.7011 12.8092C19.2051 13.5514 18.1049 15.0165 16.5 16.1445" stroke="currentColor" stroke-linecap="round"/></svg>';
            passwordToggle.setAttribute('aria-label', 'Show password');
        }
    });

    // Network dropdown functionality
    function toggleManualInput(shouldShow) {
        if (shouldShow) {
            ssidManual.classList.add('show');
        } else {
            ssidManual.classList.remove('show');
            ssidManual.value = '';
        }
    }

    // Show manual input only when needed
    ssidSelect.addEventListener('change', function() {
        const isManual = this.value === 'manual';
        toggleManualInput(isManual);
        if (isManual) {
            ssidManual.focus();
        }
    });

    // If user starts typing in manual input, clear dropdown selection
    ssidManual.addEventListener('input', function() {
        if (this.value.trim() !== '') {
            ssidSelect.value = 'manual';
            ssidManual.classList.add('show');
        }
    });

    // Populate network dropdown with available networks
    async function populateNetworks() {
        try {
            // Show loading state
            const loadingOption = document.createElement('option');
            loadingOption.value = '';
            loadingOption.textContent = 'Scanning networks...';
            loadingOption.disabled = true;
            ssidSelect.appendChild(loadingOption);

            // Fetch available networks from the device
            const response = await fetch('/scan');
            const data = await response.json();
            
            // Clear loading option
            ssidSelect.innerHTML = '<option value="">Select a network...</option>';
            
            if (data.networks && data.networks.length > 0) {
                // Add scanned networks
                data.networks.forEach(network => {
                    const option = document.createElement('option');
                    option.value = network.ssid;
                    option.textContent = network.ssid;
                    option.className = 'network-option';
                    ssidSelect.appendChild(option);
                });
            } else {
                // Fallback to common network names if scan fails
                const fallbackNetworks = ['HomeNetwork', 'OfficeWiFi', 'GuestNetwork'];
                fallbackNetworks.forEach(network => {
                    const option = document.createElement('option');
                    option.value = network;
                    option.textContent = network;
                    option.className = 'network-option fallback';
                    ssidSelect.appendChild(option);
                });
            }

            // Always add manual entry option
            const manualOption = document.createElement('option');
            manualOption.value = 'manual';
            manualOption.textContent = 'Manually enter...';
            ssidSelect.appendChild(manualOption);

        } catch (error) {
            console.error('Network scan failed:', error);
            // Clear loading and show error
            ssidSelect.innerHTML = '<option value="">Select a network...</option>';
            
            // Add manual entry option as fallback
            const manualOption = document.createElement('option');
            manualOption.value = 'manual';
            manualOption.textContent = 'Manually enter...';
            ssidSelect.appendChild(manualOption);
        }
    }

    // Start network population
    populateNetworks();


    // Start the page initialization process
    initializePage();

    form.addEventListener('submit', async function(e) {
        e.preventDefault();

        // Clear previous errors
        errorContainer.classList.add('hidden');
        document.querySelectorAll('.form-control.error').forEach(el => el.classList.remove('error'));

        const submitButton = form.querySelector('button[type="submit"]');
        submitButton.disabled = true;
        buttonText.textContent = 'Validating...';
        buttonLoader.classList.add('show');

        // Determine SSID correctly when 'manual' option is selected
        const selectedSsid = ssidSelect.value.trim();
        const manualSsid = ssidManual.value.trim();
        const resolvedSsid = (selectedSsid === 'manual') ? manualSsid : (selectedSsid || manualSsid);

        // Client-side guard: ensure manual entry is provided when 'manual' is selected
        if ((selectedSsid === 'manual' && !manualSsid) || !resolvedSsid) {
            showError({ message: 'SSID cannot be empty.', field: 'ssid' });
            submitButton.disabled = false;
            buttonText.textContent = 'Save & Connect';
            buttonLoader.classList.remove('show');
            return;
        }

        const formData = {
            ssid: resolvedSsid,
            password: document.getElementById('password').value,
            zip_code: document.getElementById('zip_code').value.trim()
        };

        try {
            const response = await fetch('/configure', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(formData)
            });

            // Try to parse JSON, but fail gracefully if not JSON
            let result = {};
            try {
                result = await response.json();
            } catch (e) {
                // Non-JSON or empty body; treat as generic server error
                throw new Error('Server returned an invalid response.');
            }

            // Handle pre-flight errors by either HTTP status or explicit status field
            if ((response.status === 400 && result.error) || (result.status === 'error' && result.error)) {
                throw result.error;
            }

            // Handle any other unexpected server errors
            if (!response.ok) {
                throw new Error(result.message || 'An unknown server error occurred.');
            }

            // If we get a 200 OK response, show success state
            if (response.status === 200 && result.status === 'precheck_success') {
                // Hide the form, show success message
                document.getElementById('setupState').style.display = 'none';
                document.getElementById('successState').style.display = 'block';
                // Device will reboot shortly (server handles timing)
                return;
            }

            // Unexpected success format
            if (result.status === 'success') {
                document.getElementById('setupState').style.display = 'none';
                document.getElementById('successState').style.display = 'block';
                return;
            }
        } catch (error) {
            let errorMessage = error && error.message ? error.message : 'An unknown error occurred.';
            // Don't show a generic network error if we are already on the precheck-success state
            if (document.body.classList.contains('managed-disconnect')) return;

            if (error.name === 'TypeError' && (error.message || '').includes('fetch')) {
                errorMessage = 'Network error: Could not reach the device. Please ensure you are connected to the WICID-Setup WiFi network.';
            }

            // If we have the structured error object, prefer showError for field highlighting
            if (error && (error.message || error.field)) {
                showError({ message: errorMessage, field: error.field || null });
            } else {
                showStatus(`Error: ${errorMessage}`, 'error');
            }

            // Reset button state
            submitButton.disabled = false;
            buttonText.textContent = 'Save & Connect';
            buttonLoader.classList.remove('show');
        }
    });

    function showStatus(message, type) {
        statusDiv.textContent = message;
        statusDiv.className = `status ${type} show`;

        // Add animation
        statusDiv.classList.add('animate-in');

        // Auto-hide error messages after 10 seconds
        if (type === 'error') {
            setTimeout(() => {
                statusDiv.classList.add('fade-out');
                setTimeout(() => {
                    statusDiv.classList.add('hidden');
                    statusDiv.classList.remove('fade-out');
                }, 500);
            }, 10000);
        }
    }

    // --- Page Initialization ---
    function initializePage() {
        const pageData = window.WICID_PAGE_DATA || { settings: {}, error: null };
        const settings = pageData.settings || {};
        const error = pageData.error;

        // Pre-populate the form with all settings
        document.getElementById('password').value = settings.password || '';
        document.getElementById('zip_code').value = settings.zip_code || '';

        // Handle SSID pre-population after networks have been scanned
        const presetSsid = settings.ssid || '';
        if (presetSsid) {
            // Wait for the network scan to finish before setting the SSID value
            const checkNetworksInterval = setInterval(() => {
                const matchingOption = Array.from(ssidSelect.options).find(option => option.value === presetSsid);
                if (matchingOption || ssidSelect.options.length > 2) { // >2 to account for default and manual options
                    clearInterval(checkNetworksInterval);
                    if (matchingOption) {
                        ssidSelect.value = presetSsid;
                        toggleManualInput(false);
                    } else {
                        ssidSelect.value = 'manual';
                        ssidManual.value = presetSsid;
                        toggleManualInput(true);
                    }
                }
            }, 100);
        }

        // Display the error from the previous attempt, if any
        if (error) {
            showError(error);
        }

        // Focus on the first empty field, prioritizing password if SSID is set
        if (!settings.ssid) {
            ssidSelect.focus();
        } else if (!settings.password) {
            passwordInput.focus();
        } else if (!settings.zip_code) {
            document.getElementById('zip_code').focus();
        }
    }

    // showManagedDisconnectUI removed; handled by precheck_success.html navigation

    function showError(error) {
        let message = error.message || 'An unknown error occurred.';
        let field = error.field || null;

        errorContainer.innerHTML = message;
        errorContainer.classList.remove('hidden');
        errorContainer.setAttribute('role', 'alert');
        errorContainer.setAttribute('aria-live', 'assertive');

        // Clear previous errors
        document.querySelectorAll('.form-control.error').forEach(el => {
            el.classList.remove('error');
            el.removeAttribute('aria-invalid');
            el.removeAttribute('aria-describedby');
        });

        // Highlight the specific field that failed
        if (field === 'ssid') {
            ssidSelect.classList.add('error');
            ssidManual.classList.add('error');
            ssidSelect.setAttribute('aria-invalid', 'true');
            ssidSelect.setAttribute('aria-describedby', 'errorContainer');
            ssidManual.setAttribute('aria-invalid', 'true');
            ssidManual.setAttribute('aria-describedby', 'errorContainer');
        } else if (field === 'password') {
            passwordInput.classList.add('error');
            passwordInput.setAttribute('aria-invalid', 'true');
            passwordInput.setAttribute('aria-describedby', 'errorContainer');
        } else if (field === 'zip_code') {
            document.getElementById('zip_code').classList.add('error');
            document.getElementById('zip_code').setAttribute('aria-invalid', 'true');
            document.getElementById('zip_code').setAttribute('aria-describedby', 'errorContainer');
        }

        // Scroll error into view
        errorContainer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
    
    // Add animation to form elements
    const formGroups = document.querySelectorAll('.form-group');
    formGroups.forEach((group, index) => {
        group.style.animation = `fadeIn 0.3s ease-out ${index * 0.1}s forwards`;
        group.style.opacity = '0';
    });

    // System Details functionality
    const systemDetailsToggle = document.getElementById('systemDetailsToggle');
    const systemDetailsContent = document.getElementById('systemDetailsContent');
    let systemDetailsLoaded = false;

    async function fetchSystemDetails() {
        try {
            const response = await fetch('/system-info');
            if (!response.ok) {
                throw new Error('Failed to fetch system information');
            }
            const data = await response.json();
            return data;
        } catch (error) {
            console.error('Error fetching system details:', error);
            return null;
        }
    }

    function renderSystemDetails(data) {
        if (!data) {
            systemDetailsContent.innerHTML = '<div class="system-details-error">Could not load system information.</div>';
            return;
        }

        const html = `
            <div class="system-details-grid">
                <div class="system-detail-item">
                    <span class="detail-label">Machine Type:</span>
                    <span class="detail-value">${data.machine_type || 'Unknown'}</span>
                </div>
                <div class="system-detail-item">
                    <span class="detail-label">Operating System:</span>
                    <span class="detail-value">${data.os_version || 'Unknown'}</span>
                </div>
                <div class="system-detail-item">
                    <span class="detail-label">WICID Version:</span>
                    <span class="detail-value">${data.wicid_version || 'Unknown'}</span>
                </div>
            </div>
        `;
        systemDetailsContent.innerHTML = html;
    }

    systemDetailsToggle.addEventListener('click', async function(e) {
        e.preventDefault();
        
        const isExpanded = !systemDetailsContent.classList.contains('hidden');
        
        if (isExpanded) {
            // Collapse
            systemDetailsContent.classList.add('hidden');
            systemDetailsToggle.classList.remove('expanded');
        } else {
            // Expand
            systemDetailsContent.classList.remove('hidden');
            systemDetailsToggle.classList.add('expanded');
            
            // Load data if not already loaded
            if (!systemDetailsLoaded) {
                systemDetailsContent.innerHTML = '<div class="system-details-loading">Loading system information...</div>';
                const data = await fetchSystemDetails();
                renderSystemDetails(data);
                systemDetailsLoaded = true;
            }
        }
    });
});
