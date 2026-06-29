const remindersEl = document.getElementById('reminders');
const countLabel = document.getElementById('count-label');
const nextTitle = document.getElementById('next-title');
const nextTime = document.getElementById('next-time');
const refreshButton = document.getElementById('refresh-button');

const formatDateTime = (value) => {
    const date = new Date(value);
    return new Intl.DateTimeFormat('en', {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    }).format(date);
};

const renderEmpty = () => {
    remindersEl.innerHTML = '<p class="empty-state">No calendar reminders have been added.</p>';
    countLabel.textContent = '0';
    nextTitle.textContent = 'No reminders yet';
    nextTime.textContent = '';
};

const renderReminders = (reminders) => {
    const sorted = [...reminders].sort((a, b) => a.starts_at.localeCompare(b.starts_at));
    countLabel.textContent = String(sorted.length);

    if (!sorted.length) {
        renderEmpty();
        return;
    }

    const next = sorted[0];
    nextTitle.textContent = next.title;
    nextTime.textContent = `${formatDateTime(next.starts_at)} · ${next.time_slot}`;

    remindersEl.innerHTML = sorted.map((reminder) => `
        <article class="reminder-card">
            <div>
                <p class="reminder-date">${formatDateTime(reminder.starts_at)}</p>
                <h3>${reminder.title}</h3>
                <p class="tracking">Tracking ${reminder.tracking_number}</p>
            </div>
            <div class="reminder-meta">
                <span>${reminder.time_slot}</span>
                <span>Alert ${formatDateTime(reminder.reminder_at)}</span>
            </div>
        </article>
    `).join('');
};

const loadReminders = async () => {
    try {
        const response = await fetch(`reminders.json?cache=${Date.now()}`);
        if (!response.ok) {
            renderEmpty();
            return;
        }
        const reminders = await response.json();
        renderReminders(Array.isArray(reminders) ? reminders : []);
    } catch (error) {
        remindersEl.innerHTML = '<p class="empty-state">Start the calendar with python calendar_reminder.py --serve.</p>';
    }
};

refreshButton.addEventListener('click', loadReminders);
loadReminders();
