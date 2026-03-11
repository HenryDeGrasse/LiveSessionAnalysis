// @ts-check
const { withSentryConfig } = require("@sentry/nextjs");

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
};

const hasClientSentryDsn = Boolean(process.env.NEXT_PUBLIC_SENTRY_DSN);
const hasServerSentryDsn = Boolean(process.env.SENTRY_DSN || process.env.NEXT_PUBLIC_SENTRY_DSN);

// Wrap with Sentry only when a DSN is configured.
// When the relevant DSN is absent, that side's plugin stays disabled so builds
// still succeed without a Sentry auth token.
const sentryWebpackPluginOptions = {
  // Suppresses source map upload logs during build
  silent: true,
  disableServerWebpackPlugin: !hasServerSentryDsn,
  disableClientWebpackPlugin: !hasClientSentryDsn,
};

module.exports = withSentryConfig(nextConfig, sentryWebpackPluginOptions);
