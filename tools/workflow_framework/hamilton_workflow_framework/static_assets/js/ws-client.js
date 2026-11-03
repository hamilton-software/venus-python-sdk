class WsClient {
  constructor(url) {
    this.url = url;
    this.socket = null;
    this.handlers = {};
    this._backoff = 1000;
    this._closedByUser = false;
  }

  connect() {
    this._closedByUser = false;
    this.socket = new WebSocket(this.url);
    this.socket.addEventListener("open", () => {
      this._backoff = 1000;
      this._emit("__open__", {});
    });
    this.socket.addEventListener("message", (evt) => {
      let msg;
      try {
        msg = JSON.parse(evt.data);
      } catch (e) {
        console.error("Bad WS message", evt.data);
        return;
      }
      this._emit(msg.type, msg);
    });
    this.socket.addEventListener("close", () => {
      this._emit("__close__", {});
      if (!this._closedByUser) {
        setTimeout(() => this.connect(), this._backoff);
        this._backoff = Math.min(this._backoff * 2, 10000);
      }
    });
    this.socket.addEventListener("error", () => {
      this.socket.close();
    });
  }

  onMessage(type, handler) {
    if (!this.handlers[type]) this.handlers[type] = [];
    this.handlers[type].push(handler);
  }

  _emit(type, msg) {
    (this.handlers[type] || []).forEach((h) => h(msg));
  }

  send(obj) {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(obj));
    } else {
      console.warn("WS not open, dropping message", obj);
    }
  }
}
