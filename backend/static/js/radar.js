// Leaflet radar maps driven by /api/radar (RainViewer proxy).
// Animates past frames on a loop; refreshes the frame list when the SSE
// 'radar' event fires.

(function() {
  const cfg = window.PICLOCK_CONFIG;

  class RainViewerMap {
    constructor(el, mapCfg) {
      this.el = el;
      this.mapCfg = mapCfg;
      this.frames = [];
      this.layers = new Map(); // time -> TileLayer
      this.current = -1;
      this.host = 'https://tilecache.rainviewer.com';
      this.color = 2;       // RainViewer color scheme 2 = Universal Blue
      this.smooth = 1;
      this.snow = 1;
      this.size = 256;

      const center = mapCfg.center;
      this.map = L.map(el, {
        center: center,
        zoom: mapCfg.zoom,
        zoomControl: false,
        attributionControl: true,
        dragging: false,
        scrollWheelZoom: false,
        doubleClickZoom: false,
        boxZoom: false,
        keyboard: false,
        touchZoom: false,
      });
      L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png', {
        maxZoom: 18,
        attribution: '&copy; CartoDB, &copy; OpenStreetMap',
      }).addTo(this.map);

      for (const m of mapCfg.markers || []) {
        L.circleMarker(m.location, {
          radius: m.size === 'large' ? 8 : 5,
          color: m.color || 'red',
          weight: 2,
          fillOpacity: 0.9,
        }).addTo(this.map);
      }

      // The map container may still be laying out (grid, images loading, etc.)
      // when L.map() runs; without invalidateSize the view latches onto a
      // stale container size and the configured center ends up off-screen.
      const recenter = () => {
        this.map.invalidateSize({ animate: false });
        this.map.setView(mapCfg.center, mapCfg.zoom, { animate: false });
      };
      requestAnimationFrame(recenter);
      setTimeout(recenter, 250);
      window.addEventListener('resize', () => {
        this.map.invalidateSize({ animate: false });
      });
    }

    async loadFrames() {
      const r = await fetch('/api/radar');
      if (!r.ok) return;
      const data = await r.json();
      this.host = data.host;
      this.frames = data.past.slice(-10); // last 10 frames
      this.prefetch();
      if (this.timer) clearInterval(this.timer);
      this.timer = setInterval(() => this.advance(), 500);
    }

    tileUrl(frame) {
      return `${this.host}${frame.path}/${this.size}/{z}/{x}/{y}/${this.color}/${this.smooth}_${this.snow}.png`;
    }

    prefetch() {
      // Create a tile layer for each frame (hidden); we flip opacity to animate.
      for (const frame of this.frames) {
        if (this.layers.has(frame.time)) continue;
        // RainViewer's 256px tile format supports zoom 0–9. Above that,
        // fetch zoom-9 tiles and let Leaflet upscale them rather than
        // showing RainViewer's "Zoom Level Not Supported" placeholder.
        const layer = L.tileLayer(this.tileUrl(frame), {
          opacity: 0,
          maxNativeZoom: 9,
          maxZoom: 18,
          tileSize: this.size,
        });
        layer.addTo(this.map);
        this.layers.set(frame.time, layer);
      }
      // Drop stale layers
      const keep = new Set(this.frames.map(f => f.time));
      for (const [t, layer] of this.layers) {
        if (!keep.has(t)) {
          this.map.removeLayer(layer);
          this.layers.delete(t);
        }
      }
    }

    advance() {
      if (this.frames.length === 0) return;
      this.current = (this.current + 1) % this.frames.length;
      for (const [t, layer] of this.layers) {
        layer.setOpacity(0);
      }
      const frame = this.frames[this.current];
      const active = this.layers.get(frame.time);
      if (active) active.setOpacity(0.7);
    }
  }

  const maps = [];
  (cfg.radars || []).forEach((r, i) => {
    const el = document.getElementById(`radar${i + 1}`);
    if (!el) return;
    const m = new RainViewerMap(el, r);
    m.loadFrames();
    maps.push(m);
  });

  window.PICLOCK_RADAR_MAPS = maps;
})();
