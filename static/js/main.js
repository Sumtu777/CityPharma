// ============================================
// CityPharma Main JavaScript File
// ============================================

// Auto-dismiss flash messages after 5 seconds
// This makes the success/error messages disappear automatically
document.addEventListener('DOMContentLoaded', function() {
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(function(alert) {
        setTimeout(function() {
            // Bootstrap's Alert class has a close method
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, 5000); // 5000ms = 5 seconds
    });
});