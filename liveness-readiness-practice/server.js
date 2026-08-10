const http = require('http');

let isReady = true;
let isAlive = true;

const server = http.createServer((req, res) => {
  // Toggle endpoints - simulate the app going unhealthy on demand
  if (req.url === '/toggle-ready') {
    isReady = !isReady;
    console.log(`Readiness toggled to: ${isReady}`);
    res.writeHead(200);
    return res.end(`isReady is now ${isReady}\n`);
  }
  if (req.url === '/toggle-alive') {
    isAlive = !isAlive;
    console.log(`Liveness toggled to: ${isAlive}`);
    res.writeHead(200);
    return res.end(`isAlive is now ${isAlive}\n`);
  }

  // Liveness probe target - TCP just needs port open, but let's also
  // give an HTTP version for visibility/logging
  if (req.url === '/livez') {
    if (isAlive) {
      res.writeHead(200);
      return res.end('alive\n');
    } else {
      // don't respond successfully - simulates a hung/broken process
      res.writeHead(500);
      return res.end('unhealthy\n');
    }
  }

  // Readiness probe target
  if (req.url === '/readyz') {
    if (isReady) {
      res.writeHead(200);
      return res.end('ready\n');
    } else {
      res.writeHead(503);
      return res.end('not ready\n');
    }
  }

  res.writeHead(200);
  res.end(`Hello - isAlive=${isAlive} isReady=${isReady}\n`);
});

server.listen(8080, '0.0.0.0', () => {
  console.log('Server listening on port 8080');
});
