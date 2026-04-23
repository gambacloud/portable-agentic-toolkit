(function () {
    var API_PORT = window.__PAT_API_PORT__ || 8002;
    var PREF_KEY = 'pat-ctrl-enter';

    function getCtrlEnterPref() {
        return localStorage.getItem(PREF_KEY) === '1';
    }

    function setCtrlEnterPref(val) {
        localStorage.setItem(PREF_KEY, val ? '1' : '0');
    }

    // ── Ctrl+Enter keyboard intercept ─────────────────────────────────────────
    var _dispatching = false;

    function getTextarea() {
        return document.querySelector('textarea');
    }

    function insertNewline(ta) {
        var start = ta.selectionStart;
        var end = ta.selectionEnd;
        var newValue = ta.value.slice(0, start) + '\n' + ta.value.slice(end);
        var setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
        setter.call(ta, newValue);
        ta.dispatchEvent(new Event('input', { bubbles: true }));
        ta.setSelectionRange(start + 1, start + 1);
    }

    document.addEventListener('keydown', function (e) {
        if (_dispatching) return;
        if (!getCtrlEnterPref()) return;
        var ta = getTextarea();
        if (!ta || e.target !== ta) return;

        if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
            // Block submit — insert newline instead
            e.stopImmediatePropagation();
            e.preventDefault();
            insertNewline(ta);
        } else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            // Submit — re-dispatch plain Enter so Chainlit handles it
            e.stopImmediatePropagation();
            e.preventDefault();
            _dispatching = true;
            ta.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'Enter', code: 'Enter', keyCode: 13, which: 13,
                bubbles: true, cancelable: true
            }));
            _dispatching = false;
        }
    }, true);

    // ── Sidebar ───────────────────────────────────────────────────────────────
    function updateToggleBtn(btn) {
        var on = getCtrlEnterPref();
        btn.textContent = on ? '⌨️ Ctrl+Enter to send: ON' : '⌨️ Ctrl+Enter to send: OFF';
        btn.className = 'pat-toggle' + (on ? ' pat-toggle-on' : '');
    }

    function inject() {
        if (document.getElementById('pat-panel')) return;
        var base = 'http://' + window.location.hostname + ':' + API_PORT;

        var panel = document.createElement('div');
        panel.id = 'pat-panel';

        panel.innerHTML =
            '<div class="pat-section-title">Toolkit</div>' +

            '<div class="pat-section-title pat-section-sep">Navigate</div>' +
            '<a href="' + base + '/docs"          target="_blank"><span>🔧</span> API Docs</a>' +
            '<a href="' + base + '/profiles"      target="_blank"><span>👤</span> Profiles</a>' +
            '<a href="' + base + '/health"        target="_blank"><span>💚</span> Health</a>' +
            '<a href="' + base + '/conversations" target="_blank"><span>💬</span> Conversations</a>' +
            '<a href="' + base + '/mcp-ui"        target="_blank"><span>🔌</span> Manage MCPs</a>' +
            '<a href="' + base + '/outputs-ui"    target="_blank"><span>📢</span> Outputs</a>' +
            '<a href="' + base + '/schedules-ui" target="_blank"><span>📅</span> Schedules</a>' +

            '<div class="pat-section-title pat-section-sep">Ollama</div>' +
            '<a href="http://' + window.location.hostname + ':11434" target="_blank"><span>🦙</span> Ollama</a>' +
            '<a href="https://ollama.com/library" target="_blank"><span>📦</span> Model Library</a>' +

            '<div class="pat-section-title pat-section-sep">Docs</div>' +
            '<a href="https://docs.chainlit.io"       target="_blank"><span>📖</span> Chainlit</a>' +
            '<a href="https://modelcontextprotocol.io" target="_blank"><span>🔌</span> MCP</a>' +

            '<div class="pat-section-title pat-section-sep">Settings</div>';

        var btn = document.createElement('button');
        updateToggleBtn(btn);
        btn.addEventListener('click', function () {
            setCtrlEnterPref(!getCtrlEnterPref());
            updateToggleBtn(btn);
        });
        panel.appendChild(btn);

        document.body.appendChild(panel);
    }

    function tryInject() {
        if (document.body) { inject(); }
        else { document.addEventListener('DOMContentLoaded', inject); }
    }

    tryInject();
    var _pushState = history.pushState;
    history.pushState = function () {
        _pushState.apply(history, arguments);
        setTimeout(inject, 300);
    };
})();
