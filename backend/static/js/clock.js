// Clock ticking — analog (CSS rotate) or digital.
(function() {
  const cfg = window.PICLOCK_CONFIG;
  const useUTC = cfg.clockUTC;

  function now() {
    const d = new Date();
    if (useUTC) {
      return {
        h: d.getUTCHours(),
        m: d.getUTCMinutes(),
        s: d.getUTCSeconds(),
        ms: d.getUTCMilliseconds(),
        date: d,
      };
    }
    return {
      h: d.getHours(),
      m: d.getMinutes(),
      s: d.getSeconds(),
      ms: d.getMilliseconds(),
      date: d,
    };
  }

  // --- Analog ---
  const analog = document.getElementById('analog-clock');
  if (analog) {
    const theme = analog.dataset.theme || 'icons-lightblue';
    const suffix = theme === 'icons-darkblue' ? '-darkblue'
                  : theme === 'icons-darkgreen' ? '-darkgreen'
                  : '';
    document.getElementById('clockface').src = `/static/images/clockface3${suffix}.png`;
    document.getElementById('hourhand').src  = `/static/images/hourhand${suffix}.png`;
    document.getElementById('minhand').src   = `/static/images/minhand${suffix}.png`;
    document.getElementById('sechand').src   = `/static/images/sechand${suffix}.png`;

    const hourEl = document.getElementById('hourhand');
    const minEl = document.getElementById('minhand');
    const secEl = document.getElementById('sechand');

    function drawAnalog() {
      const t = now();
      const h = (t.h % 12) + t.m / 60 + t.s / 3600;
      const m = t.m + t.s / 60;
      const s = t.s + t.ms / 1000;
      hourEl.style.transform = `translate(-50%, -50%) rotate(${h * 30}deg)`;
      minEl.style.transform  = `translate(-50%, -50%) rotate(${m * 6}deg)`;
      secEl.style.transform  = `translate(-50%, -50%) rotate(${s * 6}deg)`;
    }
    drawAnalog();
    setInterval(drawAnalog, 100);
  }

  // --- Digital ---
  const digital = document.getElementById('digital-clock');
  if (digital) {
    function drawDigital() {
      const t = now();
      const pad = n => String(n).padStart(2, '0');
      digital.textContent = `${pad(t.h)}:${pad(t.m)}:${pad(t.s)}`;
    }
    drawDigital();
    setInterval(drawDigital, 500);
  }

  // --- Date strip ---
  const dateStrip = document.getElementById('date-strip');
  if (dateStrip) {
    function drawDate() {
      const d = new Date();
      const opts = { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' };
      if (useUTC) opts.timeZone = 'UTC';
      dateStrip.textContent = d.toLocaleDateString(undefined, opts);
    }
    drawDate();
    setInterval(drawDate, 60000);
  }
})();
