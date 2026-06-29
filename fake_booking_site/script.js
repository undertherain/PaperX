document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('redelivery-form');
    const formContainer = document.getElementById('booking-form-container');
    const successContainer = document.getElementById('success-container');
    
    // Fill the desired-date dropdown based on current date
    const dateSelect = document.getElementById('desired-date');
    const today = new Date();
    
    const formatDate = (date) => {
        const mm = String(date.getMonth() + 1).padStart(2, '0');
        const dd = String(date.getDate()).padStart(2, '0');
        const days = ['日', '月', '火', '水', '木', '金', '土'];
        const dayOfWeek = days[date.getDay()];
        return `${mm}月${dd}日(${dayOfWeek})`;
    };
    
    const tomorrow = new Date(today);
    tomorrow.setDate(tomorrow.getDate() + 1);
    
    const dayAfterTomorrow = new Date(today);
    dayAfterTomorrow.setDate(dayAfterTomorrow.getDate() + 2);
    
    dateSelect.options[1].text = `${formatDate(today)} (本日)`;
    dateSelect.options[2].text = `${formatDate(tomorrow)} (明日)`;
    dateSelect.options[3].text = `${formatDate(dayAfterTomorrow)} (明後日)`;
    dateSelect.options[1].value = formatDate(today);
    dateSelect.options[2].value = formatDate(tomorrow);
    dateSelect.options[3].value = formatDate(dayAfterTomorrow);

    form.addEventListener('submit', (e) => {
        e.preventDefault();
        
        // Get values
        const tracking = document.getElementById('tracking-number').value;
        const date = document.getElementById('desired-date').value;
        const time = document.getElementById('desired-time').value;
        
        // Show success screen
        document.getElementById('summary-tracking').textContent = tracking;
        document.getElementById('summary-time').textContent = `${date} ${time}`;
        
        // Generate fake receipt number
        const receiptNumber = Math.floor(10000000 + Math.random() * 90000000);
        document.getElementById('receipt-number').textContent = receiptNumber;
        
        formContainer.classList.add('hidden');
        successContainer.classList.remove('hidden');
        
        // Scroll to top
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });
});
