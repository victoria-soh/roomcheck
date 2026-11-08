// A stand-in WebSocket for the locator: tests push readings and see whether it was closed.
export class FakeLocatorSocket {
  static all: FakeLocatorSocket[] = [];
  static get last(): FakeLocatorSocket | null {
    return FakeLocatorSocket.all[FakeLocatorSocket.all.length - 1] ?? null;
  }
  onmessage: ((m: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;

  constructor(readonly url: string) {
    FakeLocatorSocket.all.push(this);
  }

  push(message: object) {
    this.onmessage?.({ data: JSON.stringify(message) } as MessageEvent);
  }

  /** The server ended the session (e.g. after 10 minutes). */
  end() {
    this.onclose?.();
  }

  close() {
    this.closed = true;
  }
}
