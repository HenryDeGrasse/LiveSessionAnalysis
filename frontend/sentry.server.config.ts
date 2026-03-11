import * as Sentry from "@sentry/nextjs";

// Server-side Sentry uses the non-public DSN env var; fall back to the public one.
const dsn = process.env.SENTRY_DSN || process.env.NEXT_PUBLIC_SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.SENTRY_ENVIRONMENT || process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT || "development",
    // Capture 10% of transactions for performance monitoring
    tracesSampleRate: 0.1,
    debug: process.env.NODE_ENV === "development",
  });
}
