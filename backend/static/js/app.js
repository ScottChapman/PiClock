// SSE listener: bridges backend events into HTMX trigger events and radar refresh.
(function() {
  if (!window.EventSource) return;
  const es = new EventSource('/api/events');

  es.addEventListener('weather', () => {
    // HTMX: elements with `hx-trigger="... sse:weather"` auto-refresh.
    // We also dispatch a custom event for anything else that cares.
    document.body.dispatchEvent(new CustomEvent('piclock:weather'));
    document.querySelectorAll('[hx-trigger*="sse:weather"]').forEach(el => {
      if (window.htmx) htmx.trigger(el, 'sse:weather');
    });
  });

  es.addEventListener('radar', () => {
    (window.PICLOCK_RADAR_MAPS || []).forEach(m => m.loadFrames());
  });

  es.onerror = () => {
    // EventSource auto-reconnects; nothing to do.
  };
})();
