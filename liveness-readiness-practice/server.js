const http = require('http');

let isReady = false;
// simulate app taking 15s to become "ready" (e.g. warming cache, connecting to DB)
setTimeout(() => { isReady = true; console.log('App is now ready'); }, 15000);

const server = http.createServer((req, res) => {
  if (req.url === '/healthz') {
    // liveness-style check: just confirm process is alive
    res.writeHead(200);
    return res.end('alive');
  }
  if (req.url === '/readyz') {
    // readiness-style check: confirm app is ready to serve traffic
    if (isReady) {
      res.writeHead(200);
      return res.end('ready');
    } else {
      res.writeHead(503);
      return res.end('not ready yet');
    }
  }
  res.writeHead(200);
  res.end('Hello from probes-practice app\n');
});

server.listen(8080, '0.0.0.0', () => {
  console.log('Server listening on port 8080');
});
