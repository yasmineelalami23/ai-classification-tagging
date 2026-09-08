console.log("HELLO FROM BATCH VERSION 1000");
let reviewQueue = [];

async function fetchQueue() {
    try {
        const response = await fetch('/api/queue');
        reviewQueue = await response.json();
        renderQueue();
    } catch (error) {
        console.error("Failed to fetch queue:", error);
    }
}

function switchTab(tabId) {
    document.getElementById('page-title').innerText = tabId === 'queue' ? 'Pending Approvals' : 'Approved Tags History';
    
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.getElementById(`tab-${tabId}`).classList.add('active');

    const activeClass = 'w-full flex items-center p-3 text-sm font-medium rounded-lg bg-indigo-50 text-indigo-700 transition-colors';
    const inactiveClass = 'w-full flex items-center p-3 text-sm font-medium rounded-lg text-gray-600 hover:bg-gray-50 transition-colors';
    
    document.getElementById('btn-queue').className = tabId === 'queue' ? activeClass : inactiveClass;
    document.getElementById('btn-approved').className = tabId === 'approved' ? activeClass : inactiveClass;
}

function renderQueue() {
    const tbody = document.getElementById('queue-table-body');
    const approveAllBtn = document.getElementById('approve-all-btn');
    const actionText = document.getElementById('action-header-text');
    
  
    const inputField = document.getElementById('bq-table-input');
    const analyzeBtn = document.getElementById('analyze-btn');
    
    document.getElementById('queue-badge').innerText = reviewQueue.length;
    

    if (reviewQueue.length > 0) {

        inputField.disabled = true;
        inputField.classList.add('bg-gray-200', 'cursor-not-allowed');
        inputField.placeholder = "Clear the review queue first...";
        
        analyzeBtn.disabled = true;
        analyzeBtn.classList.add('opacity-50', 'cursor-not-allowed');
        analyzeBtn.classList.remove('hover:bg-indigo-700');
    } else {
        // Open it up
        inputField.disabled = false;
        inputField.classList.remove('bg-gray-200', 'cursor-not-allowed');
        inputField.placeholder = "e.g., search-ahmed.my_dataset.customers";
        
        analyzeBtn.disabled = false;
        analyzeBtn.classList.remove('opacity-50', 'cursor-not-allowed');
        analyzeBtn.classList.add('hover:bg-indigo-700');
    }
    
    if (reviewQueue.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="p-8 text-center text-gray-500">No pending AI proposals.</td></tr>`;
        
        if (approveAllBtn) approveAllBtn.classList.add('hidden');
        if (actionText) actionText.classList.remove('hidden');
        return;
    }

    if (approveAllBtn) approveAllBtn.classList.remove('hidden');
    if (actionText) actionText.classList.add('hidden');

    tbody.innerHTML = reviewQueue.map(item => `
        <tr class="hover:bg-gray-50 transition-colors" id="row-${item.id}">
            <td class="p-4">
                <span class="block font-medium text-gray-900">${item.column}</span>
                <span class="block text-xs text-gray-400">table: ${item.table}</span>
            </td>
            <td class="p-4">
                <span class="inline-flex px-2 py-1 rounded text-xs font-bold bg-blue-100 text-blue-800">
                    ${item.proposal}
                </span>
            </td>
            <td class="p-4 font-medium">${item.confidence}%</td>
            <td class="p-4 text-gray-600 text-sm">${item.reason}</td>
            <td class="p-4 text-right flex justify-end items-center space-x-3 h-full">
                <button onclick="modifyTag(${item.id})" class="text-indigo-600 hover:underline text-sm">Modify</button>
                <button id="approve-btn-${item.id}" onclick="submitTag(${item.id})" class="bg-green-600 text-white px-3 py-1 rounded hover:bg-green-700 transition-colors shadow-sm min-w-[100px]">
                    Approve
                </button>
            </td>
        </tr>
    `).join('');
}

async function submitTag(id) {
    // Grab the latest tag from the local array
    const item = reviewQueue.find(i => i.id === id);
    const approvedTag = item.proposal;
    
    const btn = document.getElementById(`approve-btn-${id}`);
    const originalHTML = btn ? btn.innerHTML : 'Approve';
    
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `
            <div class="flex items-center justify-center space-x-1">
                <svg class="animate-spin h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <span>Applying</span>
            </div>
        `;
        btn.classList.replace('bg-green-600', 'bg-gray-400');
        btn.classList.remove('hover:bg-green-700');
        btn.classList.add('cursor-not-allowed');
    }

    try {
        const response = await fetch('/api/tags/approve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: id, approved_tag: approvedTag })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            reviewQueue = reviewQueue.filter(i => i.id !== id);
            renderQueue();
            showToast(data.message || `Successfully applied ${approvedTag} tag!`);
        } else {
            showToast("Failed: " + (data.detail || "Unknown error"), true);
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = originalHTML;
                btn.classList.replace('bg-gray-400', 'bg-green-600');
                btn.classList.add('hover:bg-green-700');
                btn.classList.remove('cursor-not-allowed');
            }
        }
    } catch (error) {
        console.error("Error submitting tag:", error);
        showToast("Network error while trying to apply tag.", true);
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = originalHTML;
            btn.classList.replace('bg-gray-400', 'bg-green-600');
            btn.classList.add('hover:bg-green-700');
            btn.classList.remove('cursor-not-allowed');
        }
    }
}

// --- MODAL NEW FUNCTIONS ---

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
        const item = reviewQueue[itemIndex];

        if (!item.originalProposal) {
            item.originalProposal = item.proposal;
            item.originalReason = item.reason;
        }
        
        item.proposal = newTag;
        
        if (item.proposal === item.originalProposal) {
            item.proposal = item.originalProposal; 
            item.reason = item.originalReason;
        } else {
            item.reason = "⚠️ Modified by user (Original: " + item.originalProposal + ")";
        }
        
        try {
            await fetch('/api/queue/modify', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: id, proposal: item.proposal, reason: item.reason })
            });
        } catch (error) {
            console.error("Failed to sync modification:", error);
        }
        
        renderQueue();
        closeModifyModal();
    }
}
// -------------------------------------

async function analyzeTable() {
    const inputField = document.getElementById('bq-table-input');
    const tableFqn = inputField.value.trim();
    
    if (!tableFqn) {
        alert("Please enter a valid project.dataset.table name.");
        return;
    }

    const btnText = document.getElementById('analyze-text');
    const loadingText = document.getElementById('analyze-loading');
    const btn = document.getElementById('analyze-btn');
    
    btnText.classList.add('hidden');
    loadingText.classList.remove('hidden');
    btn.disabled = true;
    btn.classList.add('cursor-wait');

    try {
        const response = await fetch('/api/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
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
        console.error("Error running analysis:", error);
        alert("Network error.");
    } finally {
        btnText.classList.remove('hidden');
        loadingText.classList.add('hidden');
        btn.disabled = false;
        btn.classList.remove('cursor-wait');
    }
}

async function approveAll() {
    if (reviewQueue.length === 0) return;
    
    const confirmMsg = `Are you sure you want to apply all ${reviewQueue.length} tags to BigQuery in one batch?`;
    if (!confirm(confirmMsg)) return;

    const btnText = document.getElementById('approve-all-text');
    const loadingText = document.getElementById('approve-all-loading');
    const btn = document.getElementById('approve-all-btn');
    
    if(btnText) btnText.classList.add('hidden');
    if(loadingText) loadingText.classList.remove('hidden');
    if(btn) {
        btn.disabled = true;
        btn.classList.add('cursor-wait', 'bg-gray-400');
        btn.classList.remove('hover:bg-green-700', 'bg-green-600');
    }
    
    const idsToApprove = reviewQueue.map(item => item.id);
    
    try {
        const response = await fetch('/api/tags/approve-batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids: idsToApprove })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            reviewQueue = reviewQueue.filter(item => !idsToApprove.includes(item.id));
            renderQueue();
            showToast(data.message || `Successfully applied batch tags!`);
        } else {
            showToast("Batch Failed: " + (data.detail || "Unknown error"), true);
        }
    } catch (error) {
        console.error("Error in batch approval:", error);
        showToast("Network error while trying to batch apply tags.", true);
    } finally {
        if(btnText) btnText.classList.remove('hidden');
        if(loadingText) loadingText.classList.add('hidden');
        if(btn) {
            btn.disabled = false;
            btn.classList.remove('cursor-wait', 'bg-gray-400');
            btn.classList.add('hover:bg-green-700', 'bg-green-600');
        }
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

fetchQueue();