#!/bin/bash
echo "Startup config loaded:"
cat /app/config.json
python3 -m http.server 8080
