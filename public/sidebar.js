(function () {
    var API_PORT = window.__PAT_API_PORT__ || 8002;

    function inject() {
        if (document.getElementById('pat-nav')) return;
        var base = 'http://' + window.location.hostname + ':' + API_PORT;
        var nav = document.createElement('div');
        nav.id = 'pat-nav';
        nav.innerHTML =
            '<a href="' + base + '/docs" target="_blank">🔧 API Docs</a>' +
            '<a href="' + base + '/profiles" target="_blank">👤 Profiles</a>' +
            '<a href="' + base + '/health" target="_blank">💚 Health</a>';
        document.body.appendChild(nav);
    }

    function tryInject() {
        if (document.body) { inject(); }
        else { document.addEventListener('DOMContentLoaded', inject); }
    }

    tryInject();
    // Re-inject after Chainlit SPA navigations
    var _pushState = history.pushState;
    history.pushState = function () {
        _pushState.apply(history, arguments);
        setTimeout(inject, 300);
    };
})();
