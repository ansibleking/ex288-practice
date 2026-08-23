const http = require('http');

const server = http.createServer((req, res) => {
  if (req.url === '/api/products') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    return res.end(JSON.stringify([
      { id: 1, name: 'Petrol 95', price: 1.45 },
      { id: 2, name: 'Diesel', price: 1.38 }
    ]));
  }
  res.writeHead(200);
  res.end('petroldb-backend API is up\n');
});

server.listen(8080, '0.0.0.0', () => console.log('Backend listening on 8080'));
