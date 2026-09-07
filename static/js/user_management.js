// Function to open the points management modal
function openPointsModal(userId, username, currentPoints) {
    document.getElementById('pointsModalUserId').value = userId;
    document.getElementById('pointsModalUsername').innerText = username;
    document.getElementById('pointsModalCurrentPoints').innerText = currentPoints;
    new bootstrap.Modal(document.getElementById('pointsModal')).show();
}

// Function to open the delete confirmation modal
function openDeleteModal(userId, username) {
    document.getElementById('deleteUserId').value = userId;
    document.getElementById('deleteUsername').innerText = username;
    new bootstrap.Modal(document.getElementById('deleteUserModal')).show();
}

// Initialize DataTables safely after all scripts load, and wire up search + select-all
window.addEventListener('load', function() {
    try {
        var $table = window.jQuery ? window.jQuery('#usersTable') : null;
        if (!$table || !$table.length || !window.jQuery.fn.DataTable) {
            return;
        }
        // Create DataTable
        var dt = $table.DataTable({
            paging: false,        // Show all users on one page
            info: false,
            lengthChange: false,
            // Columns: 0=checkbox, 1=User ID, 2=Username, 3=Points
            order: [[3, 'desc']]
        });
        // Expose for other functions
        window.usersTableDT = dt;

        // Hook up search input to DataTables search
        var searchInput = document.getElementById('userSearch');
        if (searchInput) {
            searchInput.addEventListener('keyup', function() {
                dt.search(this.value).draw();
            });
        }

        // Implement Select All to affect current filtered rows
        var selectAll = document.getElementById('selectAll');
        if (selectAll) {
            selectAll.addEventListener('change', function() {
                var checked = this.checked;
                // Apply to all filtered rows using DataTables API
                var $nodes = window.jQuery(dt.rows({ search: 'applied' }).nodes());
                $nodes.find('.user-checkbox').prop('checked', checked);
            });
            // Reset header checkbox when table redraws (pagination/search)
            dt.on('draw', function() {
                var headerCb = document.getElementById('selectAll');
                if (headerCb) headerCb.checked = false;
            });
        }
    } catch (e) {
        console.error('Failed to initialize users DataTable:', e);
    }
});

function handleBulkAction(action) {
    var selectedUsers;
    // Prefer DataTables-wide selection (across all pages)
    if (window.usersTableDT && window.jQuery) {
        selectedUsers = window.usersTableDT.$('.user-checkbox:checked').map(function() {
            return this.value;
        }).get();
    } else {
        selectedUsers = [];
        var checkboxes = document.querySelectorAll('.user-checkbox:checked');
        for (var i = 0; i < checkboxes.length; i++) {
            selectedUsers.push(checkboxes[i].value);
        }
    }
    if (selectedUsers.length === 0) {
        alert('Please select at least one user.');
        return;
    }

    if (confirm('Are you sure you want to ' + action + ' ' + selectedUsers.length + ' user(s)?')) {
        fetch('/users/bulk_action', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                action: action,
                user_ids: selectedUsers
            })
        })
        .then(function(response) { return response.json(); })
        .then(function(data) {
            if (data.success) {
                window.location.reload();
            } else {
                alert('An error occurred: ' + data.message);
            }
        });
    }
} 

// Wrapper for old edit button
function editUser(userId, username, points, banned) {
    openPointsModal(userId, username, points);
} 

// Add missing single-delete handler used by table button
function deleteUser(userId) {
    if (!confirm('Are you sure you want to delete user ' + userId + '? This cannot be undone.')) {
        return;
    }
    const fd = new FormData();
    fd.append('user_id', userId);
    fetch('/users/delete', { method: 'POST', body: fd })
        .then(r => {
            if (!r.ok) throw new Error('Request failed');
            return r.text();
        })
        .then(() => window.location.reload())
        .catch(err => alert('Delete failed: ' + err.message));
}