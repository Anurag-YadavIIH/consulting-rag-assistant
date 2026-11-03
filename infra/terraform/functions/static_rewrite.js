// CloudFront Function (cloudfront-js-2.0), viewer request, S3 behavior only.
// The static Next.js export writes each page as <path>/index.html
// (trailingSlash), and S3 doesn't resolve folder index files itself:
//   /management/  -> /management/index.html
//   /management   -> /management/index.html
//   /_next/static/chunks/app.js and other files with an extension: unchanged
// "/" is left alone; the distribution's default root object handles it.
function handler(event) {
  var request = event.request;
  var uri = request.uri;

  if (uri === "/") {
    return request;
  }
  if (uri.endsWith("/")) {
    request.uri = uri + "index.html";
    return request;
  }
  var lastSegment = uri.substring(uri.lastIndexOf("/") + 1);
  if (lastSegment.indexOf(".") === -1) {
    request.uri = uri + "/index.html";
  }
  return request;
}
