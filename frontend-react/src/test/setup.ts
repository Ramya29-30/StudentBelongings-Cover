import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => cleanup());
// jsdom has no <dialog> modal support; model it just enough for the Modal component.
HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) { this.setAttribute('open', ''); };
HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) { this.removeAttribute('open'); this.dispatchEvent(new Event('close')); };
// Recharts measures its container; give ResizeObserver a no-op implementation.
class RO { observe() { /* noop */ } unobserve() { /* noop */ } disconnect() { /* noop */ } }
(globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver = RO;
URL.createObjectURL = () => 'blob:test';
URL.revokeObjectURL = () => undefined;
