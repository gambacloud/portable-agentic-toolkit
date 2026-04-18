(function () {
    var API_PORT = window.__PAT_API_PORT__ || 8002;

    function inject() {
        if (document.getElementById('pat-panel')) return;
        var base = 'http://' + window.location.hostname + ':' + API_PORT;

        var panel = document.createElement('div');
        panel.id = 'pat-panel';

        panel.innerHTML =
            '<div class="pat-section-title">Toolkit</div>' +

            '<div class="pat-section-title pat-section-sep">Navigate</div>' +
            '<a href="' + base + '/docs"        target="_blank"><span>🔧</span> API Docs</a>' +
            '<a href="' + base + '/profiles"    target="_blank"><span>👤</span> Profiles</a>' +
            '<a href="' + base + '/health"      target="_blank"><span>💚</span> Health</a>' +
            '<a href="' + base + '/conversations" target="_blank"><span>💬</span> Conversations</a>' +
            '<a href="' + base + '/mcp-ui"      target="_blank"><span>🔌</span> Manage MCPs</a>' +

            '<div class="pat-section-title pat-section-sep">Ollama</div>' +
            '<a href="http://' + window.location.hostname + ':11434" target="_blank"><span>🦙</span> Ollama</a>' +
            '<a href="https://ollama.com/library" target="_blank"><span>📦</span> Model Library</a>' +

            '<div class="pat-section-title pat-section-sep">Docs</div>' +
            '<a href="https://docs.chainlit.io"  target="_blank"><span>📖</span> Chainlit</a>' +
            '<a href="https://docs.crewai.com"   target="_blank"><span>🤖</span> CrewAI</a>' +
            '<a href="https://modelcontextprotocol.io" target="_blank"><span>🔌</span> MCP</a>';

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
