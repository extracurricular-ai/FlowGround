// WebSocket client for the Flowground run protocol (PROTOCOL.md, "WebSocket: /api/runs").
// One socket hosts many sequential runs; it is opened lazily on the first Run/Step
// and kept for subsequent runs.

export const SERVER_DOWN_MSG =
  'Can’t reach the flow server — is it running? (cd server && uvicorn app.main:app --reload)';

export class RunClient {
  constructor(handlers) {
    this.handlers = handlers || {};
    this.ws = null;
    this.opening = null;
  }

  // Resolves once the socket is open; rejects if the connection cannot be made.
  connect() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return Promise.resolve();
    if (this.opening) return this.opening;
    this.opening = new Promise((resolve, reject) => {
      let sock;
      try {
        const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        sock = new WebSocket(proto + '//' + window.location.host + '/api/runs');
      } catch (e) {
        this.opening = null;
        reject(e);
        return;
      }
      let opened = false;
      sock.onopen = () => {
        opened = true;
        this.ws = sock;
        this.opening = null;
        resolve();
      };
      sock.onmessage = (ev) => {
        let msg;
        try { msg = JSON.parse(ev.data); } catch (e) { return; }
        if (this.handlers.onEvent) this.handlers.onEvent(msg);
      };
      sock.onclose = () => {
        if (this.ws === sock) this.ws = null;
        if (!opened) {
          this.opening = null;
          reject(new Error('connect_failed'));
        } else if (this.handlers.onDisconnect) {
          // Open socket dropped (e.g. server died mid-run).
          this.handlers.onDisconnect();
        }
      };
    });
    return this.opening;
  }

  send(msg) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
      return true;
    }
    return false;
  }

  close() {
    const sock = this.ws;
    this.ws = null;
    if (sock) {
      sock.onclose = null;
      sock.onmessage = null;
      try { sock.close(); } catch (e) {}
    }
  }
}
