/* ── Global helpers for Email Manager ─────────────────────────── */

async function api(url, opts = {}) {
    const resp = await fetch(url, opts);
    if (!resp.ok) {
        const text = await resp.text();
        throw new Error(`HTTP ${resp.status}: ${text}`);
    }
    return resp.json();
}

function escHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function emailCard(e) {
    const date = e.date ? new Date(e.date).toLocaleString() : '';
    const summaryBadge = e.summary
        ? '<span class="badge badge-green">Summarised</span>'
        : '<span class="badge badge-grey">Unsummarised</span>';
    const preview = (e.summary || e.body_text || '').substring(0, 120);
    return `<div class="email-card">
        <div class="email-card-header">
            <strong>${escHtml(e.sender_name || e.sender)}</strong>
            <span class="email-date">${date}</span>
        </div>
        <div class="email-card-subject">${escHtml(e.subject)}</div>
        <div class="email-card-preview">${escHtml(preview)}${preview.length >= 120 ? '...' : ''}</div>
        <div class="email-card-footer">${summaryBadge}
            ${e.attachments && e.attachments.length ? `<span class="badge badge-blue">${e.attachments.length} file(s)</span>` : ''}
        </div>
    </div>`;
}

function taskCard(t) {
    const pClass = t.priority === 'high' ? 'priority-high' : t.priority === 'low' ? 'priority-low' : 'priority-medium';
    return `<div class="task-card ${pClass}">
        <div class="task-header">
            <span class="task-title">${escHtml(t.title)}</span>
            <span class="badge badge-${t.priority}">${t.priority}</span>
        </div>
        ${t.description ? `<p class="task-desc">${escHtml(t.description)}</p>` : ''}
    </div>`;
}

/* ── Toast notifications ──────────────────────────────────────────────── */
let toastContainer = null;

function showToast(message, type = 'info') {
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.className = 'toast-container';
        document.body.appendChild(toastContainer);
    }
    const toast = document.createElement('div');
    toast.className = `toast ${type === 'error' ? 'error' : ''}`;
    toast.textContent = message;
    toastContainer.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}

/* ── Connection check ─────────────────────────────────────────────────── */
async function checkConnection() {
    const el = document.getElementById('connectionStatus');
    if (!el) return;
    try {
        await api('/health');
        el.innerHTML = '<span class="dot" style="background:#22c55e"></span><span class="status-text">Connected</span>';
    } catch {
        el.innerHTML = '<span class="dot" style="background:#ef4444"></span><span class="status-text">Offline</span>';
    }
}

/* ── Active nav link highlight ────────────────────────────────────────── */
function highlightNav() {
    const path = window.location.pathname;
    document.querySelectorAll('.nav-link').forEach(link => {
        const href = link.getAttribute('href');
        if (href === path || (href === '/' && path === '/')) {
            link.style.background = 'rgba(255,255,255,0.12)';
        }
    });
}

/* ── Floating AI Chatbot ───────────────────────────────────────────────── */
function initChatbot() {
    const fab = document.getElementById('chatbotFab');
    const win = document.getElementById('chatbotWindow');
    const closeBtn = document.getElementById('chatbotClose');
    const input = document.getElementById('chatbotInput');
    const sendBtn = document.getElementById('chatbotSend');
    const messages = document.getElementById('chatbotMessages');
    const suggestions = document.getElementById('chatbotSuggestions');
    if (!fab || !win) return;

    fab.addEventListener('click', () => {
        fab.classList.add('active');
        win.classList.add('open');
        input.focus();
    });
    closeBtn.addEventListener('click', () => {
        win.classList.remove('open');
        fab.classList.remove('active');
    });

    function addMsg(text, role) {
        const div = document.createElement('div');
        div.className = `chat-msg ${role}`;
        div.textContent = text;
        messages.appendChild(div);
        messages.scrollTop = messages.scrollHeight;
        return div;
    }

    async function sendMessage(text) {
        if (!text.trim()) return;
        addMsg(text, 'user');
        input.value = '';
        sendBtn.disabled = true;
        suggestions.style.display = 'none';

        const thinking = addMsg('Thinking...', 'bot thinking');
        try {
            const resp = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text }),
            });
            const data = await resp.json();
            thinking.remove();
            addMsg(data.reply || data.detail || 'Sorry, I could not process that.', 'bot');
        } catch (err) {
            thinking.remove();
            addMsg('Connection error. Please try again.', 'bot');
        }
        sendBtn.disabled = false;
        input.focus();
    }

    sendBtn.addEventListener('click', () => sendMessage(input.value));
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') sendMessage(input.value);
    });

    suggestions.querySelectorAll('.suggestion-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            sendMessage(chip.dataset.q);
        });
    });
}

/* ── PWA Service Worker Registration ──────────────────────────────────── */
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/sw.js').catch(() => {});
}

document.addEventListener('DOMContentLoaded', () => {
    checkConnection();
    highlightNav();
    initChatbot();
    setInterval(checkConnection, 30000);
});
