let userToken = null;
let tokenClient;

window.onload = function () {
    switchTab('queue');
    tokenClient = google.accounts.oauth2.initTokenClient({
        client_id: '36231825761-71lmniatupn218k7tn177m0lmm183tts.apps.googleusercontent.com',
        scope: 'https://www.googleapis.com/auth/bigquery',
        callback: (response) => {
            if (response.error !== undefined) {
                console.error("Login failed:", response);
                return;
            }
            userToken = response.access_token;
            console.log("SUCCESS! Access Token acquired.");
            
            const overlay = document.getElementById('login-overlay');
            overlay.style.opacity = '0';
            setTimeout(() => { overlay.classList.add('hidden'); }, 500);

            fetchQueue();
        },
    });
};

function requestAccessToken() {
    tokenClient.requestAccessToken();
}

let reviewQueue = [];
let approvedQueue = [];

async function fetchQueue() {
    try {
        const response = await fetch('/api/queue', {
            headers: {
                'Authorization': `Bearer ${userToken}`,
                'Content-Type': 'application/json'
            }
        });
        reviewQueue = await response.json();
        renderQueue();
    } catch (error) {
        console.error("Failed to fetch queue:", error);
    }
}

function switchTab(tabId) {
    const titles = {
        'queue': 'PII/SPII Pending Approvals',
        'countryness': 'Countryness Evaluation (OGC)',
        'approved': 'Approved Tags History'
    };
    document.getElementById('page-title').innerText = titles[tabId];
    
  
    document.querySelectorAll('.tab-content').forEach(el => {
        el.classList.add('hidden');
        el.classList.remove('flex', 'active');
    });

   
    const targetTab = document.getElementById(`tab-${tabId}`);
    targetTab.classList.remove('hidden');
    targetTab.classList.add('active');
    
   
    if (tabId === 'queue' || tabId === 'countryness') {
        targetTab.classList.add('flex');
    }

    const activeClass = 'w-full flex justify-between items-center p-3 text-sm font-medium rounded-lg bg-indigo-50 text-indigo-700 transition-colors';
    const inactiveClass = 'w-full flex justify-between items-center p-3 text-sm font-medium rounded-lg text-gray-600 hover:bg-gray-50 transition-colors';
    
    document.getElementById('btn-queue').className = tabId === 'queue' ? activeClass : inactiveClass;
    document.getElementById('btn-countryness').className = tabId === 'countryness' ? activeClass : inactiveClass;
    document.getElementById('btn-approved').className = tabId === 'approved' ? activeClass : inactiveClass;
}

function renderQueue() {
    const tbody = document.getElementById('queue-table-body');
    const approveAllBtn = document.getElementById('approve-all-btn');
    const cancelBtn = document.getElementById('cancel-btn');
    const actionText = document.getElementById('action-header-text');
    
    document.getElementById('queue-badge').innerText = reviewQueue.length;
    
    if (reviewQueue.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="p-8 text-center text-gray-500">No pending AI proposals.</td></tr>`;
        if (approveAllBtn) approveAllBtn.classList.add('hidden');
        if (cancelBtn) cancelBtn.classList.add('hidden');
        if (actionText) actionText.classList.remove('hidden');
        return;
    }

    if (approveAllBtn) approveAllBtn.classList.remove('hidden');
    if (cancelBtn) cancelBtn.classList.remove('hidden');
    if (actionText) actionText.classList.add('hidden');

    tbody.innerHTML = reviewQueue.map(item => `
        <tr class="hover:bg-gray-50 transition-colors" id="row-${item.id}">
            <td class="p-4">
                <span class="block font-medium text-gray-900">${item.column}</span>
                <span class="block text-xs text-gray-400">table: ${item.table}</span>
            </td>
            <td class="p-4">
                <span class="inline-flex px-2 py-1 rounded text-xs font-bold bg-blue-100 text-blue-800">${item.proposal}</span>
            </td>
            <td class="p-4 font-medium">${item.confidence}%</td>
            <td class="p-4 text-gray-600 text-sm">${item.reason}</td>
            <td class="p-4 text-right flex justify-end items-center space-x-3 h-full">
                <button onclick="modifyTag(${item.id})" class="text-indigo-600 hover:underline text-sm">Modify</button>
                <button id="approve-btn-${item.id}" onclick="submitTag(${item.id})" class="bg-green-600 text-white px-3 py-1 rounded hover:bg-green-700 transition-colors shadow-sm min-w-[100px]">Approve</button>
            </td>
        </tr>
    `).join('');
}

async function submitTag(id) {
    const item = reviewQueue.find(i => i.id === id);
    const btn = document.getElementById(`approve-btn-${id}`);
    const originalHTML = btn ? btn.innerHTML : 'Approve';
    
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `Applying...`;
        btn.classList.replace('bg-green-600', 'bg-gray-400');
    }

    try {
        const response = await fetch('/api/tags/approve', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${userToken}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: id, approved_tag: item.proposal })
        });
        const data = await response.json();
        
        if (response.ok) {
            console.log("Tag approved! Moving to approvedQueue:", item);
            
 
            approvedQueue.push(item);
            
   
            reviewQueue = reviewQueue.filter(i => i.id !== id);
            
            renderQueue();
            renderApprovedQueue();
            
            showToast(data.message || `Successfully applied ${item.proposal} tag!`);
        } else {
            showToast("Failed: " + (data.detail || "Unknown error"), true);
            if (btn) resetBtn(btn, originalHTML);
        }
    } catch (error) {
        showToast("Network error.", true);
        if (btn) resetBtn(btn, originalHTML);
    }
}

function resetBtn(btn, originalHTML) {
    btn.disabled = false;
    btn.innerHTML = originalHTML;
    btn.classList.replace('bg-gray-400', 'bg-green-600');
}

function modifyTag(id) {
    const item = reviewQueue.find(i => i.id === id);
    if (!item) return;
    document.getElementById('modify-item-id').value = id;
    document.getElementById('modify-select').value = item.proposal;
    document.getElementById('modify-modal').classList.remove('hidden');
}

function closeModifyModal() {
    document.getElementById('modify-modal').classList.add('hidden');
}

async function saveModifiedTag() {
    const id = parseInt(document.getElementById('modify-item-id').value);
    const newTag = document.getElementById('modify-select').value;
    const itemIndex = reviewQueue.findIndex(i => i.id === id);
    
    if (itemIndex !== -1) {
        reviewQueue[itemIndex].proposal = newTag;
        reviewQueue[itemIndex].reason = "Modified by you";
        reviewQueue[itemIndex].confidence = 100;
        
        renderQueue();
        closeModifyModal();
    }
}

async function analyzeTable() {
    const inputField = document.getElementById('bq-table-input');
    const tableFqn = inputField.value.trim();
    if (!tableFqn) return;

    const btnText = document.getElementById('analyze-text');
    const loadingText = document.getElementById('analyze-loading');
    const btn = document.getElementById('analyze-btn');
    
    btnText.classList.add('hidden');
    loadingText.classList.remove('hidden');
    btn.disabled = true;

    try {
        const response = await fetch('/api/analyze', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${userToken}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ table_fqn: tableFqn })
        });
        if (response.ok) {
            await fetchQueue();
            inputField.value = ''; 
        } else {
            const err = await response.json();
            alert("Analysis failed: " + err.detail);
        }
    } catch (error) {
        alert("Network error.");
    } finally {
        btnText.classList.remove('hidden');
        loadingText.classList.add('hidden');
        btn.disabled = false;
    }
}

async function approveAll() {
    if (reviewQueue.length === 0) return;
    if (!confirm(`Apply all ${reviewQueue.length} tags?`)) return;

    
    const itemsToApprove = reviewQueue.map(item => ({
        id: item.id,
        approved_tag: item.proposal 
    }));
    
    try {
        const response = await fetch('/api/tags/approve-batch', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${userToken}`, 'Content-Type': 'application/json' },
            body: JSON.stringify(itemsToApprove)
        });
        const data = await response.json();
        
        if (response.ok) {
            approvedQueue = approvedQueue.concat(reviewQueue);
            
            reviewQueue = []; 
            
            renderQueue();
            renderApprovedQueue();
            showToast(data.message || "Batch approved successfully.");
        } else {
            showToast("Batch Failed: " + (data.detail || "Unknown error"), true);
        }
    } catch (error) {
        showToast("Network error.", true);
    }
}

function showToast(message, isError = false) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `px-4 py-3 rounded shadow-lg text-white text-sm transition-opacity duration-300 ${isError ? 'bg-red-600' : 'bg-green-600'}`;
    toast.innerText = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

async function cancelAnalysis() {
    if (!confirm("Cancel and clear queue?")) return;
    try {
        await fetch('/api/queue', { method: 'DELETE', headers: { 'Authorization': `Bearer ${userToken}` }});
        reviewQueue = [];
        approvedQueue = [];
        renderQueue(); 
        renderApprovedQueue();
    } catch (error) {}
}


let currentCountrynessPayload = null;
let currentCountrynessTable = "";

async function analyzeCountryness() {
    const inputField = document.getElementById('country-table-input');
    const tableFqn = inputField.value.trim();
    
    if (!tableFqn) {
        alert("Please enter a valid project.dataset.table name.");
        return;
    }

    const btnText = document.getElementById('country-analyze-text');
    const loadingText = document.getElementById('country-analyze-loading');
    const btn = document.getElementById('country-analyze-btn');
    
    btnText.classList.add('hidden');
    loadingText.classList.remove('hidden');
    btn.disabled = true;

    try {
        const response = await fetch('/api/countryness/analyze', {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${userToken}`,
                'Content-Type': 'application/json' 
            },
            body: JSON.stringify({ table_fqn: tableFqn })
        });
        
        if (response.ok) {
            const result = await response.json();
            currentCountrynessPayload = result.data || result;
            currentCountrynessTable = tableFqn;
            renderCountrynessPreview(currentCountrynessPayload);
        } else {
            const err = await response.json();
            alert("Analysis failed: " + err.detail);
        }
    } catch (error) {
        alert("Network error.");
    } finally {
        btnText.classList.remove('hidden');
        loadingText.classList.add('hidden');
        btn.disabled = false;
    }
}

function renderCountrynessPreview(data) {
    document.getElementById('countryness-results').classList.remove('hidden');
    document.getElementById('country-rule-name').innerText = `Use Case ${data.use_case_id}: ${data.detected_rule}`;
    document.getElementById('country-rule-reason').innerText = data.reasoning;
    
    const tbody = document.getElementById('country-preview-body');
    if (!data.sample_preview || data.sample_preview.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" class="p-8 text-center text-gray-500">No preview rows generated.</td></tr>`;
        return;
    }

    tbody.innerHTML = data.sample_preview.map(row => {
        const ignoreKeys = ["source_field", "value", "proposed_iso_country", "ISO_Country", "_dfgdia_iso3_country_std_cnty"];
        const pkKey = Object.keys(row).find(k => !ignoreKeys.includes(k)) || "Unknown ID";
        const pkValue = row[pkKey] || 'N/A';

        const predictedCountry = row._dfgdia_iso3_country_std_cnty || row.proposed_iso_country;

        return `
        <tr class="hover:bg-gray-50 transition-colors">
            <td class="p-4 text-gray-500 font-mono text-xs">${pkValue}</td>
            <td class="p-4 font-medium text-gray-800">${row.source_field || '-'}</td>
            <td class="p-4 text-gray-600">${row.value || 'NULL'}</td>
            <td class="p-4">
                <span class="inline-flex px-2 py-1 rounded text-xs font-bold ${predictedCountry === 'USA' ? 'bg-blue-100 text-blue-800' : predictedCountry === 'CAN' ? 'bg-red-100 text-red-800' : 'bg-gray-200 text-gray-800'}">
                    ${predictedCountry || 'NULL'}
                </span>
            </td>
        </tr>
        `;
    }).join('');
}

async function pushCountryness() {
    if (!currentCountrynessPayload || !currentCountrynessTable) return;
    
    const rowUpdatesPayload = 
        currentCountrynessPayload.sample_preview || 
        (currentCountrynessPayload.data && currentCountrynessPayload.data.sample_preview) || 
        [];

    const useCaseId = 
        currentCountrynessPayload.use_case_id || 
        (currentCountrynessPayload.data && currentCountrynessPayload.data.use_case_id) || 
        3;

    if (!confirm(`Execute Use Case ${useCaseId} on all rows in ${currentCountrynessTable}?`)) return;

    const btn = document.getElementById('country-push-btn');
    btn.disabled = true;
    btn.innerText = "Applying...";
    btn.classList.add('bg-gray-400');

    console.log("SENDING ROW UPDATES:", rowUpdatesPayload);

    try {
        const response = await fetch('/api/countryness/apply', {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${userToken}`,
                'Content-Type': 'application/json' 
            },
            body: JSON.stringify({ 
                table_fqn: currentCountrynessTable,
                use_case_id: useCaseId,
                row_updates: rowUpdatesPayload
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showToast(`Success! Logic applied to ${currentCountrynessTable}`);
            document.getElementById('countryness-results').classList.add('hidden');
            document.getElementById('country-table-input').value = '';
            currentCountrynessPayload = null;
        } else {
            showToast("Update Failed: " + (data.detail ? JSON.stringify(data.detail) : "Unknown error"), true);
        }
    } catch (error) {
        showToast("Network error.", true);
    } finally {
        btn.disabled = false;
        btn.innerText = "Push to BigQuery";
        btn.classList.remove('bg-gray-400');
    }
}

function renderApprovedQueue() {
    const badge = document.getElementById('approved-badge');
    if (badge) {
        badge.innerText = approvedQueue.length;
        if (approvedQueue.length > 0) {
            badge.classList.remove('hidden');
        } else {
            badge.classList.add('hidden');
        }
    }


    const tbody = document.getElementById('approved-table-body');
    
    if (!tbody) {
        console.error("Could not find 'approved-table-body' in index.html!");
        return;
    }

    if (approvedQueue.length === 0) {
        tbody.innerHTML = `<tr><td colspan="3" class="p-8 text-center text-gray-500">No recently approved tags.</td></tr>`;
        return;
    }

    tbody.innerHTML = approvedQueue.map(item => `
        <tr class="bg-white border-b hover:bg-gray-50">
            <td class="p-4">
                <span class="block font-medium text-gray-900">${item.column}</span>
                <span class="block text-xs text-gray-400">table: ${item.table}</span>
            </td>
            <td class="p-4">
                <span class="inline-flex px-2 py-1 rounded text-xs font-bold bg-green-100 text-green-800">${item.proposal}</span>
            </td>
            <td class="p-4 text-green-600 font-medium text-sm">Successfully Applied</td>
        </tr>
    `).join('');
}

function clearApprovedQueue() {
    if (!confirm("Are you sure you want to clear your approved tags history?")) return;
    
    approvedQueue = [];
    renderApprovedQueue();
}