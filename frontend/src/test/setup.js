import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// @testing-library/dom 10 still detects fake timers by looking for a global
// `jest`; without it `waitFor` falls back to real timers that Vitest has
// already faked, and hangs forever. Shim just the entry point it calls.
globalThis.jest ??= { advanceTimersByTime: (ms) => vi.advanceTimersByTime(ms) }

afterEach(() => {
  cleanup()
})
