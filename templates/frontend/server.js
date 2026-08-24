const http = require('http');

const BACKEND_API_URL = process.env.BACKEND_API_URL || 'not-set';

const server = http.createServer((req, res) => {
  if (req.url === '/health') {
    res.writeHead(200);
    return res.end('catalog-ui ok\n');
  }
  const url = `${BACKEND_API_URL}/api/products`;
  http.get(url, (backendRes) => {
    let data = '';
    backendRes.on('data', chunk => data += chunk);
    backendRes.on('end', () => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        message: 'catalog-ui connected to backend',
        backend_url: BACKEND_API_URL,
        products: JSON.parse(data)
      }, null, 2));
    });
  }).on('error', (err) => {
    res.writeHead(502, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      message: 'catalog-ui FAILED to reach backend',
      backend_url: BACKEND_API_URL,
      error: err.message
    }, null, 2));
  });
});

server.listen(8080, '0.0.0.0', () => console.log('catalog-ui listening on 8080, backend=' + BACKEND_API_URL));
