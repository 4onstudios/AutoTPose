(() => {
  const BUTTON_ID = 'autotpose-mesh2motion-button';
  const STATUS_ID = 'autotpose-mesh2motion-status';
  const BRIDGE_URL = 'http://127.0.0.1:8765';

  function ensureCss() {
    const style = document.createElement('style');
    style.textContent = `
      #${BUTTON_ID} {
        position: fixed;
        right: 22px;
        bottom: 24px;
        z-index: 2147483647;
        background: linear-gradient(135deg, #38bdf8, #2563eb);
        color: white;
        border: none;
        border-radius: 999px;
        padding: 0.8rem 1.2rem;
        font-size: 14px;
        font-weight: 700;
        letter-spacing: 0.01em;
        box-shadow: 0 12px 24px rgba(37, 99, 235, 0.35);
        cursor: pointer;
        font-family: Inter, system-ui, sans-serif;
      }
      #${BUTTON_ID}:hover { filter: brightness(1.06); }
      #${STATUS_ID} {
        position: fixed;
        right: 22px;
        bottom: 86px;
        z-index: 2147483647;
        min-width: 260px;
        max-width: 420px;
        background: rgba(15, 23, 42, 0.92);
        color: white;
        border: 1px solid rgba(148, 163, 184, 0.35);
        border-radius: 14px;
        padding: 0.75rem 0.9rem;
        font-size: 12px;
        line-height: 1.45;
        font-family: Inter, system-ui, sans-serif;
        box-shadow: 0 18px 36px rgba(0, 0, 0, 0.24);
        display: none;
      }
      #${STATUS_ID}.visible { display: block; }
      #${STATUS_ID}.error { border-color: rgba(248, 113, 113, 0.7); }
      #${STATUS_ID}.ok { border-color: rgba(74, 222, 128, 0.7); }
    `;
    document.head.appendChild(style);
  }

  function ensureStatus() {
    let status = document.getElementById(STATUS_ID);
    if (!status) {
      status = document.createElement('div');
      status.id = STATUS_ID;
      status.setAttribute('role', 'status');
      document.body.appendChild(status);
    }
    return status;
  }

  function showStatus(message, type = 'ok', durationMs = 4000) {
    const status = ensureStatus();
    status.textContent = message;
    status.className = `visible ${type}`;
    clearTimeout(status._timer);
    status._timer = setTimeout(() => {
      status.classList.remove('visible');
    }, durationMs);
  }

  function ensureButton() {
    let button = document.getElementById(BUTTON_ID);
    if (button) return button;

    button = document.createElement('button');
    button.id = BUTTON_ID;
    button.type = 'button';
    button.textContent = 'AutoTPose T-pose';
    button.title = 'AutoTPose the selected GLB/GTLF model using the local Blender bridge';
    button.addEventListener('click', () => {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = '.glb,.gltf';
      input.addEventListener('change', async (event) => {
        const [file] = event.target.files || [];
        if (!file) return;

        const formData = new FormData();
        formData.append('file', file, file.name);

        showStatus('Processing model with AutoTPose…', 'ok', 10000);

        try {
          const response = await fetch(`${BRIDGE_URL}/auto-t-pose`, {
            method: 'POST',
            body: formData,
          });

          if (!response.ok) {
            const errorText = await response.text();
            throw new Error(errorText || 'AutoTPose bridge returned an error.');
          }

          const blob = await response.blob();
          const url = URL.createObjectURL(blob);
          const anchor = document.createElement('a');
          anchor.href = url;
          anchor.download = file.name.replace(/\.[^/.]+$/, '') + '_tpose.glb';
          anchor.click();
          URL.revokeObjectURL(url);
          showStatus('AutoTPose complete: GLB downloaded.', 'ok', 5000);
        } catch (error) {
          console.error('[AutoTPose]', error);
          showStatus(
            `AutoTPose failed. Start the bridge script at ${BRIDGE_URL} and try again. ${error.message}`,
            'error',
            8000
          );
        }
      });
      input.click();
    });

    document.body.appendChild(button);
    return button;
  }

  async function pingBridge() {
    try {
      const response = await fetch(`${BRIDGE_URL}/health`, { method: 'GET' });
      return response.ok;
    } catch (error) {
      return false;
    }
  }

  function attach() {
    ensureCss();
    ensureButton();
    pingBridge().then((ok) => {
      const label = document.getElementById(BUTTON_ID);
      if (!label) return;
      label.title = ok
        ? 'AutoTPose is ready. Upload a humanoid GLB or GLTF to convert it to a T-pose.'
        : 'AutoTPose bridge is not running. Start the local bridge to enable this button.';
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', attach, { once: true });
  } else {
    attach();
  }
})();
