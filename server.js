const http = require('http');
const port = process.env.PORT || 3000;

const server = http.createServer((req, res) => {
  res.writeHead(200, { 'Content-Type': 'text/plain' });
  res.end('Hello from DO288 practice app! Listening on port 3000\n');
});

server.listen(port, () => {
  console.log(`Server running on port ${port}`);
});
