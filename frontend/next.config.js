/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export: `next build` writes plain files to out/ for S3 + CloudFront.
  // There is no Node server in production, so `next start` doesn't apply.
  output: "export",
  // /management -> management/index.html, which S3 and simple static servers
  // resolve without rewrite rules.
  trailingSlash: true,
};

module.exports = nextConfig;
