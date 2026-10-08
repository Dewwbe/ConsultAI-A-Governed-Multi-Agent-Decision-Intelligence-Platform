/** Timing for live updates. Mutable so tests can shorten it; production uses the defaults. */
export const liveConfig = {
  /** Delays between stream reconnection attempts before falling back to polling. */
  retryDelaysMs: [1000, 2000, 4000],
  /** How often to poll while the live stream is unavailable and the run is still running. */
  pollMs: 2000,
};
