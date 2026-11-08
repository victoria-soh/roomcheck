// A stand-in for the browser's WebSocket, so component tests never open a connection.
import type { ScanSnapshot } from "../api/types";

export class FakeSocket {
  static all: FakeSocket[] = [];
  static get last(): FakeSocket | null {
    return FakeSocket.all[FakeSocket.all.length - 1] ?? null;
  }
  onmessage: ((m: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;

  constructor(readonly url: string) {
    FakeSocket.all.push(this);
  }

  send(snapshot: ScanSnapshot) {
    this.onmessage?.({ data: JSON.stringify({ type: "state", ...snapshot }) } as MessageEvent);
  }

  sendRaw(message: object) {
    this.onmessage?.({ data: JSON.stringify(message) } as MessageEvent);
  }

  /** The connection drops without a final state. */
  drop() {
    this.onclose?.();
  }

  close() {
    this.closed = true;
  }
}
