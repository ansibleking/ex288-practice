const http = require('http');
const { Client } = require('pg');

const DATABASE_NAME = process.env.DATABASE_NAME || 'not-set';
const DATABASE_PORT = process.env.DATABASE_PORT || 'not-set';
const DATABASE_HOST = process.env.DATABASE_HOST || 'not-set';
const DATABASE_USER = process.env.DATABASE_USER || 'not-set';
const DATABASE_PASSWORD = process.env.DATABASE_PASSWORD || 'not-set';
const APP_PORT = process.env.APP_PORT || 'http://0.0.0.0:8080';

// parse APP_PORT like http://0.0.0.0:80 to get the actual bind port
const portMatch = APP_PORT.match(/:(\d+)$/);
const listenPort = portMatch ? portMatch[1] : '8080';

const server = http.createServer(async (req, res) => {
  let dbStatus = 'not attempted';
  try {
    const client = new Client({
      host: DATABASE_HOST,
      port: DATABASE_PORT,
      database: DATABASE_NAME,
      user: DATABASE_USER,
      password: DATABASE_PASSWORD,
      connectionTimeoutMillis: 3000,
    });
    await client.connect();
    dbStatus = 'connected';
    await client.end();
  } catch (err) {
    dbStatus = `failed: ${err.message}`;
  }

  res.writeHead(200, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({
    message: 'order-frontend config verification',
    env: {
      DATABASE_NAME, DATABASE_PORT, DATABASE_HOST,
      DATABASE_USER: DATABASE_USER === 'not-set' ? 'not-set' : '***hidden***',
      APP_PORT
    },
    db_connection: dbStatus
  }, null, 2));
});

server.listen(listenPort, '0.0.0.0', () => {
  console.log(`Server listening on port ${listenPort} (from APP_PORT=${APP_PORT})`);
});
