import * as Sentry from "@sentry/nextjs";

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT || "development",
    // Capture 10% of transactions for performance monitoring
    tracesSampleRate: 0.1,
    // Only print debug output in development
    debug: process.env.NODE_ENV === "development",
  });
}
